from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from app.match.day_engine import DayEngine, speech_order_from_start
from app.match.model_context import (
    ModelContextProjectionInvariantError,
    ModelPlayerReference,
    build_actor_information,
    build_public_match_state,
    build_public_rule_contract,
    model_prompt_metadata,
    private_authoritative_facts,
    project_model_action_context as _project_model_action_context,
    project_model_action_context_with_metadata as _project_model_action_context_with_metadata,
    resolve_model_target,
    sanitize_model_speech,
)
from app.match.model_client import build_model_request_payload
from app.match.model_context_compaction import (
    encode_known_events_v7,
    expand_known_events_v7,
)
from app.match.model_context_contract import (
    KNOWN_EVENTS_SCHEMA_VERSION,
    MODEL_CONTEXT_SCHEMA_VERSION,
    PROMPT_TEMPLATE_VERSION,
    current_model_context_contract,
    is_historical_v11_model_context_contract,
    supports_model_context_contract,
)


PLAYERS = (
    ModelPlayerReference("system-player-07", 1, "乔宁"),
    ModelPlayerReference("system-player-01", 2, "沈砚"),
    ModelPlayerReference("system-player-09", 4, "唐梨"),
)


def _complete_v11_source(
    context: dict[str, object],
    *,
    players: tuple[ModelPlayerReference, ...],
) -> dict[str, object]:
    source = deepcopy(context)
    public_state = source.get("public_match_state")
    public_state = dict(public_state) if isinstance(public_state, dict) else {}
    round_no = source.get("round_no", public_state.get("round_no", 1))
    if not isinstance(round_no, int) or isinstance(round_no, bool) or round_no < 1:
        round_no = 1
    source["round_no"] = round_no
    public_state.setdefault("round_no", round_no)
    public_state.setdefault("alive_player_ids", [player.player_id for player in players])
    public_state.setdefault("eliminated_player_ids", [])
    public_state.setdefault("alive_player_count", len(public_state["alive_player_ids"]))
    public_state.setdefault("eliminated_player_count", len(public_state["eliminated_player_ids"]))
    sheriff_player_id = public_state.get("sheriff_player_id")
    public_state.setdefault(
        "sheriff_badge_state",
        "held" if isinstance(sheriff_player_id, str) else "unassigned",
    )
    source["public_match_state"] = public_state

    identity = source.get("self_identity")
    identity = identity if isinstance(identity, dict) else {}
    owner_id = identity.get("player_id")
    private_facts = source.get("private_authoritative_facts")
    if isinstance(owner_id, str) and isinstance(private_facts, list):
        for fact in private_facts:
            if isinstance(fact, dict):
                fact.setdefault("owner_scope", "player")
                fact.setdefault("owner_id", owner_id)
    office = source.get("public_office_capabilities")
    office = dict(office) if isinstance(office, dict) else {}
    office["is_current_sheriff"] = bool(
        isinstance(identity.get("player_id"), str)
        and identity.get("player_id") == sheriff_player_id
        and public_state.get("sheriff_badge_state") == "held"
    )
    source["public_office_capabilities"] = office

    source.setdefault("action_type", "day_debate_speech")
    output_contract = source.get("output_contract")
    output_contract = dict(output_contract) if isinstance(output_contract, dict) else {}
    target_policy = output_contract.get("target_policy")
    if "kind" not in output_contract:
        output_contract["kind"] = "target" if isinstance(target_policy, dict) else "speech"
    output_contract.setdefault(
        "speech",
        {"mode": "required" if output_contract["kind"] == "speech" else "forbidden"},
    )
    if output_contract["kind"] == "target":
        target_policy = dict(target_policy) if isinstance(target_policy, dict) else {}
        target_policy.setdefault("mode", "required")
        target_policy.setdefault(
            "allowed_target_ids",
            [
                item["player_id"]
                for item in source.get("candidates", [])
                if isinstance(item, dict) and isinstance(item.get("player_id"), str)
            ],
        )
        output_contract["target_policy"] = target_policy
    source["output_contract"] = output_contract
    return source


def _default_action_record_seq(context: dict[str, object]) -> int:
    sequences = [0]
    for key in ("public_history", "private_authoritative_facts"):
        items = context.get(key)
        if not isinstance(items, (list, tuple)):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for sequence_key in ("record_seq", "known_at_seq"):
                value = item.get(sequence_key)
                if isinstance(value, int) and not isinstance(value, bool):
                    sequences.append(value)
    return max(sequences) + 1


def project_model_action_context(
    context: dict[str, object],
    *,
    players: tuple[ModelPlayerReference, ...],
    model_context_contract: dict[str, object] | None = None,
    action_record_seq: int | None = None,
    projection_at_seq: int | None = None,
) -> dict[str, object]:
    prepared = _complete_v11_source(context, players=players)
    return _project_model_action_context(
        prepared,
        players=players,
        model_context_contract=(
            current_model_context_contract()
            if model_context_contract is None
            else model_context_contract
        ),
        action_record_seq=action_record_seq or _default_action_record_seq(prepared),
        projection_at_seq=projection_at_seq,
    )


def project_model_action_context_with_metadata(
    context: dict[str, object],
    *,
    players: tuple[ModelPlayerReference, ...],
    model_context_contract: dict[str, object] | None = None,
    action_record_seq: int | None = None,
    projection_at_seq: int | None = None,
):
    prepared = _complete_v11_source(context, players=players)
    return _project_model_action_context_with_metadata(
        prepared,
        players=players,
        model_context_contract=(
            current_model_context_contract()
            if model_context_contract is None
            else model_context_contract
        ),
        action_record_seq=action_record_seq or _default_action_record_seq(prepared),
        projection_at_seq=projection_at_seq,
    )


def _assert_contains(actual: dict[str, object], expected: dict[str, object]) -> None:
    assert {key: actual.get(key) for key in expected} == expected


def _canonical_known_events(context: dict[str, object]) -> dict[str, object]:
    compact = context.get("known_events")
    assert isinstance(compact, dict)
    return expand_known_events_v7(compact)


def _compact_known_events(
    events: list[dict[str, object]] | None = None,
    *,
    questions: list[dict[str, object]] | None = None,
    relations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return encode_known_events_v7(
        {
            "schema_version": 5,
            "events": events or [],
            "questions": questions or [],
            "relations": relations or [],
        }
    )


def test_model_context_uses_only_seat_references_and_unifies_public_events() -> None:
    projected = project_model_action_context(
        {
            "actor": {"kind": "player", "id": "system-player-01"},
            "objective": "沈砚需要判断唐梨是否可信",
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "seer",
                "team": "villagers",
            },
            "actor_profile": {
                "name": "沈砚",
                "personality": "沈砚习惯先梳理事实",
            },
            "output_contract": {
                "target_policy": {
                    "mode": "required",
                    "allowed_target_ids": ["system-player-09"],
                }
            },
            "private_authoritative_facts": [
                {
                    "fact_type": "investigation_alignment",
                    "record_seq": 1,
                    "known_at_seq": 1,
                    "payload": {
                        "target_player_id": "system-player-09",
                        "alignment": "werewolves",
                        "night_no": 1,
                    },
                }
            ],
            "public_match_state": {
                "round_no": 1,
                "alive_player_count": 2,
                "alive_player_ids": ["system-player-01", "system-player-09"],
                "eliminated_player_count": 1,
                "eliminated_player_ids": ["system-player-07"],
                "identity_information_included": False,
            },
            "candidates": [
                {
                    "player_id": "system-player-09",
                    "seat": 4,
                    "display_name": "唐梨",
                }
            ],
            "public_history": [
                {
                    "record_seq": 2,
                    "event_type": "dawn_public_result",
                    "payload": {
                        "round_no": 1,
                        "dead_player_ids": ["system-player-07"],
                    },
                },
                {
                    "record_seq": 3,
                    "event_type": "day_speech_committed",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate",
                        "player_id": "system-player-01",
                        "speech": "昨晚乔宁出局，我怀疑唐梨。",
                    },
                },
                {
                    "record_seq": 4,
                    "event_type": "player_exiled",
                    "payload": {
                        "round_no": 1,
                        "player_id": "system-player-09",
                    },
                },
            ],
        },
        players=PLAYERS,
    )

    serialized = json.dumps(projected, ensure_ascii=False)
    assert "乔宁" not in serialized
    assert "沈砚" not in serialized
    assert "唐梨" not in serialized
    assert "system-player-" not in serialized
    assert projected["model_context_schema_version"] == MODEL_CONTEXT_SCHEMA_VERSION
    assert projected["prompt_template_version"] == PROMPT_TEMPLATE_VERSION
    assert projected["task"]["goal"] == "2号需要判断4号是否可信"
    assert projected["self"]["identity"] == {
        "player_id": "seat_2",
        "seat": 2,
        "role_key": "seer",
        "team": "villagers",
    }
    assert projected["candidates"][0] == {
        "player_id": "seat_4",
        "seat": 4,
        "display_name": "4号",
    }
    private_fact = next(
        event
        for event in _canonical_known_events(projected)["events"]
        if event["visibility"] == "actor_private"
    )
    assert private_fact == {
        "event_ref": "current_private_fact_1",
        "kind": "investigation_alignment",
        "authority": "judge_fact",
        "visibility": "actor_private",
        "owner_scope": "player",
        "owner_ref": "seat_2",
        "record_seq": 1,
        "known_at_seq": 1,
        "occurred_in": {"period": "night", "round_no": 1},
        "data": {
            "target_player_id": "seat_4",
            "alignment": "werewolves",
            "night_no": 1,
        },
    }
    _assert_contains(
        projected["state"],
        {
            "round_no": 1,
            "alive_player_count": 2,
            "alive_player_ids": ["seat_2", "seat_4"],
            "eliminated_player_count": 1,
            "eliminated_player_ids": ["seat_1"],
            "identity_information_included": False,
            "current_period": "day",
            "current_round_no": 1,
            "latest_completed_night_no": 1,
            "next_night_no": 2,
            "as_of_seq": 5,
        },
    )
    public_events = [
        event
        for event in _canonical_known_events(projected)["events"]
        if event["visibility"] == "public"
    ]
    assert [item["kind"] for item in public_events] == [
        "night_result",
        "player_statement",
        "player_eliminated",
    ]
    assert all("source_event_id" not in item for item in public_events)
    assert all("timeline_index" not in item for item in public_events)
    assert public_events[0]["authority"] == "judge_fact"
    assert public_events[1]["authority"] == "player_claim_unverified"
    assert public_events[1]["speaker_ref"] == "seat_2"
    assert public_events[1]["speech"] == "昨晚1号出局，我怀疑4号。"
    assert public_events[1]["event_ref"] == "history_2"
    assert public_events[2]["public_reason"] == "exile"
    assert public_events[2]["role_revealed"] is False
    assert projected["known_events"]["schema_version"] == KNOWN_EVENTS_SCHEMA_VERSION
    assert _canonical_known_events(projected)["questions"] == []
    assert _canonical_known_events(projected)["relations"] == []
    assert "history" not in projected
    assert "public_timeline" not in projected
    assert "source_rules" not in serialized
    assert projected["known_events"]["annotations"] == []
    metadata = model_prompt_metadata(projected)
    assert metadata["prompt_schema_version"] == MODEL_CONTEXT_SCHEMA_VERSION
    assert metadata["model_context_schema_version"] == MODEL_CONTEXT_SCHEMA_VERSION
    assert metadata["prompt_template_version"] == PROMPT_TEMPLATE_VERSION
    assert metadata["serialized_char_count"] == len(
        json.dumps(projected, ensure_ascii=False, separators=(",", ":"))
    )


def test_v11_projects_public_technical_speech_skip() -> None:
    context = {
        "round_no": 3,
        "phase_id": "day_3",
        "action_type": "exile_vote",
        "self_identity": {
            "player_id": "system-player-01",
            "seat": 2,
            "role_key": "villager",
            "team": "villagers",
        },
        "public_history": [
            {
                "source_event_id": "skip-12",
                "record_seq": 1345,
                "event_type": "action_skipped_technical",
                "payload": {
                    "round_no": 3,
                    "phase_id": "day_3",
                    "actor_id": "system-player-09",
                    "action_type": "day_debate_speech",
                    "failure_code": "model_first_token_timeout",
                },
            }
        ],
    }

    projected = project_model_action_context(
        context,
        players=PLAYERS,
        action_record_seq=1400,
    )
    assert _canonical_known_events(projected)["events"] == [
        {
            "kind": "speech_turn_skipped_technical",
            "authority": "judge_fact",
            "record_seq": 1345,
            "occurred_in": {"period": "day", "round_no": 3},
            "speaker_ref": "seat_4",
            "action_type": "day_debate_speech",
            "stage": "day_debate_speech",
            "reason": "technical_failure",
            "event_ref": "skip-12",
            "visibility": "public",
            "known_at_seq": 1345,
        }
    ]


