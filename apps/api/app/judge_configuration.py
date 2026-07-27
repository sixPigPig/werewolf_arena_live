from __future__ import annotations

from dataclasses import dataclass
import secrets
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.judge_configuration import JudgeConfigurationRecord


JUDGE_CONFIGURATION_ID = "default"


@dataclass(frozen=True)
class RuntimeJudgeConfiguration:
    voice_mode: str
    tts_speaker: str
    random_tts_speakers: tuple[str, ...]
    version: int


def runtime_judge_configuration(
    db: Session,
    *,
    default_tts_speaker: str,
) -> RuntimeJudgeConfiguration:
    record = db.get(JudgeConfigurationRecord, JUDGE_CONFIGURATION_ID)
    if record is None:
        return RuntimeJudgeConfiguration(
            voice_mode="fixed",
            tts_speaker=default_tts_speaker,
            random_tts_speakers=(),
            version=0,
        )
    return RuntimeJudgeConfiguration(
        voice_mode=record.voice_mode,
        tts_speaker=record.tts_speaker,
        random_tts_speakers=_speaker_tuple(record.random_tts_speakers),
        version=record.version,
    )


def build_judge_voice_snapshot(
    configuration: RuntimeJudgeConfiguration,
    *,
    chooser: Callable[[tuple[str, ...]], str] = secrets.choice,
) -> dict[str, Any]:
    candidates = (
        configuration.random_tts_speakers
        if configuration.voice_mode == "random"
        else (configuration.tts_speaker,)
    )
    if not candidates:
        raise ValueError("judge voice configuration has no selectable speaker")
    selected = chooser(candidates)
    if selected not in candidates:
        raise ValueError("judge voice chooser returned a speaker outside the configured pool")
    return {
        "schema_version": 1,
        "voice_mode": configuration.voice_mode,
        "selected_tts_speaker": selected,
        "random_tts_speakers": list(configuration.random_tts_speakers),
        "configuration_version": configuration.version,
    }


def configuration_from_voice_snapshot(
    value: Any,
) -> RuntimeJudgeConfiguration | None:
    if not isinstance(value, dict):
        return None
    selected = value.get("selected_tts_speaker")
    mode = value.get("voice_mode")
    version = value.get("configuration_version")
    if (
        not isinstance(selected, str)
        or not selected.strip()
        or mode not in {"fixed", "random"}
        or not isinstance(version, int)
        or isinstance(version, bool)
        or version < 0
    ):
        return None
    return RuntimeJudgeConfiguration(
        voice_mode=mode,
        tts_speaker=selected.strip(),
        random_tts_speakers=_speaker_tuple(value.get("random_tts_speakers")),
        version=version,
    )


def _speaker_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    )
