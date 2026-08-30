from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import get_args

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

import app.cli as cli
from app.db.base import Base
from app.match.contracts import LiveState
from app.match.model_context_contract import current_model_context_contract
from app.match.model_context_cutover import (
    ModelContextCutoverEventFact,
    ModelContextCutoverFacts,
    ModelContextCutoverFinding,
    ModelContextCutoverReport,
    evaluate_v11_model_context_cutover,
    preflight_v12_model_context_cutover,
)
from app.match.models import (
    AbilityActivation,
    AbilityInstance,
    ActionWindow,
    GameRecord,
    GameRecordEvent,
    GameRun,
    LivePresentation,
    MatchState,
    ModelActionRecovery,
    VoiceAsset,
)


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
BLOCKING_LIVE_STATES = (
    "waiting_to_start",
    "ready",
    "generating",
    "broadcasting",
    "finalizing",
    "paused_model_error",
    "awaiting_observation",
)


def _event(
    event_type: str,
    record_seq: int,
    payload: dict[str, object] | None = None,
) -> ModelContextCutoverEventFact:
    return ModelContextCutoverEventFact(
        event_type=event_type,
        record_seq=record_seq,
        payload=dict(payload or {}),
    )


def _facts(**overrides: object) -> ModelContextCutoverFacts:
    values: dict[str, object] = {
        "game_id": "v2_game_cutover001",
        "current_run_id": "v2_run_cutover001",
        "checked_run_id": "v2_run_cutover001",
        "checked_run_game_id": "v2_game_cutover001",
        "prompt_template_version": 4,
        "game_status": "awaiting_observation",
        "phase_state": "game_completed",
        "run_status": "awaiting_observation",
        "match_status": "completed",
        "execution_state": "stopped",
        "winner": "villagers",
        "completion_reason": "",
        "run_completed_at": NOW,
        "worker_id": None,
        "worker_heartbeat_at": None,
        "lease_expires_at": None,
        "fence_token": 1,
        "events": (
            _event("v2_run_execution_claimed", 1),
            _event("game_completed", 10),
            _event("v2_run_execution_released", 11),
        ),
    }
    values.update(overrides)
    return ModelContextCutoverFacts(**values)  # type: ignore[arg-type]


def _v11_contract(prompt_template_version: int) -> dict[str, int]:
    return {
        "model_context_schema_version": 11,
        "prompt_template_version": prompt_template_version,
        "known_events_schema_version": 5,
        "ledger_schema_version": 5,
        "model_view_schema_version": 5,
        "model_view_selector_version": 2,
    }


def test_completed_history_accepts_empty_completion_reason_and_release_after_terminal() -> None:
    finding = evaluate_v11_model_context_cutover(_facts())

    assert finding.is_safe_history
    assert finding.reason_codes == ()


def test_never_owned_terminal_history_is_proven_by_zero_fence_and_empty_owner_fields() -> None:
    finding = evaluate_v11_model_context_cutover(
        _facts(
            fence_token=0,
            events=(_event("game_completed", 10),),
        )
    )

    assert finding.is_safe_history


def test_execution_release_before_terminal_event_does_not_satisfy_cutover() -> None:
    finding = evaluate_v11_model_context_cutover(
        _facts(
            events=(
                _event("v2_run_execution_claimed", 1),
                _event("v2_run_execution_released", 9),
                _event("game_completed", 10),
            ),
        )
    )

    assert "execution_release_after_terminal_missing" in finding.reason_codes


def test_canceled_history_uses_atomic_cancel_fence_evidence_without_release() -> None:
    finding = evaluate_v11_model_context_cutover(
        _facts(
            game_status="canceled",
            phase_state="night_running",
            run_status="canceled",
            match_status="canceled",
            winner=None,
            completion_reason=None,
            fence_token=2,
            events=(
                _event("v2_run_execution_claimed", 1),
                _event("game_canceled", 10, {"invalidated_fence_token": 1}),
            ),
        )
    )

    assert finding.is_safe_history


def test_canceled_history_blocks_when_cancel_transaction_did_not_advance_fence() -> None:
    finding = evaluate_v11_model_context_cutover(
        _facts(
            game_status="canceled",
            phase_state="night_running",
            run_status="canceled",
            match_status="canceled",
            winner=None,
            completion_reason=None,
            fence_token=1,
            events=(
                _event("v2_run_execution_claimed", 1),
                _event("game_canceled", 10, {"invalidated_fence_token": 1}),
            ),
        )
    )

    assert "cancellation_fence_not_advanced" in finding.reason_codes


