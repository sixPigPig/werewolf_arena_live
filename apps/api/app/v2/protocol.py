from __future__ import annotations

from datetime import UTC, datetime
import json
import struct
from typing import Any

from app.v2.repository import V2PhaseTransition, V2PresentationIdentity


PROTOCOL_VERSION = 1
AUDIO_MAGIC = b"LV2A"


class V2LiveProtocolError(RuntimeError):
    pass


def control_message(
    *,
    message_type: str,
    game_id: str,
    run_id: str,
    fields: dict[str, Any],
) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "type": message_type,
        "game_id": game_id,
        "run_id": run_id,
        "server_time": datetime.now(tz=UTC).isoformat(),
        **fields,
    }


def presentation_opened(identity: V2PresentationIdentity) -> dict[str, Any]:
    return control_message(
        message_type="presentation.opened",
        game_id=identity.game_id,
        run_id=identity.run_id,
        fields={
            "action_id": identity.action_id,
            "presentation_seq": identity.presentation_seq,
            "presentation_id": identity.presentation_id,
            "phase_id": identity.phase_id,
            "actor": {"kind": identity.actor_kind, "id": identity.actor_id},
            "speech_id": identity.speech_id,
        },
    )


def segment_committed(identity: V2PresentationIdentity) -> dict[str, Any]:
    return control_message(
        message_type="speech.segment_committed",
        game_id=identity.game_id,
        run_id=identity.run_id,
        fields={
            "action_id": identity.action_id,
            "presentation_seq": identity.presentation_seq,
            "presentation_id": identity.presentation_id,
            "speech_id": identity.speech_id,
            "segment_index": identity.segment_index,
            "text": identity.subtitle_text,
        },
    )


def live_state(
    *,
    game_id: str,
    run_id: str,
    state: str,
    reason: str | None = None,
) -> dict[str, Any]:
    return control_message(
        message_type="live.state_changed",
        game_id=game_id,
        run_id=run_id,
        fields={"live_state": state, "reason": reason},
    )


def game_phase_changed(transition: V2PhaseTransition) -> dict[str, Any]:
    return control_message(
        message_type="game.phase_changed",
        game_id=transition.game_id,
        run_id=transition.run_id,
        fields={
            "phase_seq": transition.phase_seq,
            "previous_phase_id": transition.previous_phase_id,
            "phase_id": transition.phase_id,
            "phase_state": transition.phase_state,
        },
    )


def night_progress(
    *,
    game_id: str,
    run_id: str,
    stage: str,
    latest_presentation_seq: int,
) -> dict[str, Any]:
    if stage not in {
        "night_started",
        "actions_in_progress",
        "night_resolved",
        "dawn_announced",
    }:
        raise V2LiveProtocolError("invalid public night progress")
    return control_message(
        message_type="night.progress_changed",
        game_id=game_id,
        run_id=run_id,
        fields={
            "stage": stage,
            "latest_presentation_seq": latest_presentation_seq,
        },
    )


def ability_progress(
    *,
    game_id: str,
    run_id: str,
    ability_id: str,
    status: str,
    actor_player_id: str | None = None,
    target_player_id: str | None = None,
    round_no: int | None = None,
) -> dict[str, Any]:
    return control_message(
        message_type="ability.progress_changed",
        game_id=game_id,
        run_id=run_id,
        fields={
            "ability_id": ability_id,
            "status": status,
            "actor_player_id": actor_player_id,
            "target_player_id": target_player_id,
            "round_no": round_no,
        },
    )


def public_dawn_result(
    *,
    game_id: str,
    run_id: str,
    dead_player_ids: list[str],
) -> dict[str, Any]:
    return control_message(
        message_type="dawn.result_announced",
        game_id=game_id,
        run_id=run_id,
        fields={"dead_player_ids": dead_player_ids},
    )