def test_v11_strips_failure_episode_audit_from_public_history() -> None:
    context = {
        "round_no": 3,
        "phase_id": "day_3",
        "action_type": "judge_game_completed",
        "self_identity": {
            "player_id": "system-player-01",
            "seat": 2,
            "role_key": "villager",
            "team": "villagers",
        },
        "public_history": [
            {
                "source_event_id": "cancel-1",
                "record_seq": 1401,
                "event_type": "game_canceled",
                "payload": {
                    "reason_code": "operator_interrupted",
                    "failure_episode_id": "v2_mfep_secret",
                    "source_failure_episode_ids": ["v2_mfep_source"],
                    "failed_failure_episode_ids": ["v2_mfep_failed"],
                    "canceled_failure_episode_ids": ["v2_mfep_canceled"],
                    "technical_outcome_record_seq": 1399,
                    "failure_episode_disposition": "run_canceled",
                    "model_generation_policy_profile": "recoverable_public_speech",
                    "model_generation_policy_enforcement": "observe_only",
                    "reasoning_only_timeout_ms": 180000,
                    "reasoning_only_elapsed_ms": 200000,
                    "shadow_would_timeout": True,
                    "nested": {"failure_episode_id": "v2_mfep_nested"},
                },
            }
        ],
    }

    projected = project_model_action_context(
        context,
        players=PLAYERS,
        action_record_seq=1402,
    )

    serialized = json.dumps(projected, ensure_ascii=False)
    assert "operator_interrupted" in serialized
    assert "failure_episode" not in serialized
    assert "technical_outcome_record_seq" not in serialized
    assert "model_generation_policy" not in serialized
    assert "reasoning_only" not in serialized
    assert "shadow_would_timeout" not in serialized
    assert "v2_mfep_" not in serialized


def test_v11_projects_prior_public_investigation_report_without_rewriting_causality() -> None:
    players = tuple(
        ModelPlayerReference(f"player-{seat}", seat, f"玩家{seat}") for seat in (1, 5, 6, 8)
    )
    projected = project_model_action_context_with_metadata(
        {
            "round_no": 1,
            "phase_id": "day_1",
            "action_type": "day_debate_speech",
            "self_identity": {
                "player_id": "player-6",
                "seat": 6,
                "role_key": "villager",
                "team": "villagers",
            },
            "speech_order": ["player-8", "player-6", "player-5", "player-1"],
            "public_rule_contract": {
                "roles": [
                    {"role_key": "seer", "count": 1, "team": "villagers"},
                    {"role_key": "villager", "count": 3, "team": "villagers"},
                ]
            },
            "public_history": [
                {
                    "source_event_id": 460,
                    "record_seq": 460,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "sheriff_campaign_speech",
                        "player_id": "player-5",
                        "speech": (
                            "5号上警，我是预言家。首夜验了1号，是狼人查杀。警徽流暂时不想死留。"
                        ),
                    },
                },
                {
                    "source_event_id": 732,
                    "record_seq": 732,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate_speech",
                        "player_id": "player-8",
                        "speech": "现在天亮了，5号昨晚验了谁、什么结果，该报了吧？",
                    },
                },
            ],
            "output_contract": {"kind": "speech", "speech": {"mode": "required"}},
        },
        players=players,
        action_record_seq=764,
    )

    events = _canonical_known_events(projected.context)["events"]
    first_party_report = next(event for event in events if event["event_ref"] == "460")
    assert [item["claim_type"] for item in first_party_report["annotations"]] == [
        "role_claim",
        "investigation_claim",
    ]
    assert first_party_report["annotations"][0]["claimed_role"] == "seer"
    _assert_contains(
        first_party_report["annotations"][1],
        {
            "claimed_action_in": {"period": "night", "round_no": 1},
            "target_ref": "seat_1",
            "claimed_result": "werewolves",
        },
    )
    assert all(
        item["authority"] == "player_claim_unverified"
        and item["derivation"]["validation_status"] == "complete"
        for item in first_party_report["annotations"]
    )
    questions = _canonical_known_events(projected.context)["questions"]
    assert len(questions) == 1
    _assert_contains(
        questions[0],
        {
            "question_id": "question_732_1",
            "source_event_ref": "732",
            "source_authority": "player_claim_unverified",
            "asked_by": "seat_8",
            "addressed_to": "seat_5",
            "address_resolution": "resolved",
            "asked_at_seq": 732,
            "topic": "past_investigation_result",
            "response_status": "none_detected",
            "requested_fields": ["target_ref", "claimed_result"],
            "referenced_night_no": 1,
            "reply_opportunity": "awaiting_scheduled_turn",
            "prior_relevant_event_refs": ["460"],
            "prior_coverage": "already_publicly_reported",
        },
    )
    assert questions[0]["derivation"]["validation_status"] == "complete"
    assert _canonical_known_events(projected.context)["relations"] == []
    assert projected.projection_metadata["emitted_claim_count"] == 2
    assert projected.projection_metadata["emitted_question_count"] == 1


def test_v11_night_state_anchor_distinguishes_current_from_completed_night() -> None:
    projected = project_model_action_context(
        {
            "round_no": 2,
            "night_no": 2,
            "phase_id": "night_2",
            "action_type": "ability_seer.investigate_decision",
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "seer",
                "team": "villagers",
            },
            "public_history": [],
        },
        players=PLAYERS,
        action_record_seq=20,
    )

    _assert_contains(
        projected["state"],
        {
            "current_period": "night",
            "current_round_no": 2,
            "latest_completed_night_no": 1,
            "next_night_no": 2,
            "as_of_seq": 20,
        },
    )

    pre_dawn_sheriff = project_model_action_context(
        {
            "round_no": 1,
            "phase_id": "first_night",
            "action_type": "sheriff_campaign_speech",
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "seer",
                "team": "villagers",
            },
            "public_history": [],
        },
        players=PLAYERS,
        action_record_seq=30,
    )
    _assert_contains(
        pre_dawn_sheriff["state"],
        {
            "current_period": "day",
            "current_round_no": 1,
            "latest_completed_night_no": 1,
            "next_night_no": 2,
            "as_of_seq": 30,
        },
    )

    hunter_dawn_context = {
        "round_no": 1,
        "night_no": 1,
        "phase_id": "day_1",
        "action_type": "ability_hunter.death_shot_decision",
        "self_identity": {
            "player_id": "system-player-01",
            "seat": 2,
            "role_key": "hunter",
            "team": "villagers",
        },
        "public_history": [
            {
                "source_event_id": 35,
                "record_seq": 35,
                "event_type": "dawn_public_result",
                "payload": {
                    "round_no": 1,
                    "dead_player_ids": ["system-player-01"],
                },
            }
        ],
    }
    hunter_dawn = project_model_action_context(
        hunter_dawn_context,
        players=PLAYERS,
        action_record_seq=40,
    )
    _assert_contains(
        hunter_dawn["state"],
        {
            "current_period": "day",
            "current_round_no": 1,
            "latest_completed_night_no": 1,
            "next_night_no": 2,
            "as_of_seq": 40,
        },
    )
    hunter_dawn_events = _canonical_known_events(hunter_dawn)["events"]
    assert hunter_dawn_events[0]["occurred_in"] == {
        "period": "night",
        "round_no": 1,
    }
    assert hunter_dawn_events[0]["announced_in"] == {
        "period": "dawn",
        "round_no": 1,
    }


def test_private_round_memory_keeps_subjective_actor_authority() -> None:
    projected = project_model_action_context(
        {
            "action_type": "day_debate_speech",
            "objective": "发表下一轮白天发言。",
            "round_no": 2,
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "villager",
                "team": "villagers",
            },
            "private_authoritative_facts": [
                {
                    "knowledge_fact_id": "v2_fact_memory_1",
                    "fact_type": "private_round_memory",
                    "authority": "actor_memory",
                    "payload": {
                        "round_no": 1,
                        "memory": "我上一轮暂时怀疑4号，但这不是法官确认事实。",
                        "epistemic_status": "actor_subjective_memory",
                    },
                    "record_seq": 30,
                    "known_at_seq": 30,
                    "occurred_in": {"period": "day", "round_no": 1},
                }
            ],
            "public_history": [],
            "output_contract": {
                "kind": "speech",
                "speech": {"mode": "required"},
            },
        },
        players=PLAYERS,
        action_record_seq=31,
    )

    memory = _canonical_known_events(projected)["events"][0]
    assert memory == {
        "event_ref": "v2_fact_memory_1",
        "kind": "private_round_memory",
        "authority": "actor_memory",
        "visibility": "actor_private",
        "owner_scope": "player",
        "owner_ref": "seat_2",
        "record_seq": 30,
        "known_at_seq": 30,
        "occurred_in": {"period": "day", "round_no": 1},
        "data": {
            "round_no": 1,
            "memory": "我上一轮暂时怀疑4号，但这不是法官确认事实。",
            "epistemic_status": "actor_subjective_memory",
        },
    }


def test_v13_selector_keeps_only_latest_actor_memory_with_snapshot_audit() -> None:
    projection = project_model_action_context_with_metadata(
        {
            "round_no": 3,
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "villager",
                "team": "villagers",
            },
            "private_authoritative_facts": [
                {
                    "knowledge_fact_id": "memory_old",
                    "fact_type": "private_round_memory",
                    "authority": "actor_memory",
                    "payload": {
                        "round_no": 1,
                        "memory": "旧记忆",
                        "source_cutoff_record_seq": 20,
                        "memory_sha256": "1" * 64,
                    },
                    "record_seq": 21,
                    "known_at_seq": 21,
                },
                {
                    "knowledge_fact_id": "memory_latest",
                    "fact_type": "private_round_memory",
                    "authority": "actor_memory",
                    "payload": {
                        "round_no": 2,
                        "memory": "最新记忆",
                        "source_cutoff_record_seq": 40,
                        "memory_sha256": "2" * 64,
                    },
                    "record_seq": 41,
                    "known_at_seq": 41,
                },
                {
                    "knowledge_fact_id": "seer_fact",
                    "fact_type": "investigation_alignment",
                    "authority": "judge_fact",
                    "payload": {"night_no": 1, "alignment": "villagers"},
                    "record_seq": 10,
                    "known_at_seq": 10,
                },
            ],
            "public_history": [],
        },
        players=PLAYERS,
        action_record_seq=50,
    )

    events = _canonical_known_events(projection.context)["events"]
    assert [event["event_ref"] for event in events] == ["seer_fact", "memory_latest"]
    selector = projection.projection_metadata["selector"]
    assert selector["latest_actor_memory_ref"] == "memory_latest"
    assert selector["latest_actor_memory_cutoff_seq"] == 40
    assert selector["latest_actor_memory_hash"] == "2" * 64
    assert selector["source_count"] == 3
    assert selector["retained_count"] == 2
    assert selector["omitted_count"] == 1
    assert selector["future_filtered_count"] == 0
    assert selector["omitted"] == [
        {
            "event_ref": "memory_old",
            "category": "actor_memory",
            "reason": "superseded_actor_memory",
        }
    ]


@pytest.mark.parametrize(
    ("action_type", "memory_cutoff"),
    [
        ("ability_seer.investigate_decision", 10),
        ("day_debate_speech", 10),
        ("ability_seer.investigate_decision", None),
    ],
)
def test_v13_selector_keeps_every_event_not_archived_by_latest_actor_memory(
    action_type: str,
    memory_cutoff: int | None,
) -> None:
    projection = project_model_action_context_with_metadata(
        {
            "round_no": 3,
            "action_type": action_type,
            **(
                {"unarchived_memory_source_cutoff_record_seq": 0}
                if memory_cutoff is None
                else {}
            ),
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "villager",
                "team": "villagers",
            },
            "private_authoritative_facts": (
                [
                    {
                        "knowledge_fact_id": "memory_round_1",
                        "fact_type": "private_round_memory",
                        "authority": "actor_memory",
                        "payload": {
                            "round_no": 1,
                            "memory": "第一轮结束时形成的主观记忆。",
                            "source_cutoff_record_seq": memory_cutoff,
                            "memory_sha256": "3" * 64,
                        },
                        "record_seq": 11,
                        "known_at_seq": 11,
                    }
                ]
                if memory_cutoff is not None
                else []
            ),
            "public_history": [
                {
                    "source_event_id": 8,
                    "record_seq": 8,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate_speech",
                        "player_id": "system-player-07",
                        "speech": "已经被记忆归档的旧发言。",
                    },
                },
                {
                    "source_event_id": 20,
                    "record_seq": 20,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 2,
                        "stage": "day_debate_speech",
                        "player_id": "system-player-07",
                        "speech": "上一轮记忆失败后尚未归档的普通发言。",
                    },
                },
                {
                    "source_event_id": 30,
                    "record_seq": 30,
                    "event_type": "day_vote_committed",
                    "payload": {
                        "round_no": 2,
                        "action_type": "exile_vote",
                        "voter_player_id": "system-player-07",
                        "target_player_id": "system-player-09",
                        "weight": 1.0,
                    },
                },
            ],
        },
        players=PLAYERS,
        action_record_seq=40,
    )

    events = _canonical_known_events(projection.context)["events"]
    expected_refs = (
        ["memory_round_1", "20", "30"]
        if memory_cutoff is not None
        else ["8", "20", "30"]
    )
    assert [event["event_ref"] for event in events] == expected_refs
    retained_by_ref = {
        item["event_ref"]: item for item in projection.projection_metadata["selector"]["retained"]
    }
    assert retained_by_ref["20"] == {
        "event_ref": "20",
        "category": "rolling_memory_increment",
        "reason": "not_yet_archived_in_actor_memory",
    }
    assert retained_by_ref["30"]["category"] == "rolling_memory_increment"
    expected_omitted = (
        [
            {
                "event_ref": "8",
                "category": "ordinary_history",
                "reason": "old_non_salient_player_statement",
            }
        ]
        if memory_cutoff is not None
        else []
    )
    assert projection.projection_metadata["selector"]["omitted"] == expected_omitted


