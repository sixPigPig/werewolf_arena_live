from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from app.werewolf.actor_mind import ActorMindV1
from app.werewolf.turn_planning import PublicTurnPlanV1


@dataclass(frozen=True)
class ActorScenePacketV1:
    schema_version: int
    actor: str
    identity: dict[str, Any]
    private_facts: tuple[str, ...]
    relevant_public_facts: tuple[object, ...]
    actor_mind: dict[str, Any] | None
    legal_action_boundary: dict[str, Any]
    recent_committed_turns: tuple[str, ...]
    current_pressure: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(asdict(self))

    def content_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True)
class PublicSpeechSceneV1:
    schema_version: int
    public_actor_name: str
    persona_style: str
    public_state_boundary: dict[str, Any]
    recent_committed_turns: tuple[str, ...]
    relevant_public_facts: tuple[object, ...]
    public_stimulus: tuple[str, ...]
    turn_plan: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(asdict(self))


def build_actor_scene_packet(
    world_state: Mapping[str, object],
    *,
    actor_mind: ActorMindV1 | None,
) -> ActorScenePacketV1:
    observations = _strings(world_state.get("observations"), limit=6, max_chars=180)
    werewolf_context = _clean(world_state.get("werewolf_context"), max_chars=240)
    private_facts = tuple([*observations, *([werewolf_context] if werewolf_context else [])])
    public_facts = _public_items(world_state.get("public_facts"), limit=6, max_chars=180)
    recent_turns = _strings(world_state.get("debate"), limit=3, max_chars=220)
    hard_state = world_state.get("hard_state")
    eligibility = world_state.get("public_action_eligibility")
    return ActorScenePacketV1(
        schema_version=1,
        actor=_clean(world_state.get("name"), max_chars=120),
        identity={
            "role": _clean(world_state.get("role"), max_chars=40),
            "personality": _clean(world_state.get("personality"), max_chars=500),
        },
        private_facts=private_facts,
        relevant_public_facts=public_facts,
        actor_mind=actor_mind.to_dict() if actor_mind is not None else None,
        legal_action_boundary={
            "round": world_state.get("round"),
            "remaining_players": _clean(world_state.get("remaining_players"), max_chars=300),
            "options": _clean(world_state.get("options"), max_chars=300),
            "hard_state": copy.deepcopy(hard_state) if isinstance(hard_state, Mapping) else {},
            "eligibility": (
                copy.deepcopy(dict(eligibility)) if isinstance(eligibility, Mapping) else {}
            ),
        },
        recent_committed_turns=recent_turns,
        current_pressure={
            "endgame": bool(world_state.get("endgame_context")),
            "stage_interruptions": _strings(
                world_state.get("stage_interruptions"), limit=3, max_chars=160
            ),
        },
    )


def build_public_speech_scene(
    world_state: Mapping[str, object],
    *,
    turn_plan: PublicTurnPlanV1,
) -> PublicSpeechSceneV1:
    recent_turns = _strings(world_state.get("debate"), limit=3, max_chars=220)
    public_facts = _public_items(world_state.get("public_facts"), limit=6, max_chars=180)
    stimulus = tuple(
        [
            *_strings(world_state.get("stage_interruptions"), limit=1, max_chars=160),
            *_strings(world_state.get("endgame_context"), limit=1, max_chars=160),
        ][:2]
    )
    return PublicSpeechSceneV1(
        schema_version=1,
        public_actor_name=_clean(world_state.get("name"), max_chars=120),
        persona_style=_clean(world_state.get("personality"), max_chars=250),
        public_state_boundary={
            "round": world_state.get("round"),
            "remaining_players": _clean(world_state.get("remaining_players"), max_chars=300),
            "options": _clean(world_state.get("options"), max_chars=300),
            "eligibility": copy.deepcopy(world_state.get("public_action_eligibility") or {}),
        },
        recent_committed_turns=recent_turns,
        relevant_public_facts=public_facts,
        public_stimulus=stimulus,
        turn_plan=turn_plan.to_dict(),
    )


def scene_packet_prompt_chars(packet: ActorScenePacketV1 | PublicSpeechSceneV1) -> int:
    return len(json.dumps(packet.to_dict(), ensure_ascii=False, separators=(",", ":")))


def _strings(value: object, *, limit: int, max_chars: int) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[str] = []
    for item in list(value)[-limit:]:
        text = _clean(item, max_chars=max_chars)
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _public_items(value: object, *, limit: int, max_chars: int) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    result: list[object] = []
    seen: set[str] = set()
    for item in reversed(list(value)):
        if isinstance(item, str):
            normalized: object = _clean(item, max_chars=max_chars)
        elif isinstance(item, Mapping):
            normalized = {
                key: copy.deepcopy(item[key])
                for key in ("fact_id", "text", "trust_class", "source")
                if key in item
            }
            if isinstance(normalized.get("text"), str):
                normalized["text"] = _clean(normalized["text"], max_chars=max_chars)
        else:
            continue
        fingerprint = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        result.append(normalized)
        if len(result) >= limit:
            break
    result.reverse()
    return tuple(result)


def _clean(value: object, *, max_chars: int) -> str:
    text = " ".join(str(value or "").split())
    return text[:max_chars]
