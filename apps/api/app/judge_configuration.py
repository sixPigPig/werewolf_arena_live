from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.judge_configuration import JudgeConfigurationRecord


JUDGE_CONFIGURATION_ID = "default"


@dataclass(frozen=True)
class RuntimeJudgeConfiguration:
    model_provider: str
    model_id: str
    tts_speaker: str
    version: int


def runtime_judge_configuration(
    db: Session,
    *,
    default_model_id: str,
    default_tts_speaker: str,
) -> RuntimeJudgeConfiguration:
    record = db.get(JudgeConfigurationRecord, JUDGE_CONFIGURATION_ID)
    if record is None:
        return RuntimeJudgeConfiguration(
            model_provider="agent_plan",
            model_id=default_model_id,
            tts_speaker=default_tts_speaker,
            version=0,
        )
    return RuntimeJudgeConfiguration(
        model_provider=record.model_provider,
        model_id=record.model_id,
        tts_speaker=record.tts_speaker,
        version=record.version,
    )
