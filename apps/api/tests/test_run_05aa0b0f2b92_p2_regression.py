from __future__ import annotations

import json
from pathlib import Path

from app.admin.p2_diagnostics import build_game_p2_quality
from app.werewolf.action_choice import normalize_action_choice
from app.werewolf.checkpoint import round_state_from_dict
from app.werewolf.debate_realism import SpeechMissionV1, evaluate_speech_quality
from app.werewolf.lineup_quality import evaluate_lineup_quality, plan_diverse_lineup
from app.werewolf.models import RoundState
from app.werewolf.player_configs import PlayerConfig
from app.werewolf.public_outcomes import (
    append_public_outcome,
    render_public_round_summary,
)


FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "run_05aa0b0f2b92_p2_regression.json"
)


def _config(
    *,
    seat: int,
    profile_id: str,
    personality_id: str,
    strategy_profile: str,
    avatar_asset_id: str,
) -> PlayerConfig:
    return PlayerConfig(
        seat=seat,
        profile_id=profile_id,
        name=f"{seat}号玩家" if seat else profile_id,
        model="fixture-model",
        personality_id=personality_id,
        personality="",
        appearance_id="default",
        tags=(),
        avatar_asset_id=avatar_asset_id,
        strategy_profile=strategy_profile,
    )


def _fixture() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_run_05aa0b0f2b92_p2_lineup_is_detected_and_repaired() -> None:
    fixture = _fixture()
    source = fixture["homogeneous_lineup"]
    player_count = source["player_count"]
    homogeneous = [
        _config(
            seat=seat,
            profile_id=f"source-{seat}",
            personality_id=source["personality_id"],
            strategy_profile=source["strategy_profile"],
            avatar_asset_id=source["avatar_asset_id"],
        )
        for seat in range(1, player_count + 1)
    ]
    before = evaluate_lineup_quality(homogeneous, player_count=player_count)

    candidates = [
        _config(
            seat=0,
            profile_id=item["profile_id"],
            personality_id=item["personality_id"],
            strategy_profile=item["strategy_profile"],
            avatar_asset_id=f"avatar-{item['profile_id']}",
        )
        for item in fixture["repair_candidates"]
    ]
    repaired = plan_diverse_lineup(
        homogeneous,
        candidates,
        player_count=player_count,
        seed=20260714,
        repair_scope="unlocked_all",
    )
    after = evaluate_lineup_quality(
        repaired,
        player_count=player_count,
        was_repaired=True,
    )

    assert before.is_blocked is fixture["acceptance"]["lineup_blocked_before_repair"]
    assert set(source["expected_violation_codes"]) <= {
        violation.code for violation in before.violations
    }
    assert after.is_blocked is fixture["acceptance"]["lineup_blocked_after_repair"]
    assert after.was_repaired is True
    assert after.style_bucket_count >= after.required_style_bucket_count


def test_run_05aa0b0f2b92_p2_rewrites_repetition_and_normalizes_seat() -> None:
    fixture = _fixture()
    speech = fixture["speech_repetition"]
    mission = SpeechMissionV1(**speech["mission"])
    rejected = evaluate_speech_quality(
        text=speech["rejected_draft"],
        prior_texts=speech["prior_texts"],
        mission=mission,
    )
    accepted = evaluate_speech_quality(
        text=speech["accepted_rewrite"],
        prior_texts=speech["prior_texts"],
        mission=mission,
    )

    assert rejected.requires_rewrite is fixture["acceptance"][
        "rejected_draft_requires_rewrite"
    ]
    assert speech["expected_rewrite_code"] in rejected.hard_failure_codes
    assert accepted.requires_rewrite is fixture["acceptance"][
        "accepted_rewrite_requires_rewrite"
    ]
    assert accepted.new_proposition_count > 0

    choice = fixture["choice_normalization"]
    normalized = normalize_action_choice(
        choice["raw_choice"],
        choice["allowed_values"],
    )
    assert normalized.canonical_value == choice["expected_canonical"]
    assert normalized.kind == choice["expected_kind"]


