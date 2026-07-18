from __future__ import annotations

import concurrent.futures
import json
import threading
import time
from collections.abc import Iterable
from types import SimpleNamespace

import pytest

import app.werewolf.engine as engine_module
from app.werewolf.checkpoint import round_log_from_dict, round_state_from_dict
from app.werewolf.config import VILLAGER, WEREWOLF
from app.werewolf.engine import GameEngine, initialize_game_state
from app.werewolf.execution_budget import (
    ActionExecutionBudgetV1,
    ModelDeadlineExceeded,
)
from app.werewolf.models import RoundLog, RoundState
from app.werewolf.rules import (
    ACTION_EXILE_LAST_WORDS,
    ACTION_REMOVE,
    ACTION_WEREWOLF_DISCUSS,
    ACTION_WEREWOLF_KILL_VOTE,
    get_rule_set,
)


class CapturingEventSink:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.events: list[dict[str, object]] = []

    def publish(self, event_type: str, **kwargs: object) -> object:
        with self._lock:
            self.events.append({"type": event_type, **kwargs})
            return SimpleNamespace(id=len(self.events))

    def snapshot(self) -> list[dict[str, object]]:
        with self._lock:
            return [dict(event) for event in self.events]


def _extract_actor_name(prompt: str) -> str:
    marker = "- 你是"
    if marker not in prompt:
        return ""
    return prompt.split(marker, 1)[1].split("，", 1)[0]


def _extract_options(prompt: str) -> list[str]:
    marker = next(
        (candidate for candidate in ("候选人：", "候选选项：") if candidate in prompt),
        "",
    )
    if not marker:
        return []
    tail = prompt.split(marker, 1)[1].split("。", 1)[0]
    return [option.strip() for option in tail.split("、") if option.strip()]


