from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.public import PublicSession
from app.models.user import User


@dataclass(frozen=True)
class IssuedPublicSession:
    record: PublicSession
    session_token: str
    csrf_token: str


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def hash_public_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_guest_public_session(
    db: Session,
    *,
    ttl_seconds: int,
) -> IssuedPublicSession:
    guest_subject = uuid4().hex
    user = User(
        email=f"guest-{guest_subject}@guest.invalid",
        display_name="Guest",
        auth_provider="guest",
        auth_subject=guest_subject,
        admin_role=None,
        is_active=True,
    )
    db.add(user)
    db.flush()

    session_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(48)
    now = utc_now()
    record = PublicSession(
        id=str(uuid4()),
        user_id=user.id,
        token_hash=hash_public_secret(session_token),
        csrf_token_hash=hash_public_secret(csrf_token),
        created_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
        revoked_at=None,
    )
    db.add(record)
    db.flush()
    return IssuedPublicSession(
        record=record,
        session_token=session_token,
        csrf_token=csrf_token,
    )


def find_public_session(db: Session, session_token: str) -> PublicSession | None:
    token_hash = hash_public_secret(session_token)
    return db.query(PublicSession).filter(PublicSession.token_hash == token_hash).one_or_none()


def public_session_is_expired(
    session: PublicSession,
    *,
    now: datetime | None = None,
) -> bool:
    return as_utc(session.expires_at) <= as_utc(now or utc_now())


def rotate_public_csrf_token(session: PublicSession) -> str:
    csrf_token = secrets.token_urlsafe(48)
    session.csrf_token_hash = hash_public_secret(csrf_token)
    return csrf_token


def refresh_public_session(session: PublicSession, *, ttl_seconds: int) -> None:
    session.expires_at = utc_now() + timedelta(seconds=ttl_seconds)


def public_csrf_token_matches(session: PublicSession, candidate: str | None) -> bool:
    if not candidate:
        return False
    candidate_hash = hash_public_secret(candidate)
    return hmac.compare_digest(candidate_hash, session.csrf_token_hash)


def delete_expired_public_sessions(db: Session, *, now: datetime | None = None) -> int:
    cutoff = as_utc(now or utc_now())
    expired_user_ids = set(
        db.scalars(
            select(PublicSession.user_id).where(PublicSession.expires_at <= cutoff)
        )
    )
    deleted_count = int(
        db.query(PublicSession)
        .filter(PublicSession.expires_at <= cutoff)
        .delete(synchronize_session=False)
    )
    for user_id in expired_user_ids:
        has_session = (
            db.query(PublicSession.id)
            .filter(PublicSession.user_id == user_id)
            .first()
            is not None
        )
        if has_session:
            continue
        user = db.get(User, user_id)
        if user is not None and user.auth_provider == "guest":
            db.delete(user)
    return deleted_count
