from __future__ import annotations

from app.judge_configuration import (
    RuntimeJudgeConfiguration,
    build_judge_voice_snapshot,
    configuration_from_voice_snapshot,
)


def test_random_judge_voice_is_selected_once_and_rehydrated_from_snapshot() -> None:
    configuration = RuntimeJudgeConfiguration(
        voice_mode="random",
        tts_speaker="speaker-a",
        random_tts_speakers=("speaker-a", "speaker-b"),
        version=7,
    )

    snapshot = build_judge_voice_snapshot(
        configuration,
        chooser=lambda speakers: speakers[-1],
    )
    frozen = configuration_from_voice_snapshot(snapshot)

    assert snapshot == {
        "schema_version": 1,
        "voice_mode": "random",
        "selected_tts_speaker": "speaker-b",
        "random_tts_speakers": ["speaker-a", "speaker-b"],
        "configuration_version": 7,
    }
    assert frozen == RuntimeJudgeConfiguration(
        voice_mode="random",
        tts_speaker="speaker-b",
        random_tts_speakers=("speaker-a", "speaker-b"),
        version=7,
    )


def test_fixed_judge_voice_snapshot_uses_configured_speaker() -> None:
    snapshot = build_judge_voice_snapshot(
        RuntimeJudgeConfiguration(
            voice_mode="fixed",
            tts_speaker="speaker-fixed",
            random_tts_speakers=(),
            version=2,
        )
    )

    assert snapshot["selected_tts_speaker"] == "speaker-fixed"
    assert snapshot["voice_mode"] == "fixed"