def test_failed_history_requires_all_failed_states_and_release_after_failure() -> None:
    safe = evaluate_v11_model_context_cutover(
        _facts(
            game_status="failed",
            phase_state="failed",
            run_status="failed",
            match_status="failed",
            winner=None,
            completion_reason="runtime_failed",
            events=(
                _event("v2_run_execution_claimed", 1),
                _event("ability_runtime_failed", 9),
                _event("v2_run_execution_released", 10),
            ),
        )
    )
    missing_release = evaluate_v11_model_context_cutover(
        _facts(
            game_status="failed",
            phase_state="failed",
            run_status="failed",
            match_status="failed",
            winner=None,
            completion_reason="runtime_failed",
            events=(
                _event("v2_run_execution_claimed", 1),
                _event("action_failed", 9),
            ),
        )
    )

    assert safe.is_safe_history
    assert "execution_release_after_terminal_missing" in missing_release.reason_codes


@pytest.mark.parametrize("live_state", BLOCKING_LIVE_STATES)
def test_every_real_nonterminal_live_state_blocks_cutover(live_state: str) -> None:
    assert live_state in get_args(LiveState)
    finding = evaluate_v11_model_context_cutover(
        _facts(
            game_status=live_state,
            phase_state="opening_ready" if live_state == "waiting_to_start" else "night_running",
            run_status=live_state,
            match_status="waiting" if live_state == "waiting_to_start" else "running",
            execution_state="stopped" if live_state == "awaiting_observation" else "unowned",
            winner=None,
            completion_reason=None,
            run_completed_at=None,
            fence_token=0,
            events=(),
        )
    )

    assert "match_status_not_terminal" in finding.reason_codes
    if live_state == "finalizing":
        assert "finalization_in_progress" in finding.reason_codes


def test_open_runtime_resources_recoveries_and_voice_all_block() -> None:
    finding = evaluate_v11_model_context_cutover(
        _facts(
            open_presentation_count=1,
            open_action_window_count=1,
            open_ability_activation_count=1,
            unsafe_recovery_count=1,
            leased_recovery_count=1,
            unfinished_voice_asset_count=1,
        )
    )

    assert set(finding.reason_codes) >= {
        "open_live_presentation",
        "open_action_window",
        "open_ability_activation",
        "model_action_recovery_not_terminal",
        "model_action_recovery_lease_present",
        "unfinished_voice_asset",
    }


def test_missing_current_run_and_owner_fields_fail_closed() -> None:
    finding = evaluate_v11_model_context_cutover(
        _facts(
            checked_run_id=None,
            checked_run_game_id=None,
            execution_state="stale",
            worker_id="worker-a",
            worker_heartbeat_at=NOW,
            lease_expires_at=NOW,
        )
    )

    assert set(finding.reason_codes) >= {
        "current_run_missing",
        "execution_state_not_stopped",
        "execution_owner_fields_not_clear",
    }


@pytest.fixture
def cutover_db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            GameRecord.__table__,
            GameRun.__table__,
            MatchState.__table__,
            GameRecordEvent.__table__,
            LivePresentation.__table__,
            VoiceAsset.__table__,
            ActionWindow.__table__,
            AbilityInstance.__table__,
            AbilityActivation.__table__,
            ModelActionRecovery.__table__,
        ],
    )
    with Session(engine) as db:
        yield db


