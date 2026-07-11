from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import timedelta
import hashlib
import hmac
import secrets
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import httpx
import jwt
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.admin.session import as_utc, hash_admin_secret, utc_now
from app.core.config import settings
from app.models.admin import AdminOidcLoginAttempt
from app.models.user import User

_ALLOWED_ID_TOKEN_ALGORITHMS = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}


class AdminOidcError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class OidcAttemptSecrets:
    record: AdminOidcLoginAttempt
    state: str
    browser_nonce: str
    oidc_nonce: str


@dataclass(frozen=True)
class OidcIdentity:
    subject: str
    email: str
    display_name: str
    nonce: str


class OidcProvider:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client
        self._discovery: dict[str, Any] | None = None
        self._jwks: dict[str, Any] | None = None

    def authorization_url(
        self,
        *,
        state: str,
        nonce: str,
        code_verifier: str,
    ) -> str:
        discovery = self._get_discovery()
        endpoint = _required_url(discovery, "authorization_endpoint")
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode("ascii")).digest()
        ).decode("ascii").rstrip("=")
        query = urlencode(
            {
                "response_type": "code",
                "client_id": settings.admin_oidc_client_id,
                "redirect_uri": settings.admin_oidc_redirect_uri,
                "scope": "openid profile email",
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{endpoint}?{query}"

    def exchange_code(self, *, code: str, code_verifier: str) -> OidcIdentity:
        if not code or len(code) > 4096:
            raise AdminOidcError("admin_oidc_invalid_callback")
        discovery = self._get_discovery()
        token_endpoint = _required_url(discovery, "token_endpoint")
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.admin_oidc_redirect_uri,
            "client_id": settings.admin_oidc_client_id,
            "code_verifier": code_verifier,
        }
        auth: tuple[str, str] | None = None
        if settings.admin_oidc_client_auth_method == "client_secret_basic":
            auth = (settings.admin_oidc_client_id, settings.admin_oidc_client_secret)
        else:
            form["client_secret"] = settings.admin_oidc_client_secret
        try:
            response = self._http().post(token_endpoint, data=form, auth=auth)
            response.raise_for_status()
            token_payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AdminOidcError("admin_oidc_provider_unavailable") from exc
        if not isinstance(token_payload, dict) or not isinstance(token_payload.get("id_token"), str):
            raise AdminOidcError("admin_oidc_invalid_token")
        return self._verify_id_token(token_payload["id_token"], discovery)

    def _verify_id_token(
        self,
        id_token: str,
        discovery: dict[str, Any],
    ) -> OidcIdentity:
        try:
            header = jwt.get_unverified_header(id_token)
            algorithm = header.get("alg")
            key_id = header.get("kid")
            if algorithm not in _ALLOWED_ID_TOKEN_ALGORITHMS or not isinstance(key_id, str):
                raise AdminOidcError("admin_oidc_invalid_token")
            signing_key = self._signing_key(
                discovery,
                key_id=key_id,
                algorithm=algorithm,
            )
            claims = jwt.decode(
                id_token,
                key=signing_key.key,
                algorithms=[algorithm],
                audience=settings.admin_oidc_client_id,
                issuer=_issuer(),
                leeway=60,
                options={"require": ["iss", "sub", "aud", "exp", "iat", "nonce"]},
            )
        except AdminOidcError:
            raise
        except (jwt.PyJWTError, KeyError, StopIteration, TypeError, ValueError) as exc:
            raise AdminOidcError("admin_oidc_invalid_token") from exc

        subject = claims.get("sub")
        email = claims.get("email")
        nonce = claims.get("nonce")
        if (
            not isinstance(subject, str)
            or not 1 <= len(subject) <= 255
            or not isinstance(email, str)
            or not 3 <= len(email) <= 255
            or claims.get("email_verified") is not True
            or not isinstance(nonce, str)
            or not 16 <= len(nonce) <= 512
        ):
            raise AdminOidcError("admin_oidc_unverified_identity")
        display_name = claims.get("name") or claims.get("preferred_username") or email
        if not isinstance(display_name, str) or not display_name.strip():
            display_name = email
        return OidcIdentity(
            subject=subject,
            email=email.strip().lower(),
            display_name=display_name.strip()[:120],
            nonce=nonce,
        )

    def _signing_key(
        self,
        discovery: dict[str, Any],
        *,
        key_id: str,
        algorithm: str,
    ) -> jwt.PyJWK:
        for refresh in (False, True):
            if refresh:
                self._jwks = None
            jwk_set = jwt.PyJWKSet.from_dict(self._get_jwks(discovery))
            signing_key = next(
                (
                    key
                    for key in jwk_set.keys
                    if key.key_id == key_id and key.algorithm_name == algorithm
                ),
                None,
            )
            if signing_key is not None:
                return signing_key
        raise AdminOidcError("admin_oidc_invalid_token")

    def _get_discovery(self) -> dict[str, Any]:
        if self._discovery is not None:
            return self._discovery
        try:
            response = self._http().get(f"{_issuer()}/.well-known/openid-configuration")
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AdminOidcError("admin_oidc_provider_unavailable") from exc
        if not isinstance(payload, dict) or payload.get("issuer", "").rstrip("/") != _issuer():
            raise AdminOidcError("admin_oidc_invalid_discovery")
        for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            _required_url(payload, field)
        self._discovery = payload
        return payload

    def _get_jwks(self, discovery: dict[str, Any]) -> dict[str, Any]:
        if self._jwks is not None:
            return self._jwks
        try:
            response = self._http().get(_required_url(discovery, "jwks_uri"))
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AdminOidcError("admin_oidc_provider_unavailable") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
            raise AdminOidcError("admin_oidc_invalid_discovery")
        self._jwks = payload
        return payload

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=8, follow_redirects=False)
        return self._client


