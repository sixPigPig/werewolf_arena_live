from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.config import settings

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")


@dataclass
class AdminAPIProblem(Exception):
    status_code: int
    code: str
    title: str
    detail: str
    extensions: dict[str, Any] = field(default_factory=dict)


def request_id_for(request: Request) -> str:
    existing = getattr(request.state, "request_id", None)
    if isinstance(existing, str) and _REQUEST_ID_RE.fullmatch(existing):
        return existing

    supplied = request.headers.get("x-request-id", "")
    request_id = supplied if _REQUEST_ID_RE.fullmatch(supplied) else uuid4().hex
    request.state.request_id = request_id
    return request_id


async def admin_api_problem_handler(request: Request, exc: AdminAPIProblem) -> JSONResponse:
    request_id = request_id_for(request)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "type": f"urn:werewolf-arena:admin-problem:{exc.code}",
            "title": exc.title,
            "status": exc.status_code,
            "detail": exc.detail,
            "code": exc.code,
            "request_id": request_id,
            **exc.extensions,
        },
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "X-Request-ID": request_id,
        },
        media_type="application/problem+json",
    )


async def admin_request_validation_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    admin_prefix = f"{settings.api_v1_prefix.rstrip('/')}/admin"
    if not (
        request.url.path == admin_prefix
        or request.url.path.startswith(f"{admin_prefix}/")
    ):
        return await request_validation_exception_handler(request, exc)

    errors: list[dict[str, str]] = []
    for error in exc.errors():
        location = [str(part) for part in error.get("loc", ()) if part not in {"body"}]
        errors.append(
            {
                "field": ".".join(location),
                "message": str(error.get("msg") or "Invalid value"),
            }
        )
    return await admin_api_problem_handler(
        request,
        AdminAPIProblem(
            status_code=422,
            code="admin_request_invalid",
            title="Invalid admin request",
            detail="One or more request fields are invalid.",
            extensions={"errors": errors},
        ),
    )