def _add_game(
    db: Session,
    *,
    suffix: str,
    contract: dict[str, int],
    completed: bool,
) -> tuple[GameRecord, GameRun]:
    game_id = f"v2_game_cutover{suffix}"
    run_id = f"v2_run_cutover{suffix}"
    game = GameRecord(
        game_id=game_id,
        title=f"cutover {suffix}",
        status="awaiting_observation",
        current_run_id=run_id,
        record_schema_version=1,
        last_record_seq=3 if completed else 0,
        last_presentation_seq=0,
        phase_seq=1,
        phase_id="day_1",
        phase_state="game_completed" if completed else "night_running",
        rule_snapshot={"model_context_contract": contract},
        players_snapshot=[],
        judge_voice_snapshot={},
        delivery_snapshot={"schema_version": 1, "mode": "text_only"},
        ability_snapshot={},
    )
    run = GameRun(
        run_id=run_id,
        game_id=game_id,
        attempt_no=1,
        status="awaiting_observation",
        started_at=NOW,
        completed_at=NOW if completed else None,
        fence_token=1 if completed else 0,
    )
    db.add_all([game, run])
    if completed:
        db.add(
            MatchState(
                game_id=game_id,
                round_no=1,
                sheriff_badge_state="disabled",
                pre_sheriff_explosion_count=0,
                winner="villagers",
                completion_reason="",
            )
        )
        for record_seq, event_type in (
            (1, "v2_run_execution_claimed"),
            (2, "game_completed"),
            (3, "v2_run_execution_released"),
        ):
            db.add(
                GameRecordEvent(
                    game_id=game_id,
                    event_id=record_seq,
                    record_seq=record_seq,
                    run_id=run_id,
                    event_type=event_type,
                    payload_schema_version=1,
                    payload={},
                )
            )
    return game, run


def test_database_preflight_recognizes_v11_prompt_3_and_4_and_executes_selects_only(
    cutover_db: Session,
) -> None:
    pending_game, _run = _add_game(
        cutover_db,
        suffix="p3",
        contract=_v11_contract(3),
        completed=True,
    )
    _add_game(cutover_db, suffix="p4", contract=_v11_contract(4), completed=False)
    _add_game(
        cutover_db,
        suffix="v12",
        contract=current_model_context_contract(),
        completed=False,
    )
    cutover_db.commit()
    pending_game.title = "pending caller change must not autoflush"
    statements: list[str] = []

    def capture_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(cutover_db.get_bind(), "before_cursor_execute", capture_statement)
    try:
        report = preflight_v12_model_context_cutover(cutover_db, now=NOW)
    finally:
        event.remove(cutover_db.get_bind(), "before_cursor_execute", capture_statement)

    assert report.scanned_game_count == 3
    assert report.candidate_count == 2
    assert report.safe_history_count == 1
    assert report.blocking_count == 1
    assert report.ignored_current_v12_game_count == 1
    assert {finding.prompt_template_version for finding in report.findings} == {3, 4}
    assert all(
        not statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for statement in statements
    )


def test_database_preflight_blocks_v11_shaped_but_unrecognized_contract(
    cutover_db: Session,
) -> None:
    malformed = _v11_contract(4)
    malformed["known_events_schema_version"] = 6
    _add_game(cutover_db, suffix="badcontract", contract=malformed, completed=True)
    cutover_db.commit()

    report = preflight_v12_model_context_cutover(cutover_db, now=NOW)

    assert report.candidate_count == 1
    assert report.blocking_count == 1
    assert report.findings[0].reason_codes == ("unrecognized_historical_v11_contract",)


def test_database_preflight_blocks_missing_and_unknown_contracts(
    cutover_db: Session,
) -> None:
    missing, _missing_run = _add_game(
        cutover_db,
        suffix="missingcontract",
        contract=_v11_contract(4),
        completed=False,
    )
    missing.rule_snapshot = {}
    unknown = _v11_contract(4)
    unknown["model_context_schema_version"] = 10
    _add_game(cutover_db, suffix="unknowncontract", contract=unknown, completed=False)
    cutover_db.commit()

    report = preflight_v12_model_context_cutover(cutover_db, now=NOW)

    assert report.candidate_count == 2
    assert report.blocking_count == 2
    assert report.ignored_current_v12_game_count == 0
    assert {finding.reason_codes for finding in report.findings} == {
        ("model_context_contract_missing",),
        ("unsupported_model_context_contract_for_cutover",),
    }