def test_v13_selector_audits_future_events_separately_from_omissions() -> None:
    projection = project_model_action_context_with_metadata(
        {
            "round_no": 2,
            "public_history": [
                {
                    "source_event_id": 10,
                    "record_seq": 10,
                    "event_type": "day_speech_committed",
                    "payload": {
                        "round_no": 1,
                        "player_id": "system-player-07",
                        "speech": "旧轮普通发言。",
                    },
                },
                {
                    "source_event_id": 30,
                    "record_seq": 30,
                    "event_type": "day_speech_committed",
                    "payload": {
                        "round_no": 2,
                        "player_id": "system-player-09",
                        "speech": "未来发言。",
                    },
                },
            ],
        },
        players=PLAYERS,
        action_record_seq=40,
        projection_at_seq=20,
    )

    selector = projection.projection_metadata["selector"]
    assert selector["source_count"] == 2
    assert selector["retained_count"] == 0
    assert selector["omitted_count"] == 1
    assert selector["future_filtered_count"] == 1
    assert selector["future_filtered"] == [
        {"event_ref": "30", "reason": "event_after_action_cutoff"}
    ]


def test_model_context_orders_sheriff_plan_before_later_votes_on_one_clock() -> None:
    players = tuple(
        ModelPlayerReference(
            player_id=f"system-player-{seat:02d}",
            seat=seat,
            display_name=f"{seat}号玩家",
        )
        for seat in (2, 5, 6, 7, 8)
    )
    projected = project_model_action_context(
        {
            "round_no": 1,
            "action_type": "day_debate_speech",
            "self_identity": {
                "player_id": "system-player-08",
                "seat": 8,
                "role_key": "werewolf",
                "team": "werewolves",
            },
            "public_history": [
                {
                    "source_event_id": 448,
                    "record_seq": 448,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "sheriff_campaign_speech",
                        "player_id": "system-player-06",
                        "speech": "警徽流：今晚验2号，明晚验5号。",
                    },
                },
                {
                    "source_event_id": 562,
                    "record_seq": 562,
                    "event_type": "day_vote_committed",
                    "payload": {
                        "round_no": 1,
                        "action_type": "sheriff_vote",
                        "voter_player_id": "system-player-02",
                        "target_player_id": "system-player-07",
                        "weight": 1.0,
                    },
                },
                {
                    "source_event_id": 564,
                    "record_seq": 564,
                    "event_type": "day_vote_committed",
                    "payload": {
                        "round_no": 1,
                        "action_type": "sheriff_vote",
                        "voter_player_id": "system-player-05",
                        "target_player_id": "system-player-07",
                        "weight": 1.0,
                    },
                },
            ],
        },
        players=players,
    )

    events = _canonical_known_events(projected)["events"]
    assert [(item["record_seq"], item["kind"]) for item in events] == [
        (448, "player_statement"),
        (562, "day_vote"),
        (564, "day_vote"),
    ]
    assert events[0]["event_ref"] == "448"
    assert events[0]["speech"] == "警徽流：今晚验2号，明晚验5号。"
    assert [
        (item["voter_ref"], item["target_ref"]) for item in events if item["kind"] == "day_vote"
    ] == [
        ("seat_2", "seat_7"),
        ("seat_5", "seat_7"),
    ]
    assert "judge_facts" not in projected["state"]
    assert projected["task"]["at_seq"] == 565
    projection = project_model_action_context_with_metadata(
        {
            "round_no": 1,
            "action_type": "day_debate_speech",
            "self_identity": {
                "player_id": "system-player-08",
                "seat": 8,
                "role_key": "werewolf",
                "team": "werewolves",
            },
            "public_history": [
                {
                    "source_event_id": event["event_ref"],
                    "record_seq": event["record_seq"],
                    "event_type": (
                        "public_player_speech_presented"
                        if event["kind"] == "player_statement"
                        else "day_vote_committed"
                    ),
                    "payload": (
                        {
                            "round_no": 1,
                            "stage": "sheriff_campaign_speech",
                            "player_id": "system-player-06",
                            "speech": "警徽流：今晚验2号，明晚验5号。",
                        }
                        if event["kind"] == "player_statement"
                        else {
                            "round_no": 1,
                            "action_type": "sheriff_vote",
                            "voter_player_id": (
                                "system-player-02"
                                if event["record_seq"] == 562
                                else "system-player-05"
                            ),
                            "target_player_id": "system-player-07",
                            "weight": 1.0,
                        }
                    ),
                }
                for event in events
            ],
        },
        players=players,
    )
    assert projection.projection_metadata["known_event_record_seq_min"] == 448
    assert projection.projection_metadata["known_event_record_seq_max"] == 564
    assert projection.projection_metadata["emitted_event_count"] == 3


def test_model_context_projects_current_speech_position_and_remaining_speakers() -> None:
    projected = project_model_action_context(
        {
            "round_no": 1,
            "action_type": "day_debate_speech",
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "villager",
                "team": "villagers",
            },
            "speech_order": [
                "system-player-09",
                "system-player-01",
                "system-player-07",
            ],
        },
        players=PLAYERS,
    )

    assert projected["task"]["speech_order"] == ["seat_4", "seat_2", "seat_1"]
    assert projected["task"]["speech_progress"] == {
        "current_speaker_ref": "seat_2",
        "current_position": 2,
        "total_speakers": 3,
        "scheduled_before_refs": ["seat_4"],
        "remaining_speaker_refs": ["seat_1"],
    }


def test_known_events_preserve_input_order_for_duplicate_sequence() -> None:
    projected = project_model_action_context(
        {
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "seer",
                "team": "villagers",
            },
            "public_history": [
                {
                    "source_event_id": 562,
                    "record_seq": 562,
                    "event_type": "day_vote_committed",
                    "payload": {
                        "voter_player_id": "system-player-01",
                        "target_player_id": "system-player-09",
                    },
                },
                {
                    "source_event_id": "legacy-duplicate",
                    "record_seq": 562,
                    "event_type": "day_vote_committed",
                    "payload": {
                        "voter_player_id": "system-player-09",
                        "target_player_id": "system-player-01",
                    },
                },
            ],
        },
        players=PLAYERS,
    )

    events = _canonical_known_events(projected)["events"]
    assert [event["event_ref"] for event in events] == ["562", "legacy-duplicate"]
    assert all("source_event_id" not in event for event in events)
    assert all("timeline_index" not in event for event in events)
    assert "source_rules" not in json.dumps(projected, ensure_ascii=False)


def test_v11_known_events_place_private_investigation_before_later_public_speech() -> None:
    players = tuple(
        ModelPlayerReference(
            player_id=f"system-player-{seat:02d}",
            seat=seat,
            display_name=f"{seat}号玩家",
        )
        for seat in (6, 8)
    )
    projected = project_model_action_context(
        {
            "round_no": 1,
            "action_type": "sheriff_campaign_speech",
            "objective": "发表警长竞选发言。",
            "self_identity": {
                "player_id": "system-player-08",
                "seat": 8,
                "role_key": "seer",
                "team": "villagers",
            },
            "private_authoritative_facts": [
                {
                    "knowledge_fact_id": "knowledge-seer-night-1",
                    "source_activation_id": "activation-seer-night-1",
                    "fact_type": "private_ability_action_committed",
                    "record_seq": 258,
                    "known_at_seq": 258,
                    "occurred_in": {"period": "night", "round_no": 1},
                    "payload": {
                        "ability_id": "seer.investigate",
                        "night_no": 1,
                        "decision": {
                            "target_player_id": "system-player-06",
                        },
                        "declared_reason": {
                            "text": "在任何警上发言前已决定查验6号。",
                            "epistemic_status": "actor_declared_reason",
                        },
                        "result": {
                            "target_player_id": "system-player-06",
                            "alignment": "werewolves",
                        },
                    },
                }
            ],
            "public_history": [
                {
                    "source_event_id": 472,
                    "record_seq": 472,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "sheriff_campaign_speech",
                        "player_id": "system-player-06",
                        "speech": "6号上警，我先听后置位怎么说。",
                    },
                }
            ],
        },
        players=players,
        action_record_seq=501,
    )

    events = _canonical_known_events(projected)["events"]
    assert [(event["event_ref"], event["known_at_seq"]) for event in events] == [
        ("knowledge-seer-night-1", 258),
        ("472", 472),
    ]
    assert events[0]["visibility"] == "actor_private"
    assert events[0]["data"]["decision"] == {"target_player_id": "seat_6"}
    assert events[0]["data"]["declared_reason"] == {
        "text": "在任何警上发言前已决定查验6号。",
        "epistemic_status": "actor_declared_reason",
    }
    assert events[1]["speaker_ref"] == "seat_6"
    assert projected["task"]["at_seq"] == 501
    assert projected["state"]["as_of_seq"] == 501
    assert events[0]["known_at_seq"] < events[1]["known_at_seq"] < projected["task"]["at_seq"]


def test_v11_prompt_separates_event_occurrence_from_delayed_announcement() -> None:
    action_context = {
        "round_no": 1,
        "action_type": "first_night_last_words",
        "objective": "发表首夜遗言；你不知道具体死亡原因。",
        "self_identity": {
            "player_id": "system-player-07",
            "seat": 1,
            "role_key": "seer",
            "team": "villagers",
        },
        "public_history": [
            {
                "source_event_id": 608,
                "record_seq": 608,
                "event_type": "sheriff_elected",
                "payload": {
                    "round_no": 1,
                    "player_id": "system-player-07",
                    "from_player_id": None,
                    "reason": "sheriff_vote_unique_leader",
                },
            },
            {
                "source_event_id": 624,
                "record_seq": 624,
                "event_type": "dawn_public_result",
                "payload": {
                    "round_no": 1,
                    "dead_player_ids": ["system-player-07"],
                },
            },
        ],
        "output_contract": {
            "kind": "speech",
            "speech": {"mode": "required", "max_chars": 200},
        },
    }
    projected = project_model_action_context(
        action_context,
        players=PLAYERS,
        model_context_contract=current_model_context_contract(),
        action_record_seq=639,
    )

    events = _canonical_known_events(projected)["events"]
    assert [(event["event_ref"], event["known_at_seq"]) for event in events] == [
        ("608", 608),
        ("624", 624),
    ]
    assert events[0]["kind"] == "sheriff_elected"
    assert events[0]["occurred_in"] == {"period": "day", "round_no": 1}
    assert events[1]["kind"] == "night_result"
    assert events[1]["occurred_in"] == {"period": "night", "round_no": 1}
    assert events[1]["announced_in"] == {"period": "dawn", "round_no": 1}

    request = build_model_request_payload(
        projected,
        decision=True,
        model_id="test-model",
        max_output_tokens=16_384,
    )
    system_text = request["input"][0]["content"][0]["text"]
    assert projected["prompt_template_version"] == PROMPT_TEMPLATE_VERSION
    assert "known_at_seq/record_seq 表示获知和记录顺序" in system_text
    assert "occurred_in 表示事件实际发生阶段" in system_text
    assert "announced_in 只表示公布阶段，公布更晚不代表发生更晚" in system_text
    assert "带 seq 的信息按 seq 判断先后" not in system_text
    assert len(system_text) < 1_400


