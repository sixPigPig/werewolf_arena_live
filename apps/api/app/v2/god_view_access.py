from __future__ import annotations

import hashlib
import hmac
import secrets


def issue_god_view_access_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, god_view_token_sha256(token)


def god_view_token_sha256(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def verify_god_view_access_token(*, token: str, expected_sha256: str) -> bool:
    if not 32 <= len(token) <= 128 or len(expected_sha256) != 64:
        return False
    return hmac.compare_digest(god_view_token_sha256(token), expected_sha256)