def test_database_preflight_queries_all_open_resource_and_lease_boundaries(
    cutover_db: Session,
) -> None:
    game, run = _add_game(
        cutover_db,
        suffix="resources",
        contract=_v11_contract(4),
        completed=True,
    )
    window = ActionWindow(
        window_id="v2_window_cutover001",
        game_id=game.game_id,
        run_id=run.run_id,
        window_seq=1,
        window_type="night",
        state="open",
        ability_snapshot_hash="a" * 64,
        plan=[],
        result={},
    )
    instance = AbilityInstance(
        ability_instance_id="v2_instance_cutover001",
        game_id=game.game_id,
        ability_id="seer.inspect",
        ability_version=1,
        owner_scope="player",
        owner_id="seat_1",
        owner_role_key="seer",
        state={},
    )
    cutover_db.add_all([window, instance])
    cutover_db.flush()
    cutover_db.add_all(
        [
            LivePresentation(
                game_id=game.game_id,
                presentation_seq=1,
                presentation_id="v2_presentation_cutover001",
                action_id="v2_action_cutover001",
                run_id=run.run_id,
                phase_id="day_1",
                actor_kind="player",
                actor_id="seat_1",
                audience="all",
                speech_id="v2_speech_cutover001",
                segment_index=0,
                source_event_id=2,
                state="active",
                subtitle_text="synthetic",
                subtitle_timings=[],
            ),
            VoiceAsset(
                voice_asset_id="v2_voice_cutover001",
                game_id=game.game_id,
                run_id=run.run_id,
                action_id="v2_action_cutover001",
                audience="all",
                presentation_id="v2_presentation_cutover001",
                speech_id="v2_speech_cutover001",
                segment_index=0,
                state="writing",
                storage_key="synthetic.wav",
                mime_type="audio/wav",
                sample_rate=24000,
                channels=1,
            ),
            AbilityActivation(
                activation_id="v2_activation_cutover001",
                game_id=game.game_id,
                run_id=run.run_id,
                window_id=window.window_id,
                ability_instance_id=instance.ability_instance_id,
                occurrence=1,
                status="open",
                knowledge_fact_ids=[],
                decision={},
                result={},
            ),
            ModelActionRecovery(
                action_id="v2_action_recovery_cutover001",
                recovery_id="v2_recovery_cutover001",
                game_id=game.game_id,
                run_id=run.run_id,
                action_type="day_debate",
                actor_id="seat_1",
                model_provider="synthetic",
                model_id="synthetic-model",
                request_payload={},
                request_hash="b" * 64,
                model_context={},
                action_snapshot={},
                failure_code="synthetic_failure",
                failure_category="machine_format",
                attempt_no=1,
                retry_cycle=0,
                state="resolved",
                lease_owner="stale-worker",
                lease_expires_at=NOW,
                resolved_at=NOW,
            ),
        ]
    )
    cutover_db.commit()

    report = preflight_v12_model_context_cutover(cutover_db, now=NOW)

    assert report.blocking_count == 1
    assert set(report.findings[0].reason_codes) >= {
        "open_live_presentation",
        "open_action_window",
        "open_ability_activation",
        "model_action_recovery_lease_present",
        "unfinished_voice_asset",
    }


def test_cutover_cli_returns_one_and_lists_blocking_game(capsys, monkeypatch) -> None:
    finding = ModelContextCutoverFinding(
        game_id="v2_game_blocking001",
        current_run_id="v2_run_blocking001",
        prompt_template_version=4,
        match_status="running",
        execution_state="owned",
        reason_codes=("match_status_not_terminal",),
    )
    report = ModelContextCutoverReport(
        scanned_game_count=1,
        ignored_current_v12_game_count=0,
        findings=(finding,),
    )

    class FakeSession:
        def __enter__(self) -> "FakeSession":
            return self

        def __exit__(self, *_args: object) -> None:
            pass

    monkeypatch.setattr(cli, "SessionLocal", FakeSession)
    monkeypatch.setattr(cli, "preflight_v12_model_context_cutover", lambda _db: report)

    exit_code = cli.main(["preflight-v12-model-context-cutover"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "blocking=1" in output
    assert "BLOCK game_id=v2_game_blocking001 run_id=v2_run_blocking001" in output
    assert "reasons=match_status_not_terminal" in output


def test_cutover_cli_json_marks_safe_empty_database_read_only(capsys, monkeypatch) -> None:
    report = ModelContextCutoverReport(
        scanned_game_count=0,
        ignored_current_v12_game_count=0,
        findings=(),
    )

    class FakeSession:
        def __enter__(self) -> "FakeSession":
            return self

        def __exit__(self, *_args: object) -> None:
            pass

    monkeypatch.setattr(cli, "SessionLocal", FakeSession)
    monkeypatch.setattr(cli, "preflight_v12_model_context_cutover", lambda _db: report)

    exit_code = cli.main(["preflight-v12-model-context-cutover", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["deployable"] is True
    assert payload["read_only"] is True
    assert payload["blocking_count"] == 0
