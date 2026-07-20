from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping

from app.werewolf.actor_mind import EventCoordinateV1


SPEECH_ACTS = frozenset(
    {
        "respond",
        "agree",
        "challenge",
        "ask",
        "defend",
        "hedge",
        "change_mind",
        "redirect",
        "defuse",
        "tease",
        "vote_only",
        "brief_pass",
        "summarize",
    }
)
SOCIAL_GOALS = frozenset(
    {
        "persuade",
        "probe",
        "defend_self",
        "protect_target",
        "shift_pressure",
        "build_alliance",
        "signal_uncertainty",
        "close_turn",
    }
)
PUBLIC_POINT_KINDS = frozenset(
    {"suspect", "trust", "defend", "challenge", "vote_intent", "change_mind", "ask"}
)
LENGTH_BANDS = frozenset({"brief", "normal", "extended"})
AFFECT_IMPULSES = frozenset({"restrained", "steady", "sharper", "softer"})


@dataclass(frozen=True)
class PublicTurnPointV1:
    kind: str
    target: str | None
    strength: Literal["low", "medium", "high"]
    basis_public_sources: tuple[EventCoordinateV1, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target": self.target,
            "strength": self.strength,
            "basis_public_sources": [source.to_dict() for source in self.basis_public_sources],
        }


@dataclass(frozen=True)
class PublicTurnPlanV1:
    schema_version: Literal[1]
    plan_id: str
    action_id: str
    fence: dict[str, Any]
    stimulus_sources: tuple[EventCoordinateV1, ...]
    response_targets: tuple[str, ...]
    primary_speech_act: str
    secondary_speech_act: str | None
    social_goal: str
    public_points: tuple[PublicTurnPointV1, ...]
    must_reference_public_fact_ids: tuple[str, ...]
    length_band: str
    affect_impulse: str

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["stimulus_sources"] = [source.to_dict() for source in self.stimulus_sources]
        value["public_points"] = [point.to_dict() for point in self.public_points]
        return value


def public_turn_plan_from_model(
    value: object,
    *,
    action_id: str,
    fence: Mapping[str, Any],
    allowed_targets: set[str],
    allowed_sources: set[tuple[str, int]],
    allowed_fact_ids: set[str],
) -> PublicTurnPlanV1:
    if not isinstance(value, Mapping):
        raise ValueError("turn plan must be an object")
    primary = _enum(value.get("primary_speech_act"), SPEECH_ACTS, "brief_pass")
    secondary_raw = value.get("secondary_speech_act")
    secondary = (
        secondary_raw
        if isinstance(secondary_raw, str) and secondary_raw in SPEECH_ACTS and secondary_raw != primary
        else None
    )
    social_goal = _enum(value.get("social_goal"), SOCIAL_GOALS, "close_turn")
    length_band = _enum(value.get("length_band"), LENGTH_BANDS, "brief")
    affect_impulse = _enum(value.get("affect_impulse"), AFFECT_IMPULSES, "steady")
    sources = _coordinates(value.get("stimulus_sources"), allowed_sources, limit=2)
    targets = _strings(value.get("response_targets"), allowed_targets, limit=2)
    fact_ids = _strings(
        value.get("must_reference_public_fact_ids"), allowed_fact_ids, limit=2
    )
    points: list[PublicTurnPointV1] = []
    raw_points = value.get("public_points")
    if isinstance(raw_points, list):
        for item in raw_points[:3]:
            if not isinstance(item, Mapping):
                continue
            kind = item.get("kind")
            if not isinstance(kind, str) or kind not in PUBLIC_POINT_KINDS:
                continue
            target = item.get("target")
            safe_target = target if isinstance(target, str) and target in allowed_targets else None
            strength = _enum(item.get("strength"), {"low", "medium", "high"}, "medium")
            points.append(
                PublicTurnPointV1(
                    kind=kind,
                    target=safe_target,
                    strength=strength,  # type: ignore[arg-type]
                    basis_public_sources=_coordinates(
                        item.get("basis_public_sources"), allowed_sources, limit=3
                    ),
                )
            )
    plan_id = stable_plan_id(action_id, value)
    return PublicTurnPlanV1(
        schema_version=1,
        plan_id=plan_id,
        action_id=action_id,
        fence=dict(fence),
        stimulus_sources=sources,
        response_targets=targets,
        primary_speech_act=primary,
        secondary_speech_act=secondary,
        social_goal=social_goal,
        public_points=tuple(points),
        must_reference_public_fact_ids=fact_ids,
        length_band=length_band,
        affect_impulse=affect_impulse,
    )


def fallback_public_turn_plan(
    *,
    action_id: str,
    fence: Mapping[str, Any],
    mission_kind: str | None,
    response_target: str | None,
) -> PublicTurnPlanV1:
    mission_mapping = {
        "contradiction_hunter": ("challenge", "probe"),
        "devil_advocate": ("challenge", "shift_pressure"),
        "vote_analyst": ("vote_only", "persuade"),
        "risk_controller": ("hedge", "signal_uncertainty"),
        "consolidator": ("summarize", "close_turn"),
        "fact_checker": ("respond", "persuade"),
    }
    speech_act, social_goal = mission_mapping.get(
        mission_kind or "", ("brief_pass", "close_turn")
    )
    value = {"primary_speech_act": speech_act, "social_goal": social_goal}
    return PublicTurnPlanV1(
        schema_version=1,
        plan_id=stable_plan_id(action_id, value),
        action_id=action_id,
        fence=dict(fence),
        stimulus_sources=(),
        response_targets=(response_target,) if response_target else (),
        primary_speech_act=speech_act,
        secondary_speech_act=None,
        social_goal=social_goal,
        public_points=(),
        must_reference_public_fact_ids=(),
        length_band="brief" if speech_act in {"brief_pass", "vote_only"} else "normal",
        affect_impulse="steady",
    )


def stable_plan_id(action_id: str, value: object) -> str:
    canonical_value = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    material = f"turn-plan-v1:{action_id}:{canonical_value}"
    return f"plan_{hashlib.sha256(material.encode()).hexdigest()[:20]}"


def _enum(value: object, allowed: set[str] | frozenset[str], fallback: str) -> str:
    return value if isinstance(value, str) and value in allowed else fallback


def _coordinates(
    value: object,
    allowed: set[tuple[str, int]],
    *,
    limit: int,
) -> tuple[EventCoordinateV1, ...]:
    if not isinstance(value, list):
        return ()
    result: list[EventCoordinateV1] = []
    for item in value:
        coordinate = EventCoordinateV1.from_dict(item)
        if coordinate is None:
            continue
        key = (coordinate.source_run_id, coordinate.source_event_id)
        if key in allowed and coordinate not in result:
            result.append(coordinate)
        if len(result) >= limit:
            break
    return tuple(result)


def _strings(value: object, allowed: set[str], *, limit: int) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item in allowed and item not in result:
            result.append(item)
        if len(result) >= limit:
            break
    return tuple(result)
