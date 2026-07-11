from functools import lru_cache
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db


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

    return {
        "status": "ready",
        "checks": {"database": "ok", "migrations": "ok"},
    }


@lru_cache
def _expected_database_revisions() -> set[str]:
    api_root = Path(__file__).resolve().parents[3]
    config = Config(str(api_root / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    return set(script.get_heads())
