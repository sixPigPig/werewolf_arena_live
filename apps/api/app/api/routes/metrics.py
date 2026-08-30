from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.rule_sets.telemetry import render_rule_set_metrics


router = APIRouter()


@router.get("", include_in_schema=False)
def read_metrics(db: Session = Depends(get_db)) -> Response:
    try:
        content = render_rule_set_metrics(db)
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
