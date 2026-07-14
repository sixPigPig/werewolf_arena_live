from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.rule_sets.telemetry import render_rule_set_metrics
from app.werewolf.execution_telemetry import render_action_execution_metrics
from app.werewolf.quality_evaluation_telemetry import render_quality_evaluation_metrics
from app.werewolf.quality_telemetry import render_speech_quality_metrics
from app.werewolf.worker_telemetry import render_live_run_metrics


router = APIRouter()


@router.get("", include_in_schema=False)
def read_metrics(db: Session = Depends(get_db)) -> Response:
    try:
        content = render_live_run_metrics(
            db,
            reaper_max_age_seconds=settings.live_run_reaper_probe_max_age_seconds,
            stale_grace_seconds=settings.live_run_reaper_stale_grace_seconds,
            max_attempts=settings.live_run_reaper_max_attempts,
        )
        content += render_rule_set_metrics(db)
        content += render_speech_quality_metrics()
        content += render_action_execution_metrics()
        content += render_quality_evaluation_metrics(
            db,
            worker_max_age_seconds=settings.quality_evaluation_probe_max_age_seconds,
        )
    except SQLAlchemyError:
        return Response(
            content="# metrics unavailable\n",
            media_type="text/plain; version=0.0.4",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"Cache-Control": "no-store"},
        )
    return Response(
        content=content,
        media_type="text/plain; version=0.0.4",
        headers={"Cache-Control": "no-store"},
    )
