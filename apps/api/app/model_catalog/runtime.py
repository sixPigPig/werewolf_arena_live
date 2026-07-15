from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionLocal
from app.models.model_configuration import ModelConfigurationRecord


@dataclass(frozen=True)
class RuntimeModelConfiguration:
    provider: str
    model_id: str
    parameters: dict[str, Any]


def catalog_model_names(provider: str) -> tuple[str, ...] | None:
    """Return enabled catalog models, or None when this provider has no catalog yet."""

    try:
        with SessionLocal() as db:
            rows = list(
                db.scalars(
                    select(ModelConfigurationRecord)
                    .where(ModelConfigurationRecord.provider == provider)
                    .order_by(ModelConfigurationRecord.created_at, ModelConfigurationRecord.model_id)
                )
            )
    except SQLAlchemyError:
        return None
    if not rows:
        return None
    return tuple(row.model_id for row in rows if row.available and row.enabled)


def catalog_all_model_names(provider: str) -> tuple[str, ...] | None:
    try:
        with SessionLocal() as db:
            names = tuple(
                db.scalars(
                    select(ModelConfigurationRecord.model_id)
                    .where(ModelConfigurationRecord.provider == provider)
                    .order_by(ModelConfigurationRecord.model_id)
                )
            )
    except SQLAlchemyError:
        return None
    return names or None


def runtime_default_model() -> tuple[str, str] | None:
    try:
        with SessionLocal() as db:
            row = db.execute(
                select(
                    ModelConfigurationRecord.provider,
                    ModelConfigurationRecord.model_id,
                ).where(
                    ModelConfigurationRecord.is_default.is_(True),
                    ModelConfigurationRecord.available.is_(True),
                    ModelConfigurationRecord.enabled.is_(True),
                )
            ).one_or_none()
            return (row.provider, row.model_id) if row is not None else None
    except SQLAlchemyError:
        return None


def runtime_configuration_for_model(
    provider: str,
    model_id: str,
) -> RuntimeModelConfiguration | None:
    try:
        with SessionLocal() as db:
            record = db.get(ModelConfigurationRecord, (provider, model_id))
    except SQLAlchemyError:
        return None
    if record is None or not record.available or not record.enabled:
        return None
    return RuntimeModelConfiguration(
        provider=record.provider,
        model_id=record.model_id,
        parameters=dict(record.parameter_values or {}),
    )
