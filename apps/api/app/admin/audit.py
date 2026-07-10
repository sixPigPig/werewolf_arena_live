from __future__ import annotations

import json
import re
from typing import Any
from uuid import uuid4

from fastapi import Request
from sqlalchemy.orm import Session

from app.api.admin.errors import request_id_for
from app.models.admin import AuditEvent

_SENSITIVE_KEY_PARTS = (
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "session_token",
    "csrf_token",
    "token",
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b((?:access|refresh|id|csrf|session)[_-]?token|token|password|secret|"
    r"api[_-]?key|authorization|cookie)[\"']?"
    r"\s*[:=]\s*[^\r\n]*"
)
_BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")


def record_audit_event(
    db: Session,
    *,
    request: Request,
    actor_user_id: int | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    result: str,
    reason: str | None = None,
    before: dict | list | None = None,
    after: dict | list | None = None,
) -> AuditEvent:
    event = AuditEvent(
        id=str(uuid4()),
        actor_user_id=actor_user_id,
        action=action[:120],
        resource_type=resource_type[:80],
        resource_id=resource_id[:160] if resource_id is not None else None,
        result=result[:20],
        reason=_sanitize_reason(reason),
        before=_sanitize_payload(before),
        after=_sanitize_payload(after),
        request_id=request_id_for(request),
        ip_address=request.client.host[:45] if request.client else None,
    )
    db.add(event)
    return event


def _sanitize_payload(value: dict | list | None) -> dict | list | None:
    sanitized = _sanitize_value(value, depth=0)
    return sanitized if isinstance(sanitized, (dict, list)) else None


def _sanitize_value(value: Any, *, depth: int) -> Any:
    if depth >= 8:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for index, (key, child) in enumerate(value.items()):
            if index >= 100:
                sanitized["__truncated__"] = True
                break
            normalized_key = str(key).lower().replace("-", "_")
            sanitized[str(key)[:160]] = (
                "[REDACTED]"
                if any(part in normalized_key for part in _SENSITIVE_KEY_PARTS)
                else _sanitize_value(child, depth=depth + 1)
            )
        return sanitized
    if isinstance(value, list):
        children = [_sanitize_value(child, depth=depth + 1) for child in value[:100]]
        if len(value) > 100:
            children.append("[TRUNCATED]")
        return children
    if isinstance(value, str):
        return _redact_secret_assignments(value)[:4096]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_secret_assignments(str(value))[:4096]


def _sanitize_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    try:
        structured_reason = json.loads(reason)
    except (TypeError, ValueError):
        structured_reason = None
    if isinstance(structured_reason, (dict, list)):
        sanitized = _sanitize_payload(structured_reason)
        return json.dumps(sanitized, ensure_ascii=False)[:4096]
    return _redact_secret_assignments(reason)[:4096]


def _redact_secret_assignments(value: str) -> str:
    redacted = _SECRET_ASSIGNMENT_RE.sub(r"\1=[REDACTED]", value)
    return _BEARER_TOKEN_RE.sub("Bearer [REDACTED]", redacted)
