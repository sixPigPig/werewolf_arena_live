from __future__ import annotations

import base64
import hashlib
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from app.werewolf.live import LiveEvent

SpeakerKind = Literal["player", "judge"]
VoiceAudience = Literal["player_public", "spectator_god_view"]
PUBLIC_SPEECH_ACTIONS = {
    "debate",
    "sheriff_speech",
    "sheriff_pk_speech",
    "exile_pk_speech",
    "exile_last_words",
}
GOD_VIEW_PRIVATE_SPEECH_ACTIONS = {"werewolf_discuss", "werewolf_kill_vote"}
PRIMARY_PRESENTATION_STATE_ACTIONS = {
    "exile_resolved",
    "night_resolved",
    "werewolf_self_explosion",
}
PUBLIC_WINNER_ASSETS = {
    "好人阵营": ("游戏结束，好人阵营获胜。", "game_over_villagers"),
    "狼人阵营": ("游戏结束，狼人阵营获胜。", "game_over_wolves"),
    "第三方阵营": ("游戏结束，第三方阵营获胜。", "game_over_third_party"),
}
USED_STATIC_JUDGE_VOICE_ASSET_IDS = frozenset(
    {
        "badge_destroyed",
        "badge_owner_out",
        "dawn_peaceful",
        "dawn_start",
        "exile_vote_start",
        "exile_tie",
        "exile_pk_start",
        "exile_runoff_vote",
        "exile_runoff_tied",
        "exile_no_votes",
        "exile_no_result",
        "exile_no_runoff_voters",
        "game_intro",
        "game_resume",
        "game_over_third_party",
        "game_over_villagers",
        "game_over_wolves",
        "guard_choose",
        "guard_sleep",
        "guard_wake",
        "night_start",
        "seer_choose",
        "seer_sleep",
        "seer_wake",
        "sheriff_choose_badge_side",
        "sheriff_no_badge",
        "sheriff_raise_hands",
        "sheriff_vote",
        "sheriff_tie",
        "self_explosion_skip",
        "hunter_shot_choose",
        "hunter_shot_skipped",
        "hunter_shot_start",
        "idiot_stays",
        "werewolves_choose",
        "werewolves_sleep",
        "werewolves_wake",
        "witch_poison",
        "witch_save",
        "witch_sleep",
        "witch_wake",
    }
)
USED_STATIC_JUDGE_VOICE_ASSET_TEMPLATE_IDS = frozenset(
    {
        "badge_transfer",
        "exile_last_words",
        "exile_result",
        "hunter_shot_result",
        "idiot_reveal",
        "sheriff_result",
        "speech_prompt",
        "werewolf_self_explosion",
        "witch_death",
    }
)
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
    action_id: str | None = None
    speech_id: str | None = None
    segment_id: str | None = None
    segment_index: int | None = None
    segment_final: bool | None = None
    presentation_id: str | None = None
    last_source_event_id: int | None = None
    static_asset_id: str | None = None
    audience: VoiceAudience = "player_public"
    effective_delivery: dict[str, Any] | None = None
    effective_context_texts: tuple[str, ...] = ()
    tts_dialect: str = ""
    voice_config_version: int | None = None
    delivery_mapping_version: str | None = None
    tts_request_source: str | None = None


@dataclass(frozen=True)
class JudgeVoiceCue:
    text: str
    static_asset_id: str | None = None


def is_static_judge_voice_asset_used(
    asset_id: str,
    *,
    template_id: str | None = None,
) -> bool:
    """Return whether live game narration can request this static asset."""
    return (
        asset_id in USED_STATIC_JUDGE_VOICE_ASSET_IDS
        or template_id in USED_STATIC_JUDGE_VOICE_ASSET_TEMPLATE_IDS
    )


