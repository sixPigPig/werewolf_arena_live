from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admin import AdminSession


@dataclass(frozen=True)
class IssuedAdminSession:
    record: AdminSession
    session_token: str
    csrf_token: str


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def hash_admin_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def create_admin_session(
    db: Session,
    *,
    user_id: int,
    ttl_seconds: int,
    ip_address: str | None,
    user_agent: str | None,
) -> IssuedAdminSession:
    session_token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(48)
    record = AdminSession(
        id=str(uuid4()),
        user_id=user_id,
        token_hash=hash_admin_secret(session_token),
        csrf_token_hash=hash_admin_secret(csrf_token),
        expires_at=utc_now() + timedelta(seconds=ttl_seconds),
        ip_address=ip_address[:45] if ip_address else None,
        user_agent=user_agent[:512] if user_agent else None,
    )
    db.add(record)
    return IssuedAdminSession(
        record=record,
        session_token=session_token,
        csrf_token=csrf_token,
    )


def find_admin_session(db: Session, session_token: str) -> AdminSession | None:
    token_hash = hash_admin_secret(session_token)
    return db.scalar(select(AdminSession).where(AdminSession.token_hash == token_hash))


def admin_session_is_expired(session: AdminSession, *, now: datetime | None = None) -> bool:
    return as_utc(session.expires_at) <= as_utc(now or utc_now())


def csrf_token_matches(session: AdminSession, candidate: str | None) -> bool:
    if not candidate or len(candidate) > 512:
        return False
    candidate_hash = hash_admin_secret(candidate)
    return hmac.compare_digest(candidate_hash, session.csrf_token_hash)


def rotate_admin_csrf_token(session: AdminSession) -> str:
    csrf_token = secrets.token_urlsafe(48)
    session.csrf_token_hash = hash_admin_secret(csrf_token)
    return csrf_token
