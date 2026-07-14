from __future__ import annotations

import hashlib
from typing import Any

from app.werewolf.models import PublicOutcomeEventV1, PublicOutcomeKind, RoundState


def append_public_outcome(
    *,
    round_state: RoundState,
    session_id: str,
    kind: PublicOutcomeKind,
    actor_player_id: str | None,
    target_player_id: str | None,
    outcome: str,
    occurred_phase: str,
    caused_by_event_id: str | None = None,
) -> PublicOutcomeEventV1:
    sequence = max(1, round_state.public_outcome_next_sequence)
    event_id = _event_id(
        session_id=session_id,
        round_number=round_state.number,
        phase=occurred_phase,
        sequence=sequence,
    )
    if any(event.event_id == event_id for event in round_state.public_outcome_events):
        raise ValueError(f"duplicate public outcome event id: {event_id}")
    event = PublicOutcomeEventV1(
        schema_version=1,
        event_id=event_id,
        sequence=sequence,
        kind=kind,
        actor_player_id=actor_player_id,
        target_player_id=target_player_id,
        outcome=outcome,
        caused_by_event_id=caused_by_event_id,
        occurred_phase=occurred_phase,
    )
    round_state.public_outcome_events.append(event)
    round_state.public_outcome_next_sequence = sequence + 1
    return event


def latest_player_outcome_event(
    events: list[PublicOutcomeEventV1],
    player_id: str,
) -> PublicOutcomeEventV1 | None:
    ordered = sorted(events, key=lambda item: item.sequence, reverse=True)
    for event in ordered:
        if event.target_player_id == player_id:
            return event
    for event in ordered:
        if event.actor_player_id == player_id:
            return event
    return None


def render_public_round_summary(events: list[PublicOutcomeEventV1]) -> str:
    ordered = sorted(events, key=lambda event: event.sequence)
    event_ids = [event.event_id for event in ordered]
    if len(event_ids) != len(set(event_ids)):
        raise ValueError("duplicate public outcome event id")
    if not ordered:
        return "没有公开出局。"

    clauses: list[str] = []
    clause_index_by_event_id: dict[str, int] = {}
    for event in ordered:
        if event.kind == "night_death" and event.target_player_id:
            clause = f"{event.target_player_id}夜间出局"
        elif event.kind == "hunter_shot" and event.target_player_id:
            suffix = f"发动猎人技能，带走{event.target_player_id}"
            if _append_to_cause_clause(
                clauses,
                clause_index_by_event_id,
                event.caused_by_event_id,
                suffix,
            ):
                clause_index_by_event_id[event.event_id] = clause_index_by_event_id[
                    event.caused_by_event_id or ""
                ]
                continue
            actor = event.actor_player_id or "猎人"
            clause = f"{actor}{suffix}"
        elif event.kind == "self_explosion" and event.actor_player_id:
            clause = f"{event.actor_player_id}自爆，白天结束"
        elif event.kind == "exile" and event.target_player_id:
            clause = f"{event.target_player_id}被放逐"
        elif event.kind == "idiot_reveal" and event.actor_player_id:
            clause = f"{event.actor_player_id}翻牌为白痴，免于出局并失去投票权"
        elif event.kind == "badge_transferred" and event.target_player_id:
            if event.actor_player_id:
                suffix = f"将警徽移交给{event.target_player_id}"
                if _append_to_cause_clause(
                    clauses,
                    clause_index_by_event_id,
                    event.caused_by_event_id,
                    suffix,
                ):
                    clause_index_by_event_id[event.event_id] = clause_index_by_event_id[
                        event.caused_by_event_id or ""
                    ]
                    continue
                clause = f"{event.actor_player_id}{suffix}"
            else:
                clause = f"{event.target_player_id}当选警长"
        elif event.kind == "badge_lost":
            suffix = "撕毁警徽" if event.outcome == "destroyed" else "警徽流失"
            if _append_to_cause_clause(
                clauses,
                clause_index_by_event_id,
                event.caused_by_event_id,
                suffix,
            ):
                clause_index_by_event_id[event.event_id] = clause_index_by_event_id[
                    event.caused_by_event_id or ""
                ]
                continue
            clause = (
                f"{event.actor_player_id}{suffix}"
                if event.actor_player_id
                else suffix
            )
        else:
            continue
        clause_index_by_event_id[event.event_id] = len(clauses)
        clauses.append(clause)
    return ("；".join(clauses) if clauses else "没有公开出局") + "。"