NIGHT_ACTION_JUDGE_CUES = {
    "remove": JudgeVoiceCue("狼人请选择今晚袭击的目标。", "werewolves_choose"),
    "eliminate": JudgeVoiceCue("狼人请选择今晚袭击的目标。", "werewolves_choose"),
    "protect": JudgeVoiceCue("请选择今晚守护的玩家。", "guard_choose"),
    "guard": JudgeVoiceCue("请选择今晚守护的玩家。", "guard_choose"),
    "investigate": JudgeVoiceCue("请选择今晚查验的玩家。", "seer_choose"),
    "witch_save": JudgeVoiceCue("你是否使用解药？", "witch_save"),
    "witch_poison": JudgeVoiceCue(
        "你是否使用毒药？如果使用，请选择毒杀目标。",
        "witch_poison",
    ),
}
NIGHT_ROLE_JUDGE_CUES = {
    "werewolves_wake": JudgeVoiceCue(
        "狼人请睁眼，请互相确认队友。",
        "werewolves_wake",
    ),
    "werewolves_sleep": JudgeVoiceCue("狼人请闭眼。", "werewolves_sleep"),
    "guard_wake": JudgeVoiceCue("守卫请睁眼。", "guard_wake"),
    "guard_sleep": JudgeVoiceCue("守卫请闭眼。", "guard_sleep"),
    "seer_wake": JudgeVoiceCue("预言家请睁眼。", "seer_wake"),
    "seer_sleep": JudgeVoiceCue("预言家请闭眼。", "seer_sleep"),
    "witch_wake": JudgeVoiceCue("女巫请睁眼。", "witch_wake"),
    "witch_sleep": JudgeVoiceCue("女巫请闭眼。", "witch_sleep"),
}


def is_public_speech_event(event: LiveEvent) -> bool:
    return (
        event.type == "model_response_delta"
        and event.action in PUBLIC_SPEECH_ACTIONS
        and event.payload.get("is_public") is True
        and event.payload.get("schema_version") == 2
        and event.payload.get("commit_state") == "accepted_segment"
        and isinstance(event.payload.get("speech_id"), str)
        and isinstance(event.payload.get("segment_id"), str)
    )


def is_god_view_private_speech_event(event: LiveEvent) -> bool:
    if event.type != "action_parsed" or event.action not in GOD_VIEW_PRIVATE_SPEECH_ACTIONS:
        return False
    visible_result = event.payload.get("visible_result")
    return (
        isinstance(visible_result, dict)
        and isinstance(visible_result.get("message"), str)
        and bool(visible_result["message"].strip())
    )


def voice_job_candidate(
    event: LiveEvent,
    *,
    audience: VoiceAudience = "player_public",
) -> SpeakerKind | None:
    """Classify durable voice outbox candidates for one audience projection."""
    if event.type == "game_resumed" and event.payload.get("terminal_recovery") is True:
        return None
    if audience == "spectator_god_view" and is_god_view_private_speech_event(event):
        return "player"
    if is_public_speech_event(event):
        return "player"
    if event.type == "state_updated" and event.action == "hunter_shot_resolved":
        return "judge"
    if (
        event.type == "state_updated"
        and event.action in PRIMARY_PRESENTATION_STATE_ACTIONS
        and bool(_string_payload(event, "presentation_id"))
    ):
        return "judge"
    if event.type in {
        "game_started",
        "game_resumed",
        "judge_cue",
        "game_completed",
        "game_failed",
        "game_canceled",
        "player_did_not_speak",
    }:
        return "judge"
    if event.type == "phase_started" and event.phase in {"night", "day", "vote"}:
        if event.phase == "day" and event.payload.get("narration_mode") == "explicit_v1":
            return None
        return "judge"
    return None


def deterministic_voice_utterance_id(
    run_id: str,
    source_event_id: int,
    speaker_kind: SpeakerKind,
    *,
    audience: VoiceAudience = "player_public",
) -> str:
    audience_suffix = "" if audience == "player_public" else f":{audience}"
    digest = hashlib.sha256(
        f"{run_id}:{source_event_id}:{speaker_kind}{audience_suffix}".encode()
    ).hexdigest()[:24]
    return f"voice_{digest}"