def test_run_05aa0b0f2b92_p2_checkpoint_admin_and_privacy_gate() -> None:
    fixture = _fixture()
    player_count = fixture["homogeneous_lineup"]["player_count"]
    candidates = [
        _config(
            seat=0,
            profile_id=item["profile_id"],
            personality_id=item["personality_id"],
            strategy_profile=item["strategy_profile"],
            avatar_asset_id=f"avatar-{item['profile_id']}",
        )
        for item in fixture["repair_candidates"]
    ]
    repaired = plan_diverse_lineup(
        [],
        candidates,
        player_count=player_count,
        seed=20260714,
    )
    lineup_report = evaluate_lineup_quality(
        repaired,
        player_count=player_count,
        was_repaired=True,
    )

    chain = fixture["hunter_chain"]
    round_state = RoundState(
        number=chain["round_number"],
        players=[f"{seat}号玩家" for seat in range(1, player_count + 1)],
    )
    death = append_public_outcome(
        round_state=round_state,
        session_id=fixture["source_session_id"],
        kind="night_death",
        actor_player_id=None,
        target_player_id=chain["night_target"],
        outcome="eliminated",
        occurred_phase="night",
    )
    append_public_outcome(
        round_state=round_state,
        session_id=fixture["source_session_id"],
        kind="hunter_shot",
        actor_player_id=chain["night_target"],
        target_player_id=chain["hunter_target"],
        outcome="eliminated",
        occurred_phase="night",
        caused_by_event_id=death.event_id,
    )
    round_state.public_summary = (
        f"第{round_state.number}轮；"
        f"{render_public_round_summary(round_state.public_outcome_events)}"
    )
    assert render_public_round_summary(round_state.public_outcome_events) == chain[
        "expected_summary"
    ]

    restored = round_state_from_dict(round_state.to_dict())
    assert [event.event_id for event in restored.public_outcome_events] == [
        event.event_id for event in round_state.public_outcome_events
    ]
    assert restored.public_outcome_next_sequence == 3

    performance = fixture["performance_samples"]
    sentinel = fixture["privacy_sentinel"]
    logs = []
    for index, duration_ms in enumerate(performance["discrete_action_ms"]):
        logs.append(
            {
                "action": "vote",
                "lm_log": {"prompt": sentinel, "raw_response": sentinel},
                "duration_ms": duration_ms,
                "raw_choice": (
                    fixture["choice_normalization"]["raw_choice"]
                    if index == 0
                    else "3号玩家"
                ),
                "choice_normalization_kind": "seat_alias" if index == 0 else "exact",
                "private_candidates": [sentinel],
            }
        )
    for index, first_token_ms in enumerate(performance["speech_first_token_ms"]):
        logs.append(
            {
                "action": "debate",
                "lm_log": {"prompt": sentinel, "raw_response": sentinel},
                "first_token_ms": first_token_ms,
                "speech_quality_report": {"issues": [], "novelty_score": 1.0},
                "speech_quality_attempt_count": 2 if index == 0 else 1,
                "speech_quality_retry_exhausted": False,
                "rejected_draft": sentinel if index == 0 else None,
            }
        )

    result = build_game_p2_quality(
        state={"rounds": [restored.to_dict()]},
        logs=logs,
        lineup_quality_report=lineup_report.to_dict(),
        status="complete",
        terminal=True,
        diagnostic_events=[],
        started_at=None,
        completed_at=None,
    )

    assert result["performance"]["discrete_action_p95_ms"] == performance[
        "expected_discrete_p95_ms"
    ]
    assert result["performance"]["speech_first_token_p95_ms"] == performance[
        "expected_first_token_p95_ms"
    ]
    assert result["performance"]["discrete_action_p95_ms"] <= performance[
        "max_discrete_p95_ms"
    ]
    assert result["choice_normalization"]["seat_alias_count"] == 1
    assert [event["sequence"] for event in result["public_outcomes"]] == [1, 2]
    assert result["public_outcomes"][1]["caused_by_event_id"] == death.event_id
    assert result["public_outcome_summary_mismatch_count"] == 0
    assert len(result["quality_gates"]) == fixture["acceptance"][
        "quality_gate_count"
    ]
    assert {gate["status"] for gate in result["quality_gates"]} == {"pass"}
    assert str(result).count(sentinel) == fixture["acceptance"][
        "private_sentinel_public_occurrences"
    ]
    assert str(result).count(f"'raw_choice': '{fixture['choice_normalization']['raw_choice']}'") == 0
    assert len({event["event_id"] for event in result["public_outcomes"]}) == len(
        result["public_outcomes"]
    )