def create_oidc_attempt(db: Session, *, return_to: str) -> OidcAttemptSecrets:
    now = utc_now()
    db.execute(
        delete(AdminOidcLoginAttempt).where(AdminOidcLoginAttempt.expires_at <= now)
    )
    state = secrets.token_urlsafe(48)
    browser_nonce = secrets.token_urlsafe(48)
    oidc_nonce = secrets.token_urlsafe(48)
    record = AdminOidcLoginAttempt(
        id=str(uuid4()),
        state_hash=hash_admin_secret(state),
        browser_nonce_hash=hash_admin_secret(browser_nonce),
        oidc_nonce_hash=hash_admin_secret(oidc_nonce),
        code_verifier=secrets.token_urlsafe(64),
        return_to=safe_return_to(return_to),
        expires_at=now + timedelta(seconds=settings.admin_oidc_login_ttl_seconds),
    )
    db.add(record)
    db.flush()
    return OidcAttemptSecrets(
        record=record,
        state=state,
        browser_nonce=browser_nonce,
        oidc_nonce=oidc_nonce,
    )


def consume_oidc_attempt(
    db: Session,
    *,
    state: str | None,
    browser_nonce: str | None,
) -> AdminOidcLoginAttempt:
    if not state or len(state) > 512 or not browser_nonce or len(browser_nonce) > 512:
        raise AdminOidcError("admin_oidc_invalid_state")
    attempt = db.scalar(
        select(AdminOidcLoginAttempt)
        .where(AdminOidcLoginAttempt.state_hash == hash_admin_secret(state))
        .with_for_update()
    )
    if (
        attempt is None
        or attempt.consumed_at is not None
        or as_utc(attempt.expires_at) <= utc_now()
        or not hmac.compare_digest(
            attempt.browser_nonce_hash,
            hash_admin_secret(browser_nonce),
        )
    ):
        raise AdminOidcError("admin_oidc_invalid_state")
    attempt.consumed_at = utc_now()
    db.flush()
    return attempt


def resolve_oidc_user(db: Session, identity: OidcIdentity) -> tuple[User, bool]:
    provider = oidc_provider_key()
    user = db.scalar(
        select(User).where(
            User.auth_provider == provider,
            User.auth_subject == identity.subject,
        ).with_for_update()
    )
    newly_bound = False
    if user is None:
        user = db.scalar(
            select(User).where(func.lower(User.email) == identity.email).with_for_update()
        )
        if user is None or user.admin_role is None:
            raise AdminOidcError("admin_oidc_account_not_provisioned")
        if not user.is_active:
            raise AdminOidcError("admin_oidc_account_disabled")
        if user.auth_provider is not None or user.auth_subject is not None:
            raise AdminOidcError("admin_oidc_identity_mismatch")
        user.auth_provider = provider
        user.auth_subject = identity.subject
        newly_bound = True
    if not user.is_active or user.admin_role is None:
        raise AdminOidcError("admin_oidc_account_disabled")
    return user, newly_bound


def validate_oidc_nonce(attempt: AdminOidcLoginAttempt, identity: OidcIdentity) -> None:
    if not hmac.compare_digest(attempt.oidc_nonce_hash, hash_admin_secret(identity.nonce)):
        raise AdminOidcError("admin_oidc_invalid_token")


def oidc_provider_key() -> str:
    digest = hashlib.sha256(_issuer().encode("utf-8")).hexdigest()[:24]
    return f"oidc:{digest}"


def safe_return_to(value: str | None) -> str:
    if (
        not value
        or len(value) > 512
        or not value.startswith("/")
        or value.startswith("//")
        or value.startswith("/login")
        or value.startswith("/403")
    ):
        return "/content/players"
    return value


def _issuer() -> str:
    return settings.admin_oidc_issuer_url.strip().rstrip("/")


def _required_url(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.startswith(("https://", "http://")):
        raise AdminOidcError("admin_oidc_invalid_discovery")
    if settings.app_environment == "production" and not value.startswith("https://"):
        raise AdminOidcError("admin_oidc_invalid_discovery")
    return value