def chunk_text_for_tts(text: str, *, max_chars: int = 24) -> list[str]:
    if max_chars < 1:
        raise ValueError("max_chars must be positive")

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
    *,
    player_seats: Mapping[str, int] | None = None,
    previous_night_deaths: Sequence[str] = (),
    peaceful_night: bool = False,
) -> VoiceUtterance | None:
    presentation_id = _string_payload(event, "presentation_id") or None
    if is_god_view_private_speech_event(event):
        visible_result = event.payload.get("visible_result")
        visible_text = (
            str(visible_result.get("message") or "")
            if isinstance(visible_result, dict)
            else ""
        ).strip()
        if not visible_text:
            return None
        return VoiceUtterance(
            utterance_id=f"voice_{uuid.uuid4().hex[:12]}",
            run_id=event.run_id,
            source_event_id=event.id,
            request_id=None,
            speaker_kind="player",
            speaker_name=_player_label(event.actor, player_seats, fallback="当前狼人"),
            speaker=config.player_speaker,
            text=visible_text,
            action=event.action,
            action_id=_string_payload(event, "action_id") or None,
            speech_id=_string_payload(event, "speech_id") or None,
            segment_id=_string_payload(event, "segment_id") or None,
            segment_index=(
                event.payload.get("segment_index")
                if type(event.payload.get("segment_index")) is int
                else None
            ),
            segment_final=(
                event.payload.get("segment_final")
                if type(event.payload.get("segment_final")) is bool
                else None
            ),
            presentation_id=presentation_id,
        )

    if is_public_speech_event(event):
        visible_text = _string_payload(event, "visible_text").strip()
        if not visible_text:
            return None
        speaker_name = _player_label(event.actor, player_seats, fallback="当前玩家")
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
            action_id=_string_payload(event, "action_id") or None,
            speech_id=_string_payload(event, "speech_id") or None,
            segment_id=_string_payload(event, "segment_id") or None,
            segment_index=(
                event.payload.get("segment_index")
                if type(event.payload.get("segment_index")) is int
                else None
            ),
            segment_final=(
                event.payload.get("segment_final")
                if type(event.payload.get("segment_final")) is bool
                else None
            ),
            presentation_id=presentation_id,
        )

    judge_cue = _judge_cue_for_event(
        event,
        player_seats=player_seats,
        previous_night_deaths=previous_night_deaths,
        peaceful_night=peaceful_night,
    )
    if judge_cue is None:
        return None

    return VoiceUtterance(
        utterance_id=f"voice_{uuid.uuid4().hex[:12]}",
        run_id=event.run_id,
        source_event_id=event.id,
        request_id=None,
        speaker_kind="judge",
        speaker_name="法官",
        speaker=config.judge_speaker,
        text=judge_cue.text,
        action=event.action,
        presentation_id=presentation_id,
        static_asset_id=judge_cue.static_asset_id,
    )


def event_to_voice_materialization(
    event: LiveEvent,
    config: VoiceSpeakerConfig,
    *,
    player_seats: Mapping[str, int] | None = None,
    previous_night_deaths: Sequence[str] = (),
    peaceful_night: bool = False,
    audience: VoiceAudience = "player_public",
) -> VoiceUtterance | None:
    candidate = voice_job_candidate(event, audience=audience)
    if candidate is None:
        return None
    utterance = event_to_voice_utterance(
        event,
        config,
        player_seats=player_seats,
        previous_night_deaths=previous_night_deaths,
        peaceful_night=peaceful_night,
    )
    if utterance is None or utterance.speaker_kind != candidate:
        return None
    return replace(
        utterance,
        utterance_id=deterministic_voice_utterance_id(
            event.run_id,
            event.id,
            candidate,
            audience=audience,
        ),
        audience=audience,
    )


