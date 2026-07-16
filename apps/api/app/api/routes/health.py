from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.werewolf.voice_materializer import LIVE_VOICE_MATERIALIZER_WORKER_TYPE
from app.werewolf.worker_telemetry import runtime_worker_is_alive


router = APIRouter()


@router.get("")
def read_health(response: Response) -> dict[str, str]:
    response.headers["Cache-Control"] = "no-store"
    return {"status": "ok"}


@router.get("/live")
def read_liveness(response: Response) -> dict[str, str]:
    """Report process liveness without depending on external services."""
    response.headers["Cache-Control"] = "no-store"
    return {"status": "ok"}


@router.get("/ready")
def read_readiness(
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, str | dict[str, str]]:
    """Only accept traffic when PostgreSQL is reachable and fully migrated."""
    response.headers["Cache-Control"] = "no-store"
    try:
        db.execute(text("SELECT 1"))
        current_revisions = set(
            db.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )
        materializer_alive = not settings.ark_tts_enabled or runtime_worker_is_alive(
            db,
            worker_type=LIVE_VOICE_MATERIALIZER_WORKER_TYPE,
            max_age_seconds=settings.live_voice_materializer_probe_max_age_seconds,
        )
    except SQLAlchemyError:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "not_ready",
            "checks": {"database": "unavailable", "migrations": "unknown"},
        }

    expected_revisions = _expected_database_revisions()
    if current_revisions != expected_revisions:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "not_ready",
            "checks": {"database": "ok", "migrations": "outdated"},
        }

    if not materializer_alive:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "not_ready",
            "checks": {
                "database": "ok",
                "migrations": "ok",
                "live_voice_materializer": "unavailable",
            },
        }

    checks = {"database": "ok", "migrations": "ok"}
    if settings.ark_tts_enabled:
        checks["live_voice_materializer"] = "ok"
    return {"status": "ready", "checks": checks}


@lru_cache
def _expected_database_revisions() -> set[str]:
    api_root = Path(__file__).resolve().parents[3]
    config = Config(str(api_root / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    return set(script.get_heads())