def test_current_contract_projects_v12_compact_shape() -> None:
    projected = project_model_action_context(
        {
            "action_type": "day_debate_speech",
            "objective": "发表白天发言。",
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "villager",
                "team": "villagers",
            },
            "public_history": [],
            "output_contract": {
                "kind": "speech",
                "speech": {"mode": "required"},
            },
        },
        players=PLAYERS,
        model_context_contract=current_model_context_contract(),
    )

    assert projected["model_context_schema_version"] == MODEL_CONTEXT_SCHEMA_VERSION
    assert projected["prompt_template_version"] == PROMPT_TEMPLATE_VERSION
    assert projected["task"]["type"] == "day_debate_speech"
    assert projected["response"] == {"kind": "speech", "speech": {"mode": "required"}}
    assert projected["known_events"] == _compact_known_events()
    assert _canonical_known_events(projected) == {
        "schema_version": 5,
        "events": [],
        "questions": [],
        "relations": [],
    }
    assert "history" not in projected
    assert "public_timeline" not in projected
    assert "output_contract" not in projected


def test_v11_keeps_player_statement_unverified_authority() -> None:
    action_context = {
        "action_type": "day_debate_speech",
        "self_identity": {
            "player_id": "system-player-01",
            "seat": 2,
            "role_key": "villager",
            "team": "villagers",
        },
        "public_history": [
            {
                "source_event_id": 20,
                "record_seq": 20,
                "event_type": "public_player_speech_presented",
                "payload": {
                    "round_no": 1,
                    "stage": "day_debate_speech",
                    "player_id": "system-player-09",
                    "speech": "4号自称猎人。",
                },
            }
        ],
        "output_contract": {"kind": "speech", "speech": {"mode": "required"}},
    }

    projected = project_model_action_context(
        action_context,
        players=PLAYERS,
        model_context_contract=current_model_context_contract(),
        action_record_seq=21,
    )

    assert projected["prompt_template_version"] == PROMPT_TEMPLATE_VERSION
    assert projected["known_events"]["schema_version"] == KNOWN_EVENTS_SCHEMA_VERSION
    statement = _canonical_known_events(projected)["events"][0]
    assert statement["authority"] == "player_claim_unverified"
    assert statement["event_ref"] == "20"
    assert "source_event_id" not in statement
    assert "timeline_index" not in statement


def test_current_contract_is_supported_and_v11_is_history_only() -> None:
    assert supports_model_context_contract(
        {"model_context_contract": current_model_context_contract()}
    )
    for prompt_version in (3, 4):
        historical = {
            **current_model_context_contract(),
            "model_context_schema_version": 11,
            "prompt_template_version": prompt_version,
            "known_events_schema_version": 5,
            "model_view_selector_version": 2,
        }
        assert is_historical_v11_model_context_contract(historical)
        assert not supports_model_context_contract({"model_context_contract": historical})
        with pytest.raises(ValueError, match="unsupported_model_context_contract"):
            project_model_action_context(
                {},
                players=PLAYERS,
                model_context_contract=historical,
            )


def test_projector_rejects_missing_frozen_model_context_contract() -> None:
    with pytest.raises(ValueError, match="unsupported_model_context_contract"):
        _project_model_action_context(
            _complete_v11_source({}, players=PLAYERS),
            players=PLAYERS,
            model_context_contract=None,
            action_record_seq=1,
        )


@pytest.mark.parametrize(
    ("private_fact", "expected_invariant"),
    [
        (
            {
                "knowledge_fact_id": "fact-without-clock",
                "fact_type": "known_investigation",
                "owner_scope": "player",
                "owner_id": "system-player-01",
                "payload": {"target_player_id": "system-player-09", "result": "good"},
            },
            "event_sequence_missing",
        ),
        (
            {
                "knowledge_fact_id": "fact-wrong-owner",
                "fact_type": "known_investigation",
                "owner_scope": "player",
                "owner_id": "system-player-09",
                "record_seq": 8,
                "known_at_seq": 8,
                "payload": {"target_player_id": "system-player-07", "result": "good"},
            },
            "actor_private_owner",
        ),
    ],
)
def test_v11_private_history_fails_closed_on_clock_or_owner_violation(
    private_fact: dict[str, object],
    expected_invariant: str,
) -> None:
    source = _complete_v11_source(
        {
            "round_no": 1,
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "seer",
                "team": "villagers",
            },
            "private_authoritative_facts": [private_fact],
            "public_history": [],
            "output_contract": {"kind": "speech", "speech": {"mode": "required"}},
        },
        players=PLAYERS,
    )

    with pytest.raises(ModelContextProjectionInvariantError) as exc_info:
        _project_model_action_context(
            source,
            players=PLAYERS,
            model_context_contract=current_model_context_contract(),
            action_record_seq=10,
        )

    assert exc_info.value.invariant_code == expected_invariant


def test_v11_sheriff_speech_order_projects_complete_precomputed_options() -> None:
    alive = [
        SimpleNamespace(player_id="system-player-07", seat=1),
        SimpleNamespace(player_id="system-player-01", seat=2),
        SimpleNamespace(player_id="system-player-09", seat=4),
    ]
    options = [
        {
            "target_player_id": candidate_id,
            "resulting_speech_order": speech_order_from_start(
                alive,
                "system-player-01",
                candidate_id,
            ),
            "sheriff_position": len(alive),
        }
        for candidate_id in ("system-player-07", "system-player-09")
    ]
    projected = project_model_action_context(
        {
            "round_no": 1,
            "action_type": "sheriff_speech_order",
            "objective": "根据每个候选对应的完整发言顺序，选择本轮起始发言者。",
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "villager",
                "team": "villagers",
            },
            "v11_action_extension": {
                "mechanical_effect": {
                    "action_type": "sheriff_speech_order",
                    "target_mode": "required",
                    "selected_target_becomes_first_speaker": True,
                    "sheriff_speaks_last": True,
                    "options": options,
                    "speech_has_gameplay_effect": False,
                }
            },
            "candidates": [
                {"player_id": "system-player-07", "seat": 1, "display_name": "乔宁"},
                {"player_id": "system-player-09", "seat": 4, "display_name": "唐梨"},
            ],
            "public_history": [],
            "output_contract": {
                "kind": "target",
                "target_policy": {"mode": "required"},
                "speech": {"mode": "forbidden"},
            },
        },
        players=PLAYERS,
        model_context_contract=current_model_context_contract(),
        action_record_seq=10,
    )

    effect = projected["task"]["mechanical_effect"]
    assert effect["options"] == [
        {
            "target_player_id": "seat_1",
            "resulting_speech_order": ["seat_1", "seat_4", "seat_2"],
            "sheriff_position": 3,
        },
        {
            "target_player_id": "seat_4",
            "resulting_speech_order": ["seat_4", "seat_1", "seat_2"],
            "sheriff_position": 3,
        },
    ]
    assert all(
        option["resulting_speech_order"][-1] == "seat_2"
        and option["sheriff_position"] == len(option["resulting_speech_order"])
        for option in effect["options"]
    )


def test_v11_sheriff_engine_reuses_selected_precomputed_order() -> None:
    class Actions:
        @staticmethod
        def check_cancellation(_game_id: str) -> None:
            return None

    class Repository:
        private_context: dict[str, object] | None = None
        event_payload: dict[str, object] | None = None

        def record_private_action_decision(self, **values: object) -> None:
            self.private_context = values["context"]  # type: ignore[assignment]

        def append_event(self, **values: object) -> None:
            self.event_payload = values["payload"]  # type: ignore[assignment]

    class Engine(DayEngine):
        call: dict[str, object] | None = None

        async def _player_action(self, **values: object) -> SimpleNamespace:
            self.call = values
            return SimpleNamespace(
                target_player_id="system-player-09",
                decision_note="从4号开始。",
            )

    repository = Repository()
    engine = Engine(repository=repository, action_engine=Actions())  # type: ignore[arg-type]
    state = SimpleNamespace(
        game_id="v2_game_sheriff_order",
        round_no=1,
        rule={"speech_policy": "sheriff_directed"},
        sheriff_player_id="system-player-01",
        model_context_contract=current_model_context_contract(),
        players=(
            SimpleNamespace(player_id="system-player-07", seat=1, alive=True),
            SimpleNamespace(player_id="system-player-01", seat=2, alive=True),
            SimpleNamespace(player_id="system-player-09", seat=4, alive=True),
        ),
    )

    result = asyncio.run(engine._speech_order(state=state, broadcaster=SimpleNamespace()))

    assert result == ["system-player-09", "system-player-07", "system-player-01"]
    assert engine.call is not None
    assert engine.call["objective"] == ("根据每个候选对应的完整发言顺序，选择本轮起始发言者。")
    extension = engine.call["extra_context"]
    assert isinstance(extension, dict)
    options = extension["v11_action_extension"]["mechanical_effect"]["options"]
    assert options == [
        {
            "target_player_id": "system-player-07",
            "resulting_speech_order": [
                "system-player-07",
                "system-player-09",
                "system-player-01",
            ],
            "sheriff_position": 3,
        },
        {
            "target_player_id": "system-player-09",
            "resulting_speech_order": [
                "system-player-09",
                "system-player-07",
                "system-player-01",
            ],
            "sheriff_position": 3,
        },
    ]
    assert repository.private_context is not None
    assert repository.event_payload is not None
    assert repository.private_context["speech_order"] is result
    assert repository.event_payload["order"] is result


def test_v11_projects_current_round_question_relations_with_reference_closure() -> None:
    action_context = {
        "round_no": 1,
        "action_type": "day_debate_speech",
        "self_identity": {
            "player_id": "system-player-07",
            "seat": 1,
            "role_key": "villager",
            "team": "villagers",
        },
        "speech_order": [
            "system-player-09",
            "system-player-07",
            "system-player-01",
        ],
        "public_history": [
            {
                "source_event_id": 10,
                "record_seq": 10,
                "event_type": "public_player_speech_presented",
                "payload": {
                    "round_no": 1,
                    "stage": "day_debate_speech",
                    "player_id": "system-player-01",
                    "speech": "第一晚我查验4号，因为想先看边角位。",
                },
            },
            {
                "source_event_id": 20,
                "record_seq": 20,
                "event_type": "public_player_speech_presented",
                "payload": {
                    "round_no": 1,
                    "stage": "day_debate_speech",
                    "player_id": "system-player-09",
                    "speech": "2号你首验为什么选4号？",
                },
            },
            {
                "source_event_id": 30,
                "record_seq": 30,
                "event_type": "public_player_speech_presented",
                "payload": {
                    "round_no": 1,
                    "stage": "day_debate_speech",
                    "player_id": "system-player-01",
                    "speech": "回应4号，查验理由就是先看边角位。",
                },
            },
        ],
        "output_contract": {"kind": "speech", "speech": {"mode": "required"}},
    }
    projected_before_answer = project_model_action_context_with_metadata(
        action_context,
        players=PLAYERS,
        model_context_contract=current_model_context_contract(),
        action_record_seq=25,
    )

    known_before = _canonical_known_events(projected_before_answer.context)
    assert [event["event_ref"] for event in known_before["events"]] == ["10", "20"]
    assert len(known_before["questions"]) == 1
    _assert_contains(
        known_before["questions"][0],
        {
            "question_id": "question_20_1",
            "source_event_ref": "20",
            "source_authority": "player_claim_unverified",
            "asked_by": "seat_4",
            "addressed_to": "seat_2",
            "address_resolution": "resolved",
            "asked_at_seq": 20,
            "topic": "investigation_reason",
            "response_status": "none_detected",
            "reply_opportunity": "awaiting_scheduled_turn",
            "prior_relevant_event_refs": ["10"],
        },
    )
    assert known_before["questions"][0]["derivation"]["validation_status"] == "complete"
    assert known_before["relations"] == []
    assert projected_before_answer.projection_metadata["emitted_question_count"] == 1
    assert projected_before_answer.projection_metadata["emitted_relation_count"] == 0
    assert projected_before_answer.projection_metadata["invalid_question_count"] == 0
    assert projected_before_answer.projection_metadata["invalid_relation_count"] == 0

    projected_after_answer = project_model_action_context_with_metadata(
        action_context,
        players=PLAYERS,
        model_context_contract=current_model_context_contract(),
        action_record_seq=35,
    )
    known_after = _canonical_known_events(projected_after_answer.context)
    assert known_after["questions"][0]["response_status"] == "response_detected"
    assert len(known_after["relations"]) == 1
    _assert_contains(
        known_after["relations"][0],
        {
            "relation_id": "relation_30_question_20_1",
            "type": "response_to_question",
            "from_event_ref": "30",
            "to_question_id": "question_20_1",
            "temporal_order_valid": True,
        },
    )
    assert known_after["relations"][0]["derivation"]["validation_status"] == "complete"
    event_refs = {event["event_ref"] for event in known_after["events"]}
    assert known_after["questions"][0]["source_event_ref"] in event_refs
    assert known_after["relations"][0]["from_event_ref"] in event_refs
    assert projected_after_answer.projection_metadata["emitted_question_count"] == len(
        known_after["questions"]
    )
    assert projected_after_answer.projection_metadata["emitted_relation_count"] == len(
        known_after["relations"]
    )
    prompt_metadata = model_prompt_metadata(projected_after_answer.context)
    assert prompt_metadata["question_count"] == len(known_after["questions"])
    assert prompt_metadata["relation_count"] == len(known_after["relations"])