def build_voice_messages(
    *,
    utterance_id: str,
    source_event_id: int,
    last_source_event_id: int | None = None,
    speaker_kind: SpeakerKind,
    speaker_name: str,
    audio: bytes,
    mime_type: str,
    duration_ms: int,
    audio_format: str,
    sample_rate: int,
    chunk_index: int,
    audience: VoiceAudience = "player_public",
    presentation_id: str | None = None,
    speech_id: str | None = None,
    segment_id: str | None = None,
    segment_index: int | None = None,
    segment_final: bool | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    start_message: dict[str, Any] = {
        "type": "voice_start",
        "utterance_id": utterance_id,
        "source_event_id": source_event_id,
        "speaker_kind": speaker_kind,
        "speaker_name": speaker_name,
        "audience": audience,
        "mime_type": mime_type,
        "audio_format": audio_format,
        "sample_rate": sample_rate,
    }
    if last_source_event_id is not None:
        start_message["last_source_event_id"] = last_source_event_id
    if presentation_id:
        start_message["presentation_id"] = presentation_id
    if speech_id:
        start_message["speech_id"] = speech_id
    if segment_id:
        start_message["segment_id"] = segment_id
    if segment_index is not None:
        start_message["segment_index"] = segment_index
    if segment_final is not None:
        start_message["segment_final"] = segment_final

    return (
        start_message,
        {
            "type": "audio_chunk",
            "utterance_id": utterance_id,
            "chunk_index": chunk_index,
            "mime_type": mime_type,
            "audio_format": audio_format,
            "sample_rate": sample_rate,
            "data": base64.b64encode(audio).decode("ascii"),
        },
        {
            "type": "voice_end",
            "utterance_id": utterance_id,
            "duration_ms": duration_ms,
        },
    )


def _judge_cue_for_event(
    event: LiveEvent,
    *,
    player_seats: Mapping[str, int] | None,
    previous_night_deaths: Sequence[str],
    peaceful_night: bool,
) -> JudgeVoiceCue | None:
    if event.type == "judge_cue":
        visible_text = _string_payload(event, "visible_text").strip()
        if visible_text:
            static_asset_id = _string_payload(event, "static_asset_id") or None
            return JudgeVoiceCue(visible_text, static_asset_id)
        role_cue = NIGHT_ROLE_JUDGE_CUES.get(event.action or "")
        if role_cue is not None:
            return role_cue
        if event.action == "witch_death":
            target = _string_payload(event, "target")
            if not target:
                return None
            target_label = _player_label(target, player_seats, fallback="该玩家")
            return JudgeVoiceCue(
                f"今晚被狼人袭击的玩家是{target_label}。",
                _seat_asset_id("witch_death", target, player_seats),
            )
        if event.action == "sheriff_raise_hands":
            return JudgeVoiceCue(
                "想要竞选警长的玩家请举手。",
                "sheriff_raise_hands",
            )
        return None
    if event.type == "game_started":
        return JudgeVoiceCue("本局游戏开始，请所有玩家确认自己的身份牌。", "game_intro")
    if event.type == "game_resumed":
        if event.payload.get("terminal_recovery") is True:
            return None
        return JudgeVoiceCue("本局游戏继续。", "game_resume")
    if event.type == "player_did_not_speak":
        actor_label = _player_label(event.actor, player_seats, fallback="该玩家")
        return JudgeVoiceCue(f"{actor_label}本轮未发言。")
    if event.type == "phase_started" and event.phase == "night":
        return JudgeVoiceCue("夜晚降临，所有玩家请闭眼。", "night_start")
    if event.type == "phase_started" and event.phase == "day":
        if event.payload.get("narration_mode") == "explicit_v1":
            return None
        if previous_night_deaths:
            return JudgeVoiceCue(
                f"昨夜死亡的玩家是 {_join_player_labels(previous_night_deaths, player_seats)}。"
            )
        if peaceful_night:
            return JudgeVoiceCue("昨夜平安夜。", "dawn_peaceful")
        return JudgeVoiceCue("天亮了，所有玩家请睁眼。", "dawn_start")
    if event.type == "phase_started" and event.phase == "vote":
        return JudgeVoiceCue("发言结束，进入放逐投票。", "exile_vote_start")
    if event.type == "action_requested" and event.phase == "night":
        night_action_cue = NIGHT_ACTION_JUDGE_CUES.get(event.action or "")
        if night_action_cue is not None:
            return night_action_cue
    if event.type == "action_requested" and event.action == "speech_order":
        return JudgeVoiceCue(
            "请警长选择从警左或警右开始发言。",
            "sheriff_choose_badge_side",
        )
    if event.type == "action_requested" and event.action == "exile_last_words":
        return None
    if event.type == "action_requested" and event.action in PUBLIC_SPEECH_ACTIONS:
        actor_label = _player_label(event.actor, player_seats, fallback="当前玩家")
        return JudgeVoiceCue(
            f"{actor_label}请发言。",
            _seat_asset_id("speech_prompt", event.actor, player_seats),
        )
    if event.type == "state_updated":
        if event.payload.get("narration_mode") == "explicit_v1":
            return None
        state_cue = _state_update_judge_cue(event, player_seats)
        if state_cue is not None:
            return state_cue
    if event.type == "game_completed":
        winner = _string_payload(event, "winner")
        if winner in PUBLIC_WINNER_ASSETS:
            text, static_asset_id = PUBLIC_WINNER_ASSETS[winner]
            return JudgeVoiceCue(text, static_asset_id)
        return JudgeVoiceCue("游戏结束，胜利阵营获胜。")
    if event.type == "game_failed":
        return JudgeVoiceCue("对局异常中断。")
    if event.type == "game_canceled":
        return JudgeVoiceCue("对局已终止。")
    return None


def _state_update_judge_cue(
    event: LiveEvent,
    player_seats: Mapping[str, int] | None,
) -> JudgeVoiceCue | None:
    if event.action == "hunter_shot_resolved":
        shot_status = _string_payload(event, "hunter_shot_status")
        hunter_shot = _string_payload(event, "hunter_shot")
        if shot_status == "shot" and hunter_shot:
            return JudgeVoiceCue(
                f"{_player_label(hunter_shot, player_seats, fallback='该玩家')} 被猎人带走，出局。",
                _seat_asset_id("hunter_shot_result", hunter_shot, player_seats),
            )
        if shot_status == "skipped" and not hunter_shot:
            return JudgeVoiceCue("猎人选择不发动技能。", "hunter_shot_skipped")
        return None

    if event.action == "night_resolved":
        night_deaths = event.payload.get("night_deaths")
        death_names = [
            player
            for item in night_deaths
            if isinstance(item, Mapping)
            and isinstance((player := item.get("player")), str)
            and player
        ] if isinstance(night_deaths, list) else []
        if death_names:
            return JudgeVoiceCue(
                f"昨夜死亡的玩家是 {_join_player_labels(death_names, player_seats)}。"
            )

    sheriff_speech_order = _string_list_payload(event, "sheriff_speech_order")
    sheriff_speech_direction = _string_payload(event, "sheriff_speech_direction")
    if sheriff_speech_order and sheriff_speech_direction:
        return JudgeVoiceCue(
            "从 "
            f"{_player_label(sheriff_speech_order[0], player_seats, fallback='当前玩家')}"
            f" 开始，按 {sheriff_speech_direction} 发表竞选发言。"
        )

    final_candidates = _string_list_payload(event, "sheriff_final_candidates")
    if final_candidates:
        return JudgeVoiceCue(
            f"仍在警上的玩家为 {_join_player_labels(final_candidates, player_seats)}。"
        )

    sheriff = _string_payload(event, "sheriff_elected") or _string_payload(event, "sheriff")
    if sheriff:
        return JudgeVoiceCue(
            f"{_player_label(sheriff, player_seats, fallback='该玩家')} 当选警长，获得警徽。",
            _seat_asset_id("sheriff_result", sheriff, player_seats),
        )

    exiled = _string_payload(event, "exiled")
    if exiled:
        return JudgeVoiceCue(
            f"{_player_label(exiled, player_seats, fallback='该玩家')} 得票最高，被放逐出局。",
            _seat_asset_id("exile_result", exiled, player_seats),
        )

    self_exploded = _string_payload(event, "werewolf_self_exploded")
    if self_exploded:
        return JudgeVoiceCue(
            f"{_player_label(self_exploded, player_seats, fallback='该玩家')} 发动狼人自爆。",
            _seat_asset_id("werewolf_self_explosion", self_exploded, player_seats),
        )

    hunter_shot = _string_payload(event, "hunter_shot")
    if hunter_shot:
        return JudgeVoiceCue(
            f"{_player_label(hunter_shot, player_seats, fallback='该玩家')} 被猎人带走，出局。",
            _seat_asset_id("hunter_shot_result", hunter_shot, player_seats),
        )

    idiot_revealed = _string_payload(event, "idiot_revealed")
    if idiot_revealed:
        return JudgeVoiceCue(
            f"{_player_label(idiot_revealed, player_seats, fallback='该玩家')} 翻牌为白痴。",
            _seat_asset_id("idiot_reveal", idiot_revealed, player_seats),
        )

    badge_target = _string_payload(event, "sheriff_badge_target")
    if badge_target:
        return JudgeVoiceCue(
            f"警徽移交给 {_player_label(badge_target, player_seats, fallback='该玩家')}。",
            _seat_asset_id("badge_transfer", badge_target, player_seats),
        )

    if event.payload.get("sheriff_badge_lost") is True:
        return JudgeVoiceCue("警徽被撕毁。", "badge_destroyed")

    return None


def _player_label(
    name: str | None,
    player_seats: Mapping[str, int] | None,
    *,
    fallback: str,
) -> str:
    if name and re.fullmatch(r"\d+号玩家", name.strip()):
        return name.strip()
    if name and player_seats:
        seat = player_seats.get(name)
        if isinstance(seat, int) and seat > 0:
            return f"{seat}号玩家"
    return fallback


def _join_player_labels(
    names: Sequence[str],
    player_seats: Mapping[str, int] | None,
) -> str:
    labels = [
        _player_label(name, player_seats, fallback="未知玩家")
        for name in names
        if name
    ]
    return "、".join(labels) if labels else "未知玩家"


def _seat_asset_id(
    template_id: str,
    name: str | None,
    player_seats: Mapping[str, int] | None,
) -> str | None:
    if not name:
        return None
    public_label = re.fullmatch(r"(\d+)号玩家", name.strip())
    if public_label is not None:
        seat = int(public_label.group(1))
    elif player_seats:
        seat = player_seats.get(name)
    else:
        return None
    if not isinstance(seat, int) or not 1 <= seat <= 12:
        return None
    return f"{template_id}_seat_{seat:02d}"


def _string_payload(event: LiveEvent, key: str) -> str:
    value = event.payload.get(key)
    return value if isinstance(value, str) else ""


def _string_list_payload(event: LiveEvent, key: str) -> list[str]:
    value = event.payload.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]
