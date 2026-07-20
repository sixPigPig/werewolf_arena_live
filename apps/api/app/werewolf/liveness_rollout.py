from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re

from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.liveness_rollout import LivenessRolloutConfigRecord


LIVENESS_ROLLOUT_CONFIG_ID = "default"
_EXPERIMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")


@dataclass(frozen=True)
class LivenessExperienceOption:
    revision: str
    label: str
    description: str
    control_summary: str
    treatment_summary: str


AVAILABLE_LIVENESS_EXPERIENCES = (
    LivenessExperienceOption(
        revision="liveness-v1",
        label="活人感体验 V1",
        description="角色心智、分句流式语音、情绪表达和可打断播报的第一版组合。",
        control_summary="保留异步质量观察与影子心智，不启用分句语音、情绪投递和打断。",
        treatment_summary="启用角色心智读取、分句语音、情绪投递、预取和确定性打断。",
    ),
)
_AVAILABLE_REVISIONS = frozenset(item.revision for item in AVAILABLE_LIVENESS_EXPERIENCES)


class LivenessRolloutConflict(RuntimeError):
    def __init__(self, current_revision: int) -> None:
        super().__init__("liveness rollout configuration changed")
        self.current_revision = current_revision


@dataclass(frozen=True)
class LivenessRolloutConfig:
    revision: int
    experience_revision: str
    experiment_id: str
    treatment_percent: int
    source: str
    updated_at: datetime | None


def get_liveness_rollout_config(
    db: Session,
    *,
    fallback_experiment_id: str,
    fallback_treatment_percent: int,
) -> LivenessRolloutConfig:
    record = db.get(LivenessRolloutConfigRecord, LIVENESS_ROLLOUT_CONFIG_ID)
    if record is None:
        return LivenessRolloutConfig(
            revision=0,
            experience_revision="liveness-v1",
            experiment_id=_validated_experiment_id(fallback_experiment_id),
            treatment_percent=_validated_percent(fallback_treatment_percent),
            source="environment_fallback",
            updated_at=None,
        )
    _validate_experience_revision(record.experience_revision)
    return _config_from_record(record)


def update_liveness_rollout_config(
    db: Session,
    *,
    expected_revision: int,
    experience_revision: str,
    experiment_id: str,
    treatment_percent: int,
    updated_by_user_id: int,
) -> LivenessRolloutConfig:
    if expected_revision < 0:
        raise ValueError("expected revision must not be negative")
    experience_revision = _validate_experience_revision(experience_revision)
    experiment_id = _validated_experiment_id(experiment_id)
    treatment_percent = _validated_percent(treatment_percent)

    existing = db.get(LivenessRolloutConfigRecord, LIVENESS_ROLLOUT_CONFIG_ID)
    if existing is None:
        if expected_revision != 0:
            raise LivenessRolloutConflict(0)
        record = LivenessRolloutConfigRecord(
            id=LIVENESS_ROLLOUT_CONFIG_ID,
            revision=1,
            experience_revision=experience_revision,
            experiment_id=experiment_id,
            treatment_percent=treatment_percent,
            updated_by_user_id=updated_by_user_id,
        )
        db.add(record)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            current = db.get(LivenessRolloutConfigRecord, LIVENESS_ROLLOUT_CONFIG_ID)
            raise LivenessRolloutConflict(current.revision if current else 0) from exc
        db.refresh(record)
        return _config_from_record(record)

    result = db.execute(
        update(LivenessRolloutConfigRecord)
        .where(
            LivenessRolloutConfigRecord.id == LIVENESS_ROLLOUT_CONFIG_ID,
            LivenessRolloutConfigRecord.revision == expected_revision,
        )
        .values(
            revision=LivenessRolloutConfigRecord.revision + 1,
            experience_revision=experience_revision,
            experiment_id=experiment_id,
            treatment_percent=treatment_percent,
            updated_by_user_id=updated_by_user_id,
            updated_at=func.now(),
        )
    )
    if result.rowcount != 1:
        db.expire_all()
        current = db.get(LivenessRolloutConfigRecord, LIVENESS_ROLLOUT_CONFIG_ID)
        raise LivenessRolloutConflict(current.revision if current else 0)
    db.expire_all()
    record = db.get(LivenessRolloutConfigRecord, LIVENESS_ROLLOUT_CONFIG_ID)
    if record is None:
        raise LivenessRolloutConflict(0)
    return _config_from_record(record)


def _config_from_record(record: LivenessRolloutConfigRecord) -> LivenessRolloutConfig:
    return LivenessRolloutConfig(
        revision=record.revision,
        experience_revision=record.experience_revision,
        experiment_id=record.experiment_id,
        treatment_percent=record.treatment_percent,
        source="database",
        updated_at=record.updated_at,
    )


def _validate_experience_revision(value: str) -> str:
    if value not in _AVAILABLE_REVISIONS:
        raise ValueError("unsupported liveness experience revision")
    return value


def _validated_experiment_id(value: str) -> str:
    cleaned = value.strip() if isinstance(value, str) else ""
    if not _EXPERIMENT_ID_RE.fullmatch(cleaned):
        raise ValueError("experiment id must use 1-64 letters, numbers, '.', '_', ':' or '-'")
    return cleaned


def _validated_percent(value: int) -> int:
    if type(value) is not int or not 0 <= value <= 100:
        raise ValueError("liveness treatment percent must be between 0 and 100")
    return value