def test_v11_reply_opportunity_covers_all_scheduled_turn_states() -> None:
    public_history = [
        {
            "source_event_id": 20,
            "record_seq": 20,
            "event_type": "public_player_speech_presented",
            "payload": {
                "round_no": 1,
                "stage": "day_debate_speech",
                "player_id": "system-player-09",
                "speech": "2号你首验为什么选4号？",
            },
        }
    ]
    cases = (
        (
            "system-player-07",
            ["system-player-09", "system-player-07", "system-player-01"],
            "awaiting_scheduled_turn",
        ),
        (
            "system-player-01",
            ["system-player-09", "system-player-07", "system-player-01"],
            "current_speaker_turn",
        ),
        (
            "system-player-07",
            ["system-player-01", "system-player-07", "system-player-09"],
            "scheduled_turn_passed",
        ),
        (
            "system-player-07",
            ["system-player-09", "system-player-07"],
            "not_in_current_speech_order",
        ),
    )
    player_by_id = {player.player_id: player for player in PLAYERS}
    for actor_id, speech_order, expected in cases:
        actor = player_by_id[actor_id]
        projected = project_model_action_context(
            {
                "round_no": 1,
                "action_type": "day_debate_speech",
                "self_identity": {
                    "player_id": actor.player_id,
                    "seat": actor.seat,
                    "role_key": "villager",
                    "team": "villagers",
                },
                "speech_order": speech_order,
                "public_history": public_history,
                "output_contract": {
                    "kind": "speech",
                    "speech": {"mode": "required"},
                },
            },
            players=PLAYERS,
            model_context_contract=current_model_context_contract(),
            action_record_seq=25,
        )
        assert _canonical_known_events(projected)["questions"][0]["reply_opportunity"] == expected


def test_v11_non_speech_action_omits_reply_opportunity_even_with_an_order() -> None:
    projected = project_model_action_context(
        {
            "round_no": 1,
            "action_type": "day_vote",
            "self_identity": {
                "player_id": "system-player-07",
                "seat": 1,
                "role_key": "villager",
                "team": "villagers",
            },
            "speech_order": [
                "system-player-09",
                "system-player-07",
                "system-player-01",
            ],
            "public_history": [
                {
                    "source_event_id": 20,
                    "record_seq": 20,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate_speech",
                        "player_id": "system-player-09",
                        "speech": "2号你首验为什么选4号？",
                    },
                }
            ],
            "output_contract": {
                "kind": "target",
                "target_policy": {"mode": "required"},
                "speech": {"mode": "forbidden"},
            },
        },
        players=PLAYERS,
        model_context_contract=current_model_context_contract(),
        action_record_seq=25,
    )

    assert "reply_opportunity" not in _canonical_known_events(projected)["questions"][0]


def test_v11_uses_one_canonical_current_living_werewolf_teammate_event() -> None:
    players = tuple(
        ModelPlayerReference(
            player_id=f"system-player-{seat:02d}",
            seat=seat,
            display_name=f"{seat}号玩家",
        )
        for seat in (1, 2, 3, 4, 5)
    )
    rule_contract = build_public_rule_contract(
        rule={
            "id": "v9-wolf-team",
            "version": "1",
            "player_count": 5,
            "roles": [
                {"role": "狼人", "count": 3, "team": "werewolves"},
                {"role": "村民", "count": 2, "team": "villagers"},
            ],
        },
        max_rounds=8,
    )
    projected = project_model_action_context(
        {
            "round_no": 2,
            "night_no": 2,
            "phase_id": "day_2",
            "action_type": "day_debate_speech",
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 1,
                "role_key": "werewolf",
                "team": "werewolves",
            },
            "private_authoritative_facts": [
                {
                    "knowledge_fact_id": "old-team-fact",
                    "fact_type": "werewolf_teammates",
                    "payload": ["system-player-02", "system-player-03"],
                    "known_at_seq": 5,
                },
                {
                    "fact_type": "living_werewolf_teammates",
                    "payload": ["system-player-03"],
                },
            ],
            "public_match_state": {
                "round_no": 2,
                "alive_player_ids": [
                    "system-player-01",
                    "system-player-03",
                    "system-player-04",
                    "system-player-05",
                ],
                "eliminated_player_ids": ["system-player-02"],
            },
            "public_rule_contract": rule_contract,
            "public_history": [],
            "output_contract": {"kind": "speech", "speech": {"mode": "required"}},
        },
        players=players,
        model_context_contract=current_model_context_contract(),
        action_record_seq=50,
    )

    assert projected["self"]["werewolf_coordination"] == {"mode": "team"}
    teammate_events = [
        event
        for event in _canonical_known_events(projected)["events"]
        if event["kind"] in {"werewolf_teammates", "living_werewolf_teammates"}
    ]
    assert teammate_events == [
        {
            "event_ref": "current_living_werewolf_teammates",
            "kind": "living_werewolf_teammates",
            "authority": "judge_fact",
            "visibility": "actor_private",
            "owner_scope": "player",
            "owner_ref": "seat_1",
            "known_at_seq": 50,
            "occurred_in": {"period": "day", "round_no": 2},
            "data": {"teammate_refs": ["seat_3"]},
        }
    ]
    assert "living_teammate_refs" not in projected["self"]["werewolf_coordination"]


def test_v11_single_wolf_and_non_wolf_do_not_receive_teammate_events() -> None:
    single_wolf_rule = build_public_rule_contract(
        rule={
            "id": "v9-single-wolf",
            "version": "1",
            "player_count": 3,
            "roles": [
                {"role": "狼人", "count": 1, "team": "werewolves"},
                {"role": "村民", "count": 2, "team": "villagers"},
            ],
        },
        max_rounds=8,
    )
    base = {
        "round_no": 1,
        "action_type": "day_debate_speech",
        "private_authoritative_facts": [
            {
                "fact_type": "living_werewolf_teammates",
                "payload": ["system-player-09"],
            }
        ],
        "public_match_state": {
            "round_no": 1,
            "alive_player_ids": ["system-player-07", "system-player-01", "system-player-09"],
        },
        "public_rule_contract": single_wolf_rule,
        "public_history": [],
        "output_contract": {"kind": "speech", "speech": {"mode": "required"}},
    }
    wolf = project_model_action_context(
        {
            **base,
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "werewolf",
                "team": "werewolves",
            },
        },
        players=PLAYERS,
        model_context_contract=current_model_context_contract(),
        action_record_seq=10,
    )
    villager = project_model_action_context(
        {
            **base,
            "self_identity": {
                "player_id": "system-player-07",
                "seat": 1,
                "role_key": "villager",
                "team": "villagers",
            },
        },
        players=PLAYERS,
        model_context_contract=current_model_context_contract(),
        action_record_seq=10,
    )

    assert wolf["self"]["werewolf_coordination"] == {"mode": "solo"}
    assert all(
        event["kind"] != "living_werewolf_teammates"
        for event in _canonical_known_events(wolf)["events"]
    )
    assert "werewolf_coordination" not in villager["self"]
    assert all(
        event["kind"] != "living_werewolf_teammates"
        for event in _canonical_known_events(villager)["events"]
    )


def test_model_context_keeps_current_round_exact_and_omits_old_ordinary_speech() -> None:
    quiet_detail = "这段只是当时的语气和铺垫。" * 10
    projected = project_model_action_context(
        {
            "round_no": 3,
            "actor": {"kind": "player", "id": "system-player-01"},
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "villager",
                "team": "villagers",
            },
            "candidates": [
                {
                    "player_id": "system-player-09",
                    "seat": 4,
                    "display_name": "唐梨",
                }
            ],
            "public_history": [
                {
                    "source_event_id": 101,
                    "record_seq": 101,
                    "event_type": "day_speech_committed",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate",
                        "player_id": "system-player-07",
                        "speech": f"我怀疑3号是狼。{quiet_detail}",
                    },
                },
                {
                    "source_event_id": 102,
                    "record_seq": 102,
                    "event_type": "day_speech_committed",
                    "payload": {
                        "round_no": 2,
                        "stage": "day_debate",
                        "player_id": "system-player-07",
                        "speech": f"我现在保3号是好人。{quiet_detail}",
                    },
                },
                {
                    "source_event_id": 103,
                    "record_seq": 103,
                    "event_type": "day_speech_committed",
                    "payload": {
                        "round_no": 3,
                        "stage": "day_debate",
                        "player_id": "system-player-09",
                        "speech": f"我今天要投2号。{quiet_detail}",
                    },
                },
                {
                    "source_event_id": 104,
                    "record_seq": 104,
                    "event_type": "day_speech_committed",
                    "payload": {
                        "round_no": 3,
                        "stage": "day_debate",
                        "player_id": "system-player-07",
                        "speech": f"我改投4号。{quiet_detail}",
                    },
                },
                {
                    "source_event_id": 105,
                    "record_seq": 105,
                    "event_type": "day_speech_committed",
                    "payload": {
                        "round_no": 3,
                        "stage": "day_debate",
                        "player_id": "system-player-09",
                        "speech": f"我认为1号可信。{quiet_detail}",
                    },
                },
            ],
        },
        players=PLAYERS,
    )

    events = _canonical_known_events(projected)["events"]
    assert {item["event_ref"] for item in events} == {"103", "104", "105"}
    assert all(item["speech"].endswith(quiet_detail) for item in events)
    assert all("source_event_id" not in item for item in events)
    assert all("timeline_index" not in item for item in events)
    assert projected["known_events"]["annotations"] == []


def test_model_context_projects_old_history_and_audits_omissions() -> None:
    public_history = [
        {
            "source_event_id": index,
            "record_seq": index,
            "event_type": "day_speech_committed",
            "payload": {
                "round_no": index // 6 + 1,
                "stage": "day_debate",
                "player_id": "system-player-07",
                "speech": f"我怀疑4号，记录{index}。" + "长发言" * 600,
            },
        }
        for index in range(1, 41)
    ]
    projection = project_model_action_context_with_metadata(
        {
            "action_type": "day_debate_speech",
            "round_no": 7,
            "public_history": public_history,
            "output_contract": {
                "kind": "speech",
                "speech": {"mode": "required"},
            },
        },
        players=PLAYERS,
    )

    projected = projection.context
    events = _canonical_known_events(projected)["events"]
    metadata = projection.projection_metadata
    assert metadata["ledger_statement_count"] == 40
    assert metadata["source_event_count"] == 40
    assert metadata["emitted_event_count"] < 40
    assert metadata["future_filtered_event_count"] == 0
    assert metadata["budget_dropped_event_count"] == 0
    assert "selection_budget_chars" not in metadata
    selector = metadata["selector"]
    assert selector["version"] == 3
    assert selector["source_count"] == 40
    assert selector["retained_count"] == metadata["emitted_event_count"]
    assert selector["retained_count"] + selector["omitted_count"] == 40
    assert selector["omitted_count"] > 0
    assert metadata["round_trip_verified"] is True
    assert metadata["canonical_serialized_char_count"] > metadata["compact_serialized_char_count"]
    assert metadata["compaction_saved_chars"] > 0
    assert len(metadata["canonical_sha256"]) == 64
    assert "retention_reasons" not in metadata
    assert all("speech_truncated" not in item for item in events)
    assert all(len(item["speech"]) > 1_800 for item in events)
    assert [item["event_ref"] for item in events] == ["36", "37", "38", "39", "40"]
    assert (
        model_prompt_metadata(
            projected,
            projection_metadata=metadata,
        )["serialized_char_count"]
        < 20_000
    )


