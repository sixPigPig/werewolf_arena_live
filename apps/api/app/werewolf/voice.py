from __future__ import annotations

import base64
import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from app.werewolf.live import LiveEvent

SpeakerKind = Literal["player", "judge"]
PUBLIC_SPEECH_ACTIONS = {"debate", "sheriff_speech", "sheriff_pk_speech"}
SENTENCE_PATTERN = re.compile(r"[^，。！？；,.!?;]+[，。！？；,.!?;]?")


@dataclass(frozen=True)
class VoiceSpeakerConfig:
    player_speaker: str
    judge_speaker: str


@dataclass(frozen=True)
class VoiceUtterance:
    utterance_id: str
    run_id: str
    source_event_id: int
    request_id: str | None
    speaker_kind: SpeakerKind
    speaker_name: str
    speaker: str
    text: str
    action: str | None


def is_public_speech_event(event: LiveEvent) -> bool:
    return event.type == "model_response_delta" and event.action in PUBLIC_SPEECH_ACTIONS


def chunk_text_for_tts(text: str, *, max_chars: int = 24) -> list[str]:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return []

    chunks: list[str] = []
    for phrase in SENTENCE_PATTERN.findall(normalized) or [normalized]:
        phrase = phrase.strip()
        if not phrase:
            continue
        if len(phrase) <= max_chars:
            chunks.append(phrase)
            continue
        for start in range(0, len(phrase), max_chars):
            chunks.append(phrase[start : start + max_chars])
    return chunks


def event_to_voice_utterance(
    event: LiveEvent,
    config: VoiceSpeakerConfig,
) -> VoiceUtterance | None:
    if is_public_speech_event(event):
        visible_text = _string_payload(event, "visible_text").strip()
        if not visible_text:
            return None
        speaker_name = event.actor or "当前玩家"
        return VoiceUtterance(
            utterance_id=f"voice_{uuid.uuid4().hex[:12]}",
            run_id=event.run_id,
            source_event_id=event.id,
            request_id=_string_payload(event, "request_id") or None,
            speaker_kind="player",
            speaker_name=speaker_name,
            speaker=config.player_speaker,
            text=visible_text,
            action=event.action,
        )

    judge_text = _judge_text_for_event(event)
    if judge_text is None:
        return None

    return VoiceUtterance(
        utterance_id=f"voice_{uuid.uuid4().hex[:12]}",
        run_id=event.run_id,
        source_event_id=event.id,
        request_id=None,
        speaker_kind="judge",
        speaker_name="法官",
        speaker=config.judge_speaker,
        text=judge_text,
        action=event.action,
    )


def build_voice_messages(
    *,
    utterance_id: str,
    source_event_id: int,
    speaker_kind: SpeakerKind,
    speaker_name: str,
    audio: bytes,
    mime_type: str,
    duration_ms: int,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return (
        {
            "type": "voice_start",
            "utterance_id": utterance_id,
            "source_event_id": source_event_id,
            "speaker_kind": speaker_kind,
            "speaker_name": speaker_name,
            "mime_type": mime_type,
        },
        {
            "type": "audio_chunk",
            "utterance_id": utterance_id,
            "mime_type": mime_type,
            "data": base64.b64encode(audio).decode("ascii"),
        },
        {
            "type": "voice_end",
            "utterance_id": utterance_id,
            "duration_ms": duration_ms,
        },
    )


def _judge_text_for_event(event: LiveEvent) -> str | None:
    if event.type == "phase_started" and event.phase == "night":
        return "天黑请闭眼。"
    if event.type == "phase_started" and event.phase == "day":
        return "天亮了，进入白天发言。"
    if event.type == "game_completed":
        winner = _string_payload(event, "winner") or "胜利阵营"
        return f"对局结束，{winner}获胜。"
    if event.type == "game_failed":
        return "对局异常中断。"
    return None


def _string_payload(event: LiveEvent, key: str) -> str:
    value = event.payload.get(key)
    return value if isinstance(value, str) else ""