def god_view_night_resolution(
    *,
    game_id: str,
    run_id: str,
    deaths: list[dict[str, str]],
    attack_prevented_by: str | None,
) -> dict[str, Any]:
    return control_message(
        message_type="god_view.night_resolved",
        game_id=game_id,
        run_id=run_id,
        fields={
            "deaths": deaths,
            "attack_prevented_by": attack_prevented_by,
        },
    )


def player_state_changed(
    *,
    game_id: str,
    run_id: str,
    player_id: str,
    alive: bool,
    cause: str | None = None,
) -> dict[str, Any]:
    return control_message(
        message_type="player.state_changed",
        game_id=game_id,
        run_id=run_id,
        fields={"player_id": player_id, "alive": alive, "cause": cause},
    )


def match_state_changed(
    *,
    game_id: str,
    run_id: str,
    round_no: int,
    sheriff_player_id: str | None,
    sheriff_badge_state: str,
    winner: str | None = None,
) -> dict[str, Any]:
    return control_message(
        message_type="match.state_changed",
        game_id=game_id,
        run_id=run_id,
        fields={
            "round_no": round_no,
            "sheriff_player_id": sheriff_player_id,
            "sheriff_badge_state": sheriff_badge_state,
            "winner": winner,
        },
    )


def day_progress(
    *,
    game_id: str,
    run_id: str,
    round_no: int,
    stage: str,
) -> dict[str, Any]:
    return control_message(
        message_type="day.progress_changed",
        game_id=game_id,
        run_id=run_id,
        fields={"round_no": round_no, "stage": stage},
    )


def presentation_closed(
    identity: V2PresentationIdentity,
    *,
    final_chunk_index: int,
    final_sample_cursor: int,
) -> dict[str, Any]:
    return control_message(
        message_type="presentation.closed",
        game_id=identity.game_id,
        run_id=identity.run_id,
        fields={
            "action_id": identity.action_id,
            "presentation_seq": identity.presentation_seq,
            "presentation_id": identity.presentation_id,
            "speech_id": identity.speech_id,
            "final_segment_index": identity.segment_index,
            "final_chunk_index": final_chunk_index,
            "final_sample_cursor": final_sample_cursor,
            "result": "audio_drained_and_voice_saved",
        },
    )


def presentation_failed(
    identity: V2PresentationIdentity,
    *,
    failure_kind: str,
    failure_code: str,
) -> dict[str, Any]:
    return control_message(
        message_type="presentation.failed",
        game_id=identity.game_id,
        run_id=identity.run_id,
        fields={
            "action_id": identity.action_id,
            "presentation_seq": identity.presentation_seq,
            "presentation_id": identity.presentation_id,
            "speech_id": identity.speech_id,
            "failure_kind": failure_kind,
            "failure_code": failure_code,
        },
    )


def audio_frame(
    identity: V2PresentationIdentity,
    *,
    chunk_index: int,
    start_sample: int,
    sample_count: int,
    sample_rate: int,
    pcm: bytes,
    is_final: bool = False,
) -> bytes:
    if sample_count <= 0 or len(pcm) != sample_count * 2:
        raise V2LiveProtocolError("PCM payload does not match sample_count")
    header = json.dumps(
        {
            "protocol_version": PROTOCOL_VERSION,
            "action_id": identity.action_id,
            "presentation_seq": identity.presentation_seq,
            "presentation_id": identity.presentation_id,
            "speech_id": identity.speech_id,
            "segment_index": identity.segment_index,
            "chunk_index": chunk_index,
            "start_sample": start_sample,
            "sample_count": sample_count,
            "sample_rate": sample_rate,
            "channels": 1,
            "encoding": "pcm_s16le",
            "is_final": is_final,
        },
        separators=(",", ":"),
    ).encode()
    if len(header) > 0xFFFF:
        raise V2LiveProtocolError("audio header is too large")
    return AUDIO_MAGIC + struct.pack(">H", len(header)) + header + pcm