def test_model_context_uses_current_presented_speech_without_duplicates() -> None:
    projected = project_model_action_context(
        {
            "round_no": 2,
            "actor": {"kind": "player", "id": "system-player-01"},
            "public_history": [
                {
                    "source_event_id": 10,
                    "record_seq": 10,
                    "event_type": "day_speech_committed",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate",
                        "player_id": "system-player-07",
                        "speech": "这条事件副本不应重复进入上下文。",
                    },
                },
                {
                    "source_event_id": 11,
                    "record_seq": 11,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate_speech",
                        "player_id": "system-player-07",
                        "speech": "第一天我怀疑4号。",
                    },
                },
                {
                    "source_event_id": 20,
                    "record_seq": 20,
                    "event_type": "sheriff_badge_transferred",
                    "payload": {
                        "round_no": 2,
                        "player_id": "system-player-01",
                        "from_player_id": "system-player-07",
                    },
                },
                {
                    "source_event_id": 21,
                    "record_seq": 21,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 2,
                        "stage": "sheriff_badge_resolution",
                        "player_id": "system-player-07",
                        "speech": "我昨夜验了2号，2号是金水。",
                    },
                },
            ],
        },
        players=PLAYERS,
    )

    events = _canonical_known_events(projected)["events"]
    assert [statement["event_ref"] for statement in events] == ["20", "21"]
    assert events[1]["speech"] == "我昨夜验了2号，2号是金水。"
    transfer = next(event for event in events if event["kind"] == "sheriff_badge_transferred")
    assert transfer["event_ref"] == "20"
    assert transfer["authority"] == "judge_fact"
    assert transfer["payload"] == {
        "round_no": 2,
        "player_id": "seat_2",
        "from_player_id": "seat_1",
    }
    assert "这条事件副本不应重复进入上下文" not in json.dumps(
        projected,
        ensure_ascii=False,
    )


def test_v13_selector_keeps_cross_round_first_party_claim_and_last_words() -> None:
    projected = project_model_action_context(
        {
            "round_no": 2,
            "public_rule_contract": build_public_rule_contract(
                rule={
                    "player_count": 3,
                    "roles": [
                        {"role": "预言家", "count": 1, "team": "villagers"},
                        {"role": "村民", "count": 2, "team": "villagers"},
                    ],
                },
                max_rounds=4,
            ),
            "public_history": [
                {
                    "source_event_id": 10,
                    "record_seq": 10,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "sheriff_campaign_speech",
                        "player_id": "system-player-07",
                        "speech": "1号是预言家，昨晚验4号是好人。",
                    },
                },
                {
                    "source_event_id": 20,
                    "record_seq": 20,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "exile_last_words",
                        "player_id": "system-player-09",
                        "speech": "这是我的遗言，请记住。",
                    },
                },
                {
                    "source_event_id": 30,
                    "record_seq": 30,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate_speech",
                        "player_id": "system-player-07",
                        "speech": "旧轮普通重复发言。",
                    },
                },
            ],
        },
        players=PLAYERS,
    )

    events = _canonical_known_events(projected)["events"]
    assert [event["event_ref"] for event in events] == ["10", "20"]
    assert events[0]["authority"] == "player_claim_unverified"
    assert events[1]["stage"] == "exile_last_words"


def test_v13_selector_keeps_old_speech_that_names_actor_or_candidate() -> None:
    projected = project_model_action_context(
        {
            "round_no": 3,
            "actor": {"kind": "player", "id": "system-player-01"},
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "villager",
                "team": "villagers",
            },
            "candidates": [
                {
                    "player_id": "system-player-09",
                    "seat": 4,
                    "display_name": "唐梨",
                }
            ],
            "public_history": [
                {
                    "source_event_id": 10,
                    "record_seq": 10,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate_speech",
                        "player_id": "system-player-07",
                        "speech": "我点名2号回答这个矛盾。",
                    },
                },
                {
                    "source_event_id": 20,
                    "record_seq": 20,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate_speech",
                        "player_id": "system-player-07",
                        "speech": "我认为4号今天应当进入候选。",
                    },
                },
                {
                    "source_event_id": 30,
                    "record_seq": 30,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate_speech",
                        "player_id": "system-player-07",
                        "speech": "这句没有涉及当前玩家或候选。",
                    },
                },
            ],
        },
        players=PLAYERS,
    )

    events = _canonical_known_events(projected)["events"]
    assert [event["event_ref"] for event in events] == ["10", "20"]


def test_model_context_preserves_first_party_claim_time_before_later_paraphrases() -> None:
    players = tuple(
        ModelPlayerReference(
            f"system-player-{seat:02d}",
            seat,
            f"{seat}号玩家",
        )
        for seat in (6, 8, 9, 10, 11, 12)
    )
    action_context = {
        "round_no": 1,
        "actor": {"kind": "player", "id": "system-player-12"},
        "public_rule_contract": build_public_rule_contract(
            rule={
                "id": "claim-order",
                "version": "1",
                "player_count": 6,
                "roles": [
                    {"role": "预言家", "count": 1, "team": "villagers"},
                    {"role": "村民", "count": 5, "team": "villagers"},
                ],
            },
            max_rounds=8,
        ),
        "public_history": [
            {
                "source_event_id": 400,
                "record_seq": 400,
                "event_type": "public_player_speech_presented",
                "payload": {
                    "round_no": 1,
                    "stage": "sheriff_campaign_speech",
                    "player_id": "system-player-06",
                    "speech": "6号上警，我先听后置位怎么说。",
                },
            },
            {
                "source_event_id": 417,
                "record_seq": 417,
                "event_type": "public_player_speech_presented",
                "payload": {
                    "round_no": 1,
                    "stage": "sheriff_campaign_speech",
                    "player_id": "system-player-08",
                    "speech": (
                        "8号上警竞选，底牌预言家，昨晚验6号，查杀。"
                        "现在回头看6号刚才的发言，我认为他在带节奏。"
                        "今晚我会验9号。"
                    ),
                },
            },
            {
                "source_event_id": 597,
                "record_seq": 597,
                "event_type": "public_player_speech_presented",
                "payload": {
                    "round_no": 1,
                    "stage": "day_debate_speech",
                    "player_id": "system-player-09",
                    "speech": "8号因为6号发言带节奏，所以昨晚验了6号。",
                },
            },
            {
                "source_event_id": 620,
                "record_seq": 620,
                "event_type": "public_player_speech_presented",
                "payload": {
                    "round_no": 1,
                    "stage": "day_debate_speech",
                    "player_id": "system-player-10",
                    "speech": "9号转述说8号验6号是因为6号发言像狼。",
                },
            },
            {
                "source_event_id": 637,
                "record_seq": 637,
                "event_type": "public_player_speech_presented",
                "payload": {
                    "round_no": 1,
                    "stage": "day_debate_speech",
                    "player_id": "system-player-11",
                    "speech": "8号警上已经说了，因为6号发言像带节奏才验6号。",
                },
            },
        ],
    }
    projected = project_model_action_context(
        action_context,
        players=players,
    )

    events = _canonical_known_events(projected)["events"]
    assert [(item["speaker_ref"], item["record_seq"]) for item in events] == [
        ("seat_6", 400),
        ("seat_8", 417),
        ("seat_9", 597),
        ("seat_10", 620),
        ("seat_11", 637),
    ]
    assert events[1]["speech"].startswith("8号上警竞选，底牌预言家，昨晚验6号，查杀。")
    assert events[2]["speech"] == "8号因为6号发言带节奏，所以昨晚验了6号。"
    assert all(event["authority"] == "player_claim_unverified" for event in events)
    first_party_annotations = events[1]["annotations"]
    assert [item["claim_type"] for item in first_party_annotations] == [
        "role_claim",
        "investigation_claim",
        "future_investigation_plan",
    ]
    assert first_party_annotations[0]["claimed_role"] == "seer"
    _assert_contains(
        first_party_annotations[1],
        {
            "claimed_action_in": {"period": "night", "round_no": 1},
            "target_ref": "seat_6",
            "claimed_result": "werewolves",
        },
    )
    _assert_contains(
        first_party_annotations[2],
        {
            "target_ref": "seat_9",
            "specificity": "specific_target",
        },
    )
    annotations = [annotation for event in events for annotation in event.get("annotations", [])]
    assert all(
        annotation["authority"] == "player_claim_unverified"
        and annotation["derivation"]["validation_status"] == "complete"
        for annotation in annotations
    )
    assert projected["known_events"]["schema_version"] == KNOWN_EVENTS_SCHEMA_VERSION
    assert model_prompt_metadata(projected)["structured_claim_count"] == len(annotations)
    assert "source_rules" not in json.dumps(projected, ensure_ascii=False)


def test_model_target_and_speech_are_mapped_back_to_internal_identity() -> None:
    assert resolve_model_target("seat_4", players=PLAYERS) == "system-player-09"
    assert resolve_model_target("seat_3", players=PLAYERS) is None
    assert (
        sanitize_model_speech(
            "我建议查验唐梨，不要把system-player-07当成7号。",
            players=PLAYERS,
        )
        == "我建议查验4号，不要把seat_1当成7号。"
    )


def test_public_rule_contract_exposes_single_wolf_and_disabled_sheriff() -> None:
    contract = build_public_rule_contract(
        rule={
            "id": "starter_6",
            "name": "新手 6 人快局",
            "version": "1",
            "player_count": 6,
            "roles": [
                {"role": "狼人", "count": 1, "team": "werewolves"},
                {"role": "预言家", "count": 1, "team": "villagers"},
                {"role": "守卫", "count": 1, "team": "villagers"},
                {"role": "村民", "count": 3, "team": "villagers"},
            ],
            "win_condition": "wolves_gte_others",
            "reveal_policy": "hidden",
            "sheriff_enabled": False,
            "sheriff_vote_weight": 1.0,
            "speech_policy": "sequential",
            "speech_rounds": 1,
            "werewolf_self_explosion_enabled": False,
            "exile_last_words_enabled": True,
            "ability_policies": {
                "werewolf_consensus": {
                    "rounds": 2,
                    "agreement": "unanimous",
                    "unresolved": "no_attack",
                },
                "guard": {
                    "first_night_self_protect": True,
                    "consecutive_same_target": False,
                },
            },
        },
        max_rounds=8,
    )

    assert contract["player_count"] == 6
    assert contract["werewolf_count"] == 1
    assert contract["reveal_policy"] == "hidden"
    assert contract["role_reveal_rule"] == (
        "玩家死亡或被放逐后，法官不会公开其身份或阵营；"
        "出局方式、发言和投票结果均不能作为法官已证实其身份的依据。"
    )
    assert contract["ability_lifecycle"] == {
        "active_abilities_require_alive": True,
        "eliminated_players_can_act_in_later_windows": False,
        "death_triggered_exceptions": [],
    }
    assert "win_condition_contract" not in contract
    assert contract["roles"] == [
        {
            "role_key": "werewolf",
            "role_label": "狼人",
            "count": 1,
            "team": "werewolves",
        },
        {
            "role_key": "seer",
            "role_label": "预言家",
            "count": 1,
            "team": "villagers",
        },
        {
            "role_key": "guard",
            "role_label": "守卫",
            "count": 1,
            "team": "villagers",
        },
        {
            "role_key": "villager",
            "role_label": "村民",
            "count": 3,
            "team": "villagers",
        },
    ]
    assert contract["sheriff_enabled"] is False
    assert contract["sheriff_vote_weight"] is None
    assert contract["sheriff_rule"] == ("本局不启用警长系统，不存在上警、警徽或警徽流机制。")
    assert contract["night_action_rules"]["werewolf_attack"] == {
        "enabled": True,
        "actor_scope": "所有存活狼人",
        "target_scope": "一名存活的非狼人玩家",
        "each_actor_must_choose_target": True,
        "can_target_self": False,
        "can_target_werewolf_teammates": False,
        "team_resolution": {
            "resolution": "unanimous_no_attack",
            "allow_no_attack": False,
            "allow_wolf_target": False,
        },
        "single_werewolf_resolution": (
            "本局只有1名狼人时，由该狼人直接作出最终选择，不会发生团队平票。"
        ),
    }
    assert contract["night_action_rules"]["guard_protect"] == {
        "enabled": True,
        "target_scope": "一名存活玩家，可以选择自己",
        "target_required": True,
        "first_night_self_protect": True,
        "can_repeat_previous_night_target": False,
        "successful_protection_effect": ("若守护目标当夜受到狼人攻击，该目标不会因这次攻击出局。"),
    }


