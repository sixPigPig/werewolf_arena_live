from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.admin.errors import (
    AdminAPIProblem,
    admin_api_problem_handler,
    admin_request_validation_handler,
)
from app.api.router import api_router
from app.core.config import settings
from app.v2.live_runtime import build_v2_live_runtime
from app.v2.router import public_router as api_v2_router


def create_application() -> FastAPI:
    app = FastAPI(title=settings.app_name)
    app.add_exception_handler(AdminAPIProblem, admin_api_problem_handler)
    app.add_exception_handler(RequestValidationError, admin_request_validation_handler)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix=settings.api_v1_prefix.rstrip("/"))
    app.include_router(api_v2_router, prefix="/api/v2")
    app.state.v2_live_runtime = build_v2_live_runtime()
    return app


app = create_application()
