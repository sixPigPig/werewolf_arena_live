from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.live import LiveEventRecord, VoiceAudioChunkRecord, VoiceUtteranceRecord


PRIVATE_ROUND_MEMORY_ACTION = "summarize"
PRIVATE_PAYLOAD_KEYS = frozenset(
    {
        "visible_text",
        "delta",
        "result",
        "visible_result",
        "choice",
    }
)
REDACTED_PRIVATE_MEMORY_PAYLOAD = {
    "redacted": True,
    "reason": "private_round_memory",
}


@dataclass(frozen=True)
class PrivateMemoryCleanupResult:
    applied: bool
    run_count: int
    event_count: int
    voice_count: int
    audio_chunk_count: int
    failure_count: int = 0


def cleanup_private_round_memory(
    db: Session,
    *,
    apply: bool = False,
) -> PrivateMemoryCleanupResult:
    """Find and optionally redact leaked private round-memory events and voices.

    The caller owns the transaction. This function only flushes mutations when
    ``apply`` is true, which keeps dry-run behavior side-effect free and makes
    repeated applied runs converge to zero matches.
    """
    summary_events = list(
        db.scalars(
            select(LiveEventRecord).where(
                LiveEventRecord.action == PRIVATE_ROUND_MEMORY_ACTION
            )
        )
    )
    events_to_redact = [
        event
        for event in summary_events
        if event.payload != REDACTED_PRIVATE_MEMORY_PAYLOAD
        and _contains_private_payload_key(event.payload)
    ]
    sensitive_event_ids_by_run: dict[str, set[int]] = {}
    for event in events_to_redact:
        sensitive_event_ids_by_run.setdefault(event.run_id, set()).add(event.event_id)

    voices = list(db.scalars(select(VoiceUtteranceRecord)))
    voices_to_delete = [
        voice
        for voice in voices
        if voice.action == PRIVATE_ROUND_MEMORY_ACTION
        or _voice_overlaps_event_ids(
            voice,
            sensitive_event_ids_by_run.get(voice.run_id, set()),
        )
    ]
    voice_ids = [voice.utterance_id for voice in voices_to_delete]
    audio_chunk_count = 0
    if voice_ids:
        audio_chunk_count = int(
            db.scalar(
                select(func.count()).select_from(VoiceAudioChunkRecord).where(
                    VoiceAudioChunkRecord.utterance_id.in_(voice_ids)
                )
            )
            or 0
        )

    affected_run_ids = {event.run_id for event in events_to_redact}
    affected_run_ids.update(voice.run_id for voice in voices_to_delete)

    if apply:
        for event in events_to_redact:
            event.payload = REDACTED_PRIVATE_MEMORY_PAYLOAD.copy()
        if voice_ids:
            db.execute(
                delete(VoiceAudioChunkRecord).where(
                    VoiceAudioChunkRecord.utterance_id.in_(voice_ids)
                )
            )
            db.execute(
                delete(VoiceUtteranceRecord).where(
                    VoiceUtteranceRecord.utterance_id.in_(voice_ids)
                )
            )
        db.flush()

    return PrivateMemoryCleanupResult(
        applied=apply,
        run_count=len(affected_run_ids),
        event_count=len(events_to_redact),
        voice_count=len(voices_to_delete),
        audio_chunk_count=audio_chunk_count,
    )


def _contains_private_payload_key(value: Any) -> bool:
    if isinstance(value, dict):
        if PRIVATE_PAYLOAD_KEYS.intersection(value):
            return True
        return any(_contains_private_payload_key(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_private_payload_key(item) for item in value)
    return False


def _voice_overlaps_event_ids(
    voice: VoiceUtteranceRecord,
    event_ids: set[int],
) -> bool:
    return any(
        voice.source_event_id <= event_id <= voice.last_source_event_id
        for event_id in event_ids
    )