def test_v11_dead_hunter_sees_public_slaughter_boundaries() -> None:
    rule = {
        "id": "classic_12",
        "name": "经典 12 人局",
        "version": "1",
        "player_count": 12,
        "roles": [
            {"role": "狼人", "count": 4, "team": "werewolves"},
            {"role": "村民", "count": 4, "team": "villagers"},
            {"role": "预言家", "count": 1, "team": "villagers"},
            {"role": "女巫", "count": 1, "team": "villagers"},
            {"role": "猎人", "count": 1, "team": "villagers"},
            {"role": "白痴", "count": 1, "team": "villagers"},
        ],
        "win_condition": "slaughter_side",
        "reveal_policy": "hidden",
        "sheriff_enabled": True,
    }
    action_context = {
        **build_actor_information(
            player_id="system-player-01",
            seat=2,
            role_key="hunter",
            team="villagers",
            persona={},
            alive=False,
            sheriff_player_id=None,
            sheriff_badge_state="unassigned",
            rule=rule,
            current_action_type="hunter_death_shot",
        ),
        "action_type": "hunter_death_shot",
        "objective": "决定是否发动猎人技能；发动时选择目标。",
        "round_no": 1,
        "public_rule_contract": build_public_rule_contract(rule=rule, max_rounds=8),
        "public_match_state": {
            "round_no": 1,
            "alive_player_count": 2,
            "alive_player_ids": ["system-player-07", "system-player-09"],
            "eliminated_player_count": 1,
            "eliminated_player_ids": ["system-player-01"],
            "identity_information_included": False,
        },
        "candidates": [
            {"player_id": "system-player-07", "seat": 1, "display_name": "乔宁"},
            {"player_id": "system-player-09", "seat": 4, "display_name": "唐梨"},
        ],
        "public_history": [],
        "output_contract": {
            "kind": "target",
            "target_policy": {"mode": "optional"},
            "speech": {"mode": "forbidden"},
            "decision_note": {"mode": "optional", "max_chars": 120},
        },
    }

    projected = project_model_action_context_with_metadata(
        action_context,
        players=PLAYERS,
        model_context_contract=current_model_context_contract(),
    )
    contract = projected.context["rules"]["win_condition_contract"]

    assert "win_condition_contract" not in action_context["public_rule_contract"]
    assert projected.context["prompt_template_version"] == PROMPT_TEMPLATE_VERSION
    assert projected.projection_metadata["ledger_schema_version"] == 5
    assert contract["mode"] == "slaughter_side"
    assert contract["evaluation_order"] == ["villagers", "werewolves"]
    assert contract["groups"]["living_villagers"] == {"role_keys": ["villager"]}
    assert contract["groups"]["living_gods"] == {"role_keys": ["seer", "witch", "hunter", "idiot"]}
    assert [
        condition["boundary"] for condition in contract["werewolves_victory"]["conditions"]
    ] == ["slaughter_villagers", "slaughter_gods"]
    assert contract["post_elimination_resolution"] == {
        "check": "after_each_elimination_before_next_ordinary_action",
        "outcome_changing_death_triggers": "resolve_before_final_result",
    }
    assert projected.observation_context["hard_rules"]["win_condition_contract"] == contract
    serialized_contract = json.dumps(contract, ensure_ascii=False)
    assert "current_role_counts" not in serialized_contract
    assert "strategy" not in serialized_contract
    assert "instruction" not in serialized_contract


def test_public_match_state_contains_only_public_liveness() -> None:
    class Player:
        def __init__(self, player_id: str, alive: bool) -> None:
            self.player_id = player_id
            self.alive = alive

    state = build_public_match_state(
        round_no=2,
        players=[
            Player("system-player-07", True),
            Player("system-player-01", False),
            Player("system-player-09", True),
        ],
    )

    assert state == {
        "round_no": 2,
        "alive_player_count": 2,
        "alive_player_ids": ["system-player-07", "system-player-09"],
        "eliminated_player_count": 1,
        "eliminated_player_ids": ["system-player-01"],
        "identity_information_included": False,
    }


def test_private_authoritative_facts_flattens_known_investigations() -> None:
    assert private_authoritative_facts(
        {
            "known_investigations": [
                {
                    "fact_type": "investigation_alignment",
                    "payload": {
                        "target_player_id": "seat_4",
                        "alignment": "werewolves",
                        "night_no": 1,
                    },
                }
            ],
            "night_no": 2,
        }
    ) == [
        {
            "fact_type": "investigation_alignment",
            "payload": {
                "target_player_id": "seat_4",
                "alignment": "werewolves",
                "night_no": 1,
            },
        },
        {"fact_type": "night_no", "payload": 2},
    ]


def test_v12_player_prompt_explains_information_authority_and_time() -> None:
    payload = build_model_request_payload(
        {
            "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
            "prompt_template_version": PROMPT_TEMPLATE_VERSION,
            "task": {"type": "day_debate_speech", "goal": "发表本轮白天讨论发言。"},
            "self": {"identity": {"player_id": "seat_2", "role_key": "seer"}},
            "rules": {"reveal_policy": "hidden"},
            "state": {"current_round_no": 1, "as_of_seq": 472},
            "known_events": _compact_known_events(
                [
                    {
                        "event_ref": "400",
                        "kind": "night_result",
                        "authority": "judge_fact",
                        "visibility": "public",
                        "known_at_seq": 400,
                        "occurred_in": {"period": "night", "round_no": 1},
                        "announced_in": {"period": "dawn", "round_no": 1},
                    }
                ]
            ),
            "response": {"kind": "speech", "speech": {"mode": "required"}},
        },
        decision=True,
        model_id="test-model",
        max_output_tokens=16_384,
    )
    system_text = payload["input"][0]["content"][0]["text"]

    assert "authority=judge_fact 是法官事实" in system_text
    assert "authority=player_claim_unverified 是玩家说法" in system_text
    assert "actor_memory/declared_reason 是可修正的主观历史" in system_text
    assert "annotations、questions、relations 只是确定性启发式检索索引" in system_text
    assert "known_events 是玩家工作记忆" in system_text
    assert "可省略旧轮普通发言/逐票" in system_text
    assert "lossless_refs_v1 对入选事件无损" in system_text
    assert "scope_ref 和 occurred_in_ref 按 catalog 展开" in system_text
    assert "defaults.scope_ref_by_kind 和 defaults.occurred_in_ref_by_kind" in system_text
    assert "显式 ref 优先，occurred_in_ref=null 表示无 occurred_in" in system_text
    assert "省略 record_seq 表示它等于 known_at_seq" in system_text
    assert "record_seq=null 表示源记录序号未知" in system_text
    assert "不能用 known_at_seq 代替" in system_text
    assert "annotations 通过 source_event_ref/source_annotation_index" in system_text
    assert "known_at_seq/record_seq 表示获知和记录顺序" in system_text
    assert "occurred_in 表示事件实际发生阶段" in system_text
    assert "公布更晚不代表发生更晚" in system_text
    assert "策略与表达由你决定" in system_text
    assert "不得使用未提供的私密信息" in system_text
    assert "public_timeline" not in system_text
    assert "history" not in system_text
    assert "source_rules" not in system_text
    assert len(system_text) < 1_400


def test_v12_prompt_explains_compact_question_response_semantics() -> None:
    payload = build_model_request_payload(
        {
            "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
            "prompt_template_version": PROMPT_TEMPLATE_VERSION,
            "task": {"type": "day_debate_speech", "goal": "发表本轮白天讨论发言。"},
            "self": {"identity": {"player_id": "seat_2", "role_key": "seer"}},
            "rules": {"reveal_policy": "hidden"},
            "state": {"current_round_no": 1, "as_of_seq": 472},
            "known_events": _compact_known_events(
                [
                    {
                        "event_ref": "10",
                        "kind": "player_statement",
                        "authority": "player_claim_unverified",
                        "visibility": "public",
                        "known_at_seq": 10,
                        "speech": "我先说明验人思路。",
                    },
                    {
                        "event_ref": "20",
                        "kind": "player_statement",
                        "authority": "player_claim_unverified",
                        "visibility": "public",
                        "known_at_seq": 20,
                        "speech": "2号你首验为什么选4号？",
                    },
                    {
                        "event_ref": "30",
                        "kind": "player_statement",
                        "authority": "player_claim_unverified",
                        "visibility": "public",
                        "known_at_seq": 30,
                        "speech": "回应4号，查验理由就是先看边角位。",
                    },
                    {
                        "event_ref": "40",
                        "kind": "speech_turn_skipped_technical",
                        "authority": "judge_fact",
                        "visibility": "public",
                        "known_at_seq": 40,
                    },
                ],
                questions=[
                    {
                        "question_id": "question_20_1",
                        "source_event_ref": "20",
                        "address_resolution": "resolved",
                        "response_status": "response_detected",
                        "requested_fields": ["target_ref", "claimed_result"],
                        "referenced_night_no": 1,
                        "reply_opportunity": "awaiting_scheduled_turn",
                        "prior_relevant_event_refs": ["10"],
                    }
                ],
                relations=[
                    {
                        "type": "response_to_question",
                        "from_event_ref": "30",
                        "to_question_id": "question_20_1",
                    }
                ],
            ),
            "response": {"kind": "speech", "speech": {"mode": "required"}},
        },
        decision=True,
        model_id="test-model",
        max_output_tokens=16_384,
    )
    system_text = payload["input"][0]["content"][0]["text"]

    assert "address_resolution 只表示是否识别出明确被问者" in system_text
    assert "response_status=response_detected 只表示检测到结构上的回应" in system_text
    assert "不表示回应真实、充分、可信或有说服力" in system_text
    assert "response_to_question 关系同样只表示检测到直接回应" in system_text
    assert "尚未轮到发言，不表示拒绝回应" in system_text
    assert "prior_relevant_event_refs 是提问前的相关说明" in system_text
    assert "因技术故障未能发言，不得解读为拒绝回应或策略性沉默" in system_text
    assert "策略与表达由你决定" in system_text
    assert len(system_text) < 1_700


def test_v12_prompt_identifies_the_public_win_condition_contract() -> None:
    payload = build_model_request_payload(
        {
            "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
            "prompt_template_version": PROMPT_TEMPLATE_VERSION,
            "task": {"type": "hunter_death_shot", "goal": "决定是否发动猎人技能。"},
            "self": {"identity": {"player_id": "seat_2", "role_key": "hunter"}},
            "rules": {"win_condition_contract": {"mode": "slaughter_side"}},
            "state": {"current_round_no": 1, "as_of_seq": 472},
            "known_events": _compact_known_events(),
            "candidates": [],
            "response": {
                "kind": "target",
                "target_policy": {"mode": "optional"},
                "speech": {"mode": "forbidden"},
            },
        },
        decision=True,
        model_id="test-model",
        max_output_tokens=16_384,
    )
    system_text = payload["input"][0]["content"][0]["text"]

    assert "rules.win_condition_contract 是本局公开胜负机械合同" in system_text
    assert "evaluation_order 和 post_elimination_resolution" in system_text


def test_private_round_memory_prompt_is_explicitly_non_public() -> None:
    payload = build_model_request_payload(
        {
            "model_context_schema_version": MODEL_CONTEXT_SCHEMA_VERSION,
            "prompt_template_version": PROMPT_TEMPLATE_VERSION,
            "task": {
                "type": "private_round_memory",
                "goal": "生成仅供本人后续决策使用的轮次记忆。",
            },
            "self": {"identity": {"player_id": "seat_2", "role_key": "seer"}},
            "rules": {},
            "state": {"current_round_no": 1, "as_of_seq": 100},
            "known_events": _compact_known_events(),
            "response": {
                "kind": "speech",
                "presentation_kind": "private_round_memory",
                "speech": {"mode": "required", "max_chars": 400},
            },
        },
        decision=True,
        model_id="test-model",
        max_output_tokens=16_384,
    )
    system_text = payload["input"][0]["content"][0]["text"]

    assert "仅供你本人后续决策使用" in system_text
    assert "不会公开播报" in system_text
    assert "不要写成对其他玩家喊话" in system_text
    assert "准备直接播报" not in system_text


def test_actor_information_composes_role_and_sheriff_capabilities() -> None:
    rule = {
        "sheriff_enabled": True,
        "sheriff_vote_weight": 1.5,
        "speech_policy": "sheriff_directed",
        "werewolf_self_explosion_enabled": True,
    }
    seer_sheriff = build_actor_information(
        player_id="system-player-01",
        seat=2,
        role_key="seer",
        team="villagers",
        persona={},
        alive=True,
        sheriff_player_id="system-player-01",
        sheriff_badge_state="held",
        rule=rule,
    )
    villager_sheriff = build_actor_information(
        player_id="system-player-07",
        seat=1,
        role_key="villager",
        team="villagers",
        persona={},
        alive=True,
        sheriff_player_id="system-player-07",
        sheriff_badge_state="held",
        rule=rule,
    )

    assert [item["ability_id"] for item in seer_sheriff["role_capabilities"]["abilities"]] == [
        "seer.investigate"
    ]
    assert [
        item["authority_id"] for item in seer_sheriff["public_office_capabilities"]["abilities"]
    ] == [
        "sheriff.weighted_exile_vote",
        "sheriff.choose_speech_order",
        "sheriff.resolve_badge_after_death",
    ]
    assert villager_sheriff["role_capabilities"]["abilities"] == []
    assert villager_sheriff["public_office_capabilities"]["is_current_sheriff"] is True