def public_outcome_event_from_dict(data: dict[str, Any]) -> PublicOutcomeEventV1:
    kind = str(data.get("kind") or "night_death")
    if kind not in {
        "night_death",
        "hunter_shot",
        "self_explosion",
        "exile",
        "idiot_reveal",
        "badge_transferred",
        "badge_lost",
    }:
        kind = "night_death"
    return PublicOutcomeEventV1(
        schema_version=1,
        event_id=str(data.get("event_id") or ""),
        sequence=max(1, int(data.get("sequence") or 1)),
        kind=kind,  # type: ignore[arg-type]
        actor_player_id=_optional_string(data.get("actor_player_id")),
        target_player_id=_optional_string(data.get("target_player_id")),
        outcome=str(data.get("outcome") or "unknown"),
        caused_by_event_id=_optional_string(data.get("caused_by_event_id")),
        occurred_phase=str(data.get("occurred_phase") or "unknown"),
    )


def conservative_legacy_outcomes(data: dict[str, Any]) -> list[PublicOutcomeEventV1]:
    round_number = int(data.get("number") or 0)
    rows: list[tuple[PublicOutcomeKind, str | None, str | None, str, str]] = []
    for death in data.get("night_deaths", []):
        if not isinstance(death, dict) or death.get("cause") == "hunter_shot":
            continue
        player = _optional_string(death.get("player"))
        if player:
            rows.append(("night_death", None, player, "eliminated", "night"))
    self_exploded = _optional_string(data.get("werewolf_self_exploded"))
    if self_exploded:
        rows.append(("self_explosion", self_exploded, None, "self_exploded", "day"))
    idiot = _optional_string(data.get("idiot_revealed"))
    if idiot:
        rows.append(("idiot_reveal", idiot, None, "survived", "vote"))
    exiled = _optional_string(data.get("exiled"))
    if exiled and exiled != idiot:
        rows.append(("exile", None, exiled, "eliminated", "vote"))
    hunter_target = _optional_string(data.get("hunter_shot"))
    if hunter_target:
        rows.append(("hunter_shot", None, hunter_target, "eliminated", "unknown"))
    badge = data.get("sheriff_badge_resolution")
    if isinstance(badge, dict):
        outcome = str(badge.get("outcome") or "")
        rows.append(
            (
                "badge_transferred" if outcome == "transferred" else "badge_lost",
                _optional_string(badge.get("from_player")),
                _optional_string(badge.get("to_player")),
                outcome or "lost",
                "unknown",
            )
        )
    events: list[PublicOutcomeEventV1] = []
    for sequence, (kind, actor, target, outcome, phase) in enumerate(rows, start=1):
        events.append(
            PublicOutcomeEventV1(
                schema_version=1,
                event_id=f"legacy:r{round_number}:{sequence}",
                sequence=sequence,
                kind=kind,
                actor_player_id=actor,
                target_player_id=target,
                outcome=outcome,
                caused_by_event_id=None,
                occurred_phase=phase,
            )
        )
    return events


def _event_id(*, session_id: str, round_number: int, phase: str, sequence: int) -> str:
    digest = hashlib.sha256(
        f"{session_id}:{round_number}:{phase}:{sequence}".encode()
    ).hexdigest()[:16]
    return f"outcome_{digest}"


def _append_to_cause_clause(
    clauses: list[str],
    indexes: dict[str, int],
    caused_by_event_id: str | None,
    suffix: str,
) -> bool:
    if not caused_by_event_id or caused_by_event_id not in indexes:
        return False
    index = indexes[caused_by_event_id]
    clauses[index] = f"{clauses[index]}，随后{suffix}"
    return True


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None and str(value) else None