def _wait_for_event(
    sink: CapturingEventSink,
    *,
    event_type: str,
    request_id: str,
    timeout: float = 1.0,
) -> list[dict[str, object]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        matches = [
            event
            for event in sink.snapshot()
            if event["type"] == event_type
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("request_id") == request_id
        ]
        if matches:
            return matches
        threading.Event().wait(0.005)
    return []


class BlockingWolfProvider:
    def __init__(self, *, offline_wolf: str, timeout_stage: str, target: str) -> None:
        self.offline_wolf = offline_wolf
        self.timeout_stage = timeout_stage
        self.target = target
        self.blocked = threading.Event()
        self.release = threading.Event()
        self.late_returned = threading.Event()

    def complete_json(
        self,
        *,
        model: str,
        prompt: str,
        temperature: float,
        call_options: object | None = None,
    ) -> str:
        del model, temperature, call_options
        actor = _extract_actor_name(prompt)
        options = _extract_options(prompt)
        is_proposal = "狼人夜晚第一轮私密表态" in prompt
        is_final_vote = "狼人夜晚最终表态与狼刀投票" in prompt
        should_block = actor == self.offline_wolf and (
            (self.timeout_stage == "proposal" and is_proposal)
            or (self.timeout_stage == "final" and is_final_vote)
        )
        if should_block:
            self.blocked.set()
            self.release.wait(timeout=2.0)

        if is_proposal:
            # A split proposal guarantees that the final-vote branch runs.
            target = options[-1] if actor == self.offline_wolf else self.target
            response = {
                "reasoning": "LATE_PRIVATE_REASONING" if should_block else "先汇总刀口。",
                "target": target,
                "message": "LATE_PRIVATE_MESSAGE" if should_block else f"建议选择{target}。",
            }
        elif is_final_vote:
            response = {
                "reasoning": "LATE_PRIVATE_REASONING" if should_block else "最终跟随有效刀口。",
                "target": self.target,
                "message": "LATE_PRIVATE_MESSAGE" if should_block else f"最终选择{self.target}。",
            }
        else:  # pragma: no cover - a focused failure message is clearer than KeyError.
            raise AssertionError(f"unexpected wolf prompt: {prompt}")

        if should_block:
            self.late_returned.set()
        return json.dumps(response, ensure_ascii=False)


@pytest.mark.parametrize(
    ("timeout_stage", "expected_action", "expected_decision_stage"),
    [
        ("proposal", ACTION_WEREWOLF_DISCUSS, "proposal"),
        ("final", ACTION_WEREWOLF_KILL_VOTE, "final"),
    ],
)
def test_wolf_individual_timeout_is_audited_abstention_and_late_result_is_discarded(
    monkeypatch: pytest.MonkeyPatch,
    timeout_stage: str,
    expected_action: str,
    expected_decision_stage: str,
) -> None:
    rule_set = get_rule_set("classic_8")
    state = initialize_game_state(
        session_id=f"wolf_{timeout_stage}_timeout_audit",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=16060126,
        rule_set=rule_set,
    )
    wolves = [player.name for player in state.players if player.role == WEREWOLF]
    non_wolves = [player.name for player in state.players if player.role != WEREWOLF]
    active_players = [player.name for player in state.players]
    target = non_wolves[0]
    offline_wolf = wolves[-1]
    provider = BlockingWolfProvider(
        offline_wolf=offline_wolf,
        timeout_stage=timeout_stage,
        target=target,
    )
    sink = CapturingEventSink()
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    monkeypatch.setattr(engine_module, "WEREWOLF_DISCUSSION_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(engine_module, "WEREWOLF_FINAL_VOTE_TIMEOUT_SECONDS", 0.05)
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
        fallback_seed=16060126,
    )

    try:
        attacked = engine._run_werewolf_kill_consensus(
            round_state,
            round_log,
            active_players,
            wolves,
            non_wolves,
        )
        assert provider.blocked.is_set()
        assert attacked == target
        committed_record = dict(round_state.werewolf_vote_rounds[0])

        candidate_logs = (
            round_log.werewolf_discussion
            if timeout_stage == "proposal"
            else round_log.werewolf_votes[0]
        )
        failed_log = next(log for log in candidate_logs if log.actor == offline_wolf)
        assert failed_log.action == expected_action
        assert failed_log.execution_status == "failed"
        assert failed_log.reason_code == "batch_deadline"
        assert failed_log.effective_origin == "none"
        assert failed_log.choice is None
        assert failed_log.fallback_choice is None
        assert failed_log.fallback_reason is None
        assert failed_log.lm_log.action_id is not None
        assert failed_log.lm_log.action_id.startswith("act_")
        assert failed_log.lm_log.request_id is not None
        assert failed_log.lm_log.request_id.startswith("req_")
        assert failed_log.lm_log.attempt_outcomes == [
            {
                "action_id": failed_log.lm_log.action_id,
                "request_id": failed_log.lm_log.request_id,
                "attempt_result": "timed_out",
            }
        ]

        events_before_release = sink.snapshot()
        started = [
            event
            for event in events_before_release
            if event["type"] == "model_request_started"
            and event.get("actor") == offline_wolf
            and event.get("action") == expected_action
            and event["payload"].get("request_id") == failed_log.lm_log.request_id
        ]
        assert len(started) == 1
        assert started[0]["payload"]["action_id"] == failed_log.lm_log.action_id
        assert set(started[0]["payload"]) <= {
            "action_id",
            "request_id",
            "model",
            "attempt",
            "attempt_result",
            "reason_code",
            "discard_reason",
        }

        abstentions = [
            event
            for event in events_before_release
            if event["type"] == "action_parsed"
            and event.get("actor") == offline_wolf
            and event.get("action") == expected_action
            and event["payload"].get("decision_stage")
            == expected_decision_stage
        ]
        assert len(abstentions) == 1
        assert abstentions[0]["payload"] == {
            "action_id": failed_log.lm_log.action_id,
            "request_id": failed_log.lm_log.request_id,
            "choice": None,
            "result": {},
            "visible_result": {},
            "message": "",
            "decision_stage": expected_decision_stage,
            "vote_round": 1,
            "action_origin": "none",
            "public_reason_code": "batch_deadline",
        }
        if timeout_stage == "proposal":
            assert offline_wolf not in {
                entry["speaker"] for entry in round_state.werewolf_discussion
            }
        else:
            assert offline_wolf not in round_state.werewolf_vote_rounds[0]["votes"]

        assert "LATE_PRIVATE_REASONING" not in str(events_before_release)
        assert "LATE_PRIVATE_MESSAGE" not in str(events_before_release)
    finally:
        provider.release.set()

    assert provider.late_returned.wait(timeout=1.0)
    late_discards = _wait_for_event(
        sink,
        event_type="late_result_discarded",
        request_id=failed_log.lm_log.request_id,
    )
    assert len(late_discards) == 1
    assert late_discards[0]["actor"] == offline_wolf
    assert late_discards[0]["action"] == expected_action
    assert late_discards[0]["payload"] == {
        "action_id": failed_log.lm_log.action_id,
        "request_id": failed_log.lm_log.request_id,
        "discard_reason": "deadline_result_already_committed",
    }
    assert round_state.werewolf_vote_rounds[0] == committed_record
    assert round_state.werewolf_vote_rounds[0]["result"] == attacked
    assert "LATE_PRIVATE_REASONING" not in str(sink.snapshot())
    assert "LATE_PRIVATE_MESSAGE" not in str(sink.snapshot())


class AlwaysTimeoutProvider:
    def complete_json(
        self,
        *,
        model: str,
        prompt: str,
        temperature: float,
        call_options: object | None = None,
    ) -> str:
        del model, prompt, temperature, call_options
        raise ModelDeadlineExceeded("test provider timeout")


def test_all_wolf_timeouts_use_stable_collective_system_action() -> None:
    rule_set = get_rule_set("classic_8")

    def run_once() -> tuple[str, dict[str, object], RoundLog]:
        state = initialize_game_state(
            session_id="all_wolf_timeouts_stable_action",
            villager_model="villager-model",
            werewolf_model="wolf-model",
            seed=16060126,
            rule_set=rule_set,
        )
        wolves = [player.name for player in state.players if player.role == WEREWOLF]
        non_wolves = [player.name for player in state.players if player.role != WEREWOLF]
        active_players = [player.name for player in state.players]
        round_state = RoundState(number=1, players=active_players.copy())
        round_log = RoundLog(number=1)
        engine = GameEngine(
            state=state,
            provider=AlwaysTimeoutProvider(),
            max_rounds=8,
            rule_set=rule_set,
            fallback_seed=16060126,
        )

        attacked = engine._run_werewolf_kill_consensus(
            round_state,
            round_log,
            active_players,
            wolves,
            non_wolves,
        )

        assert attacked is not None
        return attacked, round_state.werewolf_vote_rounds[0], round_log

    first_target, first_record, first_log = run_once()
    second_target, second_record, second_log = run_once()

    assert first_target == second_target
    assert first_record == second_record
    assert first_record["votes"] == {}
    assert first_record["fallback"] == {
        "source": "system_fallback",
        "reason_code": "collective_no_result",
    }
    first_system_log = first_log.werewolf_votes[-1][0]
    second_system_log = second_log.werewolf_votes[-1][0]
    assert first_system_log.actor == "system"
    assert first_system_log.action == ACTION_REMOVE
    assert first_system_log.execution_status == "fallback"
    assert first_system_log.effective_origin == "system_fallback"
    assert first_system_log.choice == first_target
    assert first_system_log.fallback_choice == first_target
    assert first_system_log.reason_code == "collective_no_result"
    assert first_system_log.lm_log.action_id is not None
    assert first_system_log.lm_log.action_id.startswith("act_")
    assert first_system_log.lm_log.action_id == second_system_log.lm_log.action_id
    assert first_log.eliminate is first_system_log
    assert second_log.eliminate is second_system_log
    for failed_log in [
        *first_log.werewolf_discussion,
        *first_log.werewolf_votes[0],
    ]:
        assert failed_log.execution_status == "failed"
        assert failed_log.choice is None
        assert failed_log.fallback_choice is None
        assert failed_log.effective_origin == "none"
        assert failed_log.lm_log.attempt_outcomes[-1]["attempt_result"] == "timed_out"


class ValidVoteProvider:
    def complete_json(
        self,
        *,
        model: str,
        prompt: str,
        temperature: float,
        call_options: object | None = None,
    ) -> str:
        del model, temperature, call_options
        options = _extract_options(prompt)
        return json.dumps(
            {
                "reasoning": "RACE_RESULT_MUST_NOT_COMMIT",
                "vote": options[-1],
            },
            ensure_ascii=False,
        )


def test_batch_deadline_commit_gate_discards_future_completed_in_wait_close_race(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rule_set = get_rule_set("classic_8")
    state = initialize_game_state(
        session_id="batch_wait_close_race",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=16060126,
        rule_set=rule_set,
    )
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=ValidVoteProvider(),
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
        action_budgets_enabled=True,
        action_execution_budget=ActionExecutionBudgetV1(
            required_request_seconds=2.0,
            required_total_seconds=2.0,
            required_batch_seconds=1.0,
        ),
        fallback_seed=16060126,
    )
    requests = [
        engine._build_player_action_request(
            player=player,
            action="vote",
            options=active_players[2:],
            result_key="vote",
            round_state=round_state,
            phase="day",
        )
        for player in state.players[:2]
    ]

    def completed_future_reported_pending(
        futures: Iterable[concurrent.futures.Future[object]],
        timeout: float | None = None,
    ) -> tuple[
        set[concurrent.futures.Future[object]],
        set[concurrent.futures.Future[object]],
    ]:
        del timeout
        ordered = list(futures)
        done, pending = concurrent.futures.wait(ordered, timeout=1.0)
        assert not pending
        assert done == set(ordered)
        # Deterministically emulate completion after wait's deadline decision but
        # before the caller closes the commit gate.
        return set(ordered[1:]), {ordered[0]}

    monkeypatch.setattr(engine_module, "wait", completed_future_reported_pending)

    results = engine._player_actions_batch(requests)

    raced_value, raced_log = results[0]
    committed_value, committed_log = results[1]
    assert raced_log.execution_status == "fallback"
    assert raced_log.reason_code == "batch_deadline"
    assert raced_log.fallback_reason == "batch_deadline_deterministic_legal_choice"
    assert raced_value == engine._deterministic_timeout_choice(requests[0])
    assert raced_log.choice == raced_value
    assert raced_log.lm_log.raw_response == ""
    assert committed_log.execution_status == "completed"
    assert committed_value == active_players[-1]

    late_discards = [
        event
        for event in sink.snapshot()
        if event["type"] == "late_result_discarded"
        and event.get("actor") == requests[0].player.name
    ]
    assert len(late_discards) == 1
    assert late_discards[0]["payload"]["action_id"] == requests[0].action_id
    assert late_discards[0]["payload"]["discard_reason"] == (
        "deadline_result_already_committed"
    )
    parsed_for_raced_actor = [
        event
        for event in sink.snapshot()
        if event["type"] == "action_parsed"
        and event.get("actor") == requests[0].player.name
        and event.get("action") == "vote"
    ]
    assert len(parsed_for_raced_actor) == 1
    assert parsed_for_raced_actor[0]["payload"]["choice"] == raced_value
    assert parsed_for_raced_actor[0]["payload"]["action_origin"] == "system_fallback"
    assert parsed_for_raced_actor[0]["payload"]["public_reason_code"] == (
        "batch_deadline"
    )


def test_exile_last_words_timeout_persists_skipped_with_low_cardinality_reason() -> None:
    rule_set = get_rule_set("classic_12_seer_witch_hunter_idiot")
    state = initialize_game_state(
        session_id="last_words_timeout_persistence",
        villager_model="villager-model",
        werewolf_model="wolf-model",
        seed=16060126,
        rule_set=rule_set,
    )
    exiled = next(player.name for player in state.players if player.role == VILLAGER)
    active_players = [player.name for player in state.players]
    round_state = RoundState(number=1, players=active_players.copy())
    round_log = RoundLog(number=1)
    sink = CapturingEventSink()
    engine = GameEngine(
        state=state,
        provider=AlwaysTimeoutProvider(),
        max_rounds=8,
        rule_set=rule_set,
        event_sink=sink,
        action_budgets_enabled=True,
        fallback_seed=16060126,
    )

    engine._resolve_day_exile(exiled, round_state, round_log, active_players)

    assert round_state.exile_last_words == {
        "player": exiled,
        "message": "",
        "status": "skipped",
        "reason_code": "timeout",
    }
    assert round_log.exile_last_words is not None
    assert round_log.exile_last_words.action == ACTION_EXILE_LAST_WORDS
    assert round_log.exile_last_words.execution_status == "failed"
    assert round_log.exile_last_words.reason_code == "timeout"
    assert round_log.exile_last_words.choice is None
    assert round_log.exile_last_words.effective_origin == "none"

    restored_state = round_state_from_dict(round_state.to_dict())
    restored_log = round_log_from_dict(round_log.to_dict())
    assert restored_state.exile_last_words == round_state.exile_last_words
    assert restored_state.exile_last_words["status"] == "skipped"
    assert restored_state.exile_last_words["reason_code"] == "timeout"
    assert restored_log.exile_last_words is not None
    assert restored_log.exile_last_words.execution_status == "failed"
    assert restored_log.exile_last_words.reason_code == "timeout"
    assert not any(
        event["type"] == "action_parsed"
        and event.get("action") == ACTION_EXILE_LAST_WORDS
        and event["payload"].get("speech_status") == "spoken"
        for event in sink.snapshot()
    )