def test_actor_information_uses_count_aware_werewolf_capability_wording() -> None:
    base_rule = {
        "sheriff_enabled": False,
        "roles": [
            {"role": "狼人", "count": 1, "team": "werewolves"},
            {"role": "村民", "count": 5, "team": "villagers"},
        ],
    }
    single = build_actor_information(
        player_id="system-player-01",
        seat=2,
        role_key="werewolf",
        team="werewolves",
        persona={},
        alive=True,
        sheriff_player_id=None,
        sheriff_badge_state="disabled",
        rule=base_rule,
    )
    multiple = build_actor_information(
        player_id="system-player-01",
        seat=2,
        role_key="werewolf",
        team="werewolves",
        persona={},
        alive=True,
        sheriff_player_id=None,
        sheriff_badge_state="disabled",
        rule={
            **base_rule,
            "roles": [
                {"role": "狼人", "count": 2, "team": "werewolves"},
                {"role": "村民", "count": 4, "team": "villagers"},
            ],
        },
    )

    single_description = single["role_capabilities"]["abilities"][0]["description"]
    multiple_description = multiple["role_capabilities"]["abilities"][0]["description"]
    assert "本局唯一狼人，独自选择" in single_description
    assert "队友" not in single_description
    assert "存活狼人队友共同选择" in multiple_description


def test_actor_information_separates_owned_abilities_from_consumed_resources() -> None:
    rule = {
        "sheriff_enabled": True,
        "werewolf_self_explosion_enabled": True,
    }
    private_facts = [
        {
            "fact_type": "private_ability_action_committed",
            "payload": {
                "ability_id": "witch.heal",
                "night_no": 1,
                "decision": {"target_player_id": "system-player-07"},
                "result": {"heal_used": True},
            },
        }
    ]
    day_information = build_actor_information(
        player_id="system-player-01",
        seat=2,
        role_key="witch",
        team="villagers",
        persona={},
        alive=True,
        sheriff_player_id=None,
        sheriff_badge_state="held",
        rule=rule,
        private_facts=private_facts,
        current_action_type="day_debate_speech",
    )
    night_information = build_actor_information(
        player_id="system-player-01",
        seat=2,
        role_key="witch",
        team="villagers",
        persona={},
        alive=True,
        sheriff_player_id=None,
        sheriff_badge_state="held",
        rule=rule,
        private_facts=private_facts,
        current_action_type="ability_witch.poison_decision",
        current_action_knowledge={"poison_remaining": 1},
    )

    assert [item["ability_id"] for item in day_information["role_capabilities"]["abilities"]] == [
        "witch.heal",
        "witch.poison",
    ]
    day_runtime = {
        item["ability_id"]: item for item in day_information["ability_runtime_state"]["abilities"]
    }
    assert day_runtime["witch.heal"]["resource_status"] == "consumed"
    assert day_runtime["witch.heal"]["remaining_uses"] == 0
    assert day_runtime["witch.heal"]["can_execute_now"] is False
    assert "last_committed_action" not in day_runtime["witch.heal"]
    assert day_runtime["witch.poison"]["resource_status"] == "available"
    assert day_runtime["witch.poison"]["can_execute_now"] is False

    night_runtime = {
        item["ability_id"]: item for item in night_information["ability_runtime_state"]["abilities"]
    }
    assert night_runtime["witch.heal"]["resource_status"] == "consumed"
    assert night_runtime["witch.poison"]["remaining_uses"] == 1
    assert night_runtime["witch.poison"]["in_current_action_window"] is True
    assert night_runtime["witch.poison"]["can_execute_now"] is True


def _actor_runtime_ability(
    *,
    role_key: str,
    alive: bool,
    current_action_type: str,
    private_facts: list[dict[str, object]] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    information = build_actor_information(
        player_id="system-player-01",
        seat=2,
        role_key=role_key,
        team="villagers",
        persona={},
        alive=alive,
        sheriff_player_id=None,
        sheriff_badge_state="held",
        rule={},
        private_facts=private_facts,
        current_action_type=current_action_type,
    )
    runtime_state = information["ability_runtime_state"]
    ability = next(
        item
        for item in runtime_state["abilities"]
        if item["ability_id"] == ("hunter.death_shot" if role_key == "hunter" else "witch.poison")
    )
    return information, ability


def test_dead_hunter_can_execute_in_ability_death_reaction_window() -> None:
    information, ability = _actor_runtime_ability(
        role_key="hunter",
        alive=False,
        current_action_type="ability_hunter.death_shot_decision",
    )

    assert information["current_state_restrictions"]["alive"] is False
    assert information["ability_runtime_state"]["current_action_ability_id"] == "hunter.death_shot"
    assert ability["in_current_action_window"] is True
    assert ability["can_execute_now"] is True
    assert ability["unavailable_now_reason"] is None


def test_dead_hunter_can_execute_in_legacy_day_death_reaction_window() -> None:
    information, ability = _actor_runtime_ability(
        role_key="hunter",
        alive=False,
        current_action_type="hunter_death_shot",
    )

    assert information["ability_runtime_state"]["current_action_ability_id"] == "hunter.death_shot"
    assert ability["in_current_action_window"] is True
    assert ability["can_execute_now"] is True
    assert ability["unavailable_now_reason"] is None


def test_dead_hunter_cannot_execute_outside_death_reaction_window() -> None:
    _, ability = _actor_runtime_ability(
        role_key="hunter",
        alive=False,
        current_action_type="day_debate_speech",
    )

    assert ability["in_current_action_window"] is False
    assert ability["can_execute_now"] is False
    assert ability["unavailable_now_reason"] == "actor_not_alive"


def test_dead_actor_cannot_execute_non_death_reaction_ability() -> None:
    _, ability = _actor_runtime_ability(
        role_key="witch",
        alive=False,
        current_action_type="ability_witch.poison_decision",
    )

    assert ability["in_current_action_window"] is True
    assert ability["can_execute_now"] is False
    assert ability["unavailable_now_reason"] == "actor_not_alive"


def test_consumed_death_reaction_ability_stays_unavailable() -> None:
    _, ability = _actor_runtime_ability(
        role_key="hunter",
        alive=False,
        current_action_type="ability_hunter.death_shot_decision",
        private_facts=[
            {
                "fact_type": "private_ability_action_committed",
                "payload": {
                    "ability_id": "hunter.death_shot",
                    "result": {"shot_used": True},
                },
            }
        ],
    )

    assert ability["resource_status"] == "consumed"
    assert ability["remaining_uses"] == 0
    assert ability["in_current_action_window"] is True
    assert ability["can_execute_now"] is False
    assert ability["unavailable_now_reason"] == "resource_consumed"


def test_model_context_states_single_wolf_rule_without_generic_teammate_prompt() -> None:
    rule_contract = build_public_rule_contract(
        rule={
            "id": "role-boundaries",
            "name": "角色信息边界",
            "version": "1",
            "player_count": 3,
            "roles": [
                {"role": "狼人", "count": 1, "team": "werewolves"},
                {"role": "预言家", "count": 1, "team": "villagers"},
                {"role": "女巫", "count": 1, "team": "villagers"},
            ],
            "ability_policies": {},
        },
        max_rounds=8,
    )
    projected = project_model_action_context(
        {
            "action_type": "day_debate_speech",
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "werewolf",
                "team": "werewolves",
            },
            "private_authoritative_facts": [
                {
                    "fact_type": "werewolf_teammates",
                    "payload": ["system-player-01"],
                }
            ],
            "output_contract": {
                "kind": "speech",
                "speech": {"mode": "required"},
            },
            "public_rule_contract": rule_contract,
            "public_history": [],
        },
        players=PLAYERS,
    )

    assert projected["rules"]["werewolf_count"] == 1
    assert projected["rules"]["ability_lifecycle"] == {
        "active_abilities_require_alive": True,
        "eliminated_players_can_act_in_later_windows": False,
        "death_triggered_exceptions": [],
    }
    assert "ability_rules" not in projected["rules"]
    assert "current_ability" not in projected["rules"]
    assert projected["self"]["werewolf_coordination"] == {"mode": "solo"}
    assert _canonical_known_events(projected)["events"] == []
    assert "狼人队友" not in json.dumps(projected, ensure_ascii=False)


def test_public_rule_contract_exposes_hunter_as_a_death_triggered_exception() -> None:
    contract = build_public_rule_contract(
        rule={
            "id": "hunter-lifecycle",
            "version": "1",
            "player_count": 3,
            "roles": [
                {"role": "狼人", "count": 1, "team": "werewolves"},
                {"role": "猎人", "count": 1, "team": "villagers"},
                {"role": "村民", "count": 1, "team": "villagers"},
            ],
        },
        max_rounds=8,
    )

    assert contract["ability_lifecycle"] == {
        "active_abilities_require_alive": True,
        "eliminated_players_can_act_in_later_windows": False,
        "death_triggered_exceptions": ["hunter.death_shot"],
    }


def test_legacy_public_rule_contract_without_ability_lifecycle_stays_supported() -> None:
    projected = project_model_action_context(
        {
            "action_type": "day_debate_speech",
            "self_identity": {
                "player_id": "system-player-01",
                "seat": 2,
                "role_key": "villager",
                "team": "villagers",
            },
            "output_contract": {"kind": "speech", "speech": {"mode": "required"}},
            "public_rule_contract": {
                "schema_version": 1,
                "rule_id": "legacy-rule-contract",
                "rule_version": "1",
                "player_count": 3,
                "roles": [],
            },
            "public_history": [],
        },
        players=PLAYERS,
    )

    assert "ability_lifecycle" not in projected["rules"]


def test_model_context_separates_reveals_claims_and_vote_snapshot() -> None:
    projected = project_model_action_context(
        {
            "self_identity": {
                "player_id": "system-player-01",
                "role_key": "seer",
                "team": "villagers",
            },
            "role_capabilities": {"abilities": [{"ability_id": "seer.investigate"}]},
            "public_office_capabilities": {
                "is_current_sheriff": True,
                "abilities": [{"authority_id": "sheriff.weighted_exile_vote"}],
            },
            "public_history": [
                {
                    "source_event_id": "claim-1",
                    "record_seq": 10,
                    "event_type": "day_speech_committed",
                    "payload": {
                        "round_no": 1,
                        "stage": "day_debate",
                        "player_id": "system-player-09",
                        "speech": "我是预言家，2号是我的金水。",
                    },
                },
                {
                    "source_event_id": "vote-1",
                    "record_seq": 20,
                    "event_type": "day_vote_resolved",
                    "payload": {
                        "round_no": 1,
                        "action_type": "exile_vote",
                        "eligible_voter_ids": [
                            "system-player-01",
                            "system-player-09",
                        ],
                        "ineligible_voter_ids": ["system-player-07"],
                        "candidate_player_ids": [
                            "system-player-01",
                            "system-player-09",
                        ],
                        "weighted": True,
                        "sheriff_player_id": "system-player-01",
                        "sheriff_vote_weight": 1.5,
                        "voter_weights": {
                            "system-player-01": 1.5,
                            "system-player-09": 1.0,
                        },
                        "totals": {"system-player-09": 1.5},
                        "leaders": ["system-player-09"],
                    },
                },
                {
                    "source_event_id": "exile-1",
                    "record_seq": 30,
                    "event_type": "player_exiled",
                    "payload": {
                        "round_no": 1,
                        "player_id": "system-player-09",
                    },
                },
                {
                    "source_event_id": "bomb-1",
                    "record_seq": 40,
                    "event_type": "werewolf_self_exploded",
                    "payload": {
                        "round_no": 1,
                        "player_id": "system-player-07",
                        "stage": "day_debate",
                    },
                },
            ],
        },
        players=PLAYERS,
    )

    public_events = _canonical_known_events(projected)["events"]
    assert public_events[0]["speech"] == "我是预言家，2号是我的金水。"
    assert projected["state"]["as_of_seq"] == 41
    vote_snapshot = next(item for item in public_events if item["kind"] == "vote_result")
    assert vote_snapshot["eligible_voter_refs"] == [
        "seat_2",
        "seat_4",
    ]
    assert vote_snapshot["ineligible_voter_refs"] == ["seat_1"]
    assert vote_snapshot["voter_weights"] == {
        "seat_2": 1.5,
        "seat_4": 1.0,
    }
    assert vote_snapshot["totals"] == {"seat_4": 1.5}
    exile_fact = next(item for item in public_events if item.get("public_reason") == "exile")
    assert exile_fact["role_revealed"] is False
    assert "known_role" not in exile_fact
    explosion = next(
        item for item in public_events if item.get("public_reason") == "self_explosion"
    )
    assert explosion["player_ref"] == "seat_1"
    assert explosion["known_role"] == "werewolf"
    assert "history" not in projected
    assert "public_timeline" not in projected
