from __future__ import annotations

import asyncio
from dataclasses import replace
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

import app.cli as cli
from app.match.model_client import ModelClient
from app.match.model_concurrency_canary import (
    DEFAULT_E1_CANARY_CORPUS_PATH,
    E1CanaryAttemptObservation,
    E1CanaryBudgetLedger,
    E1CanaryCorpus,
    E1CanaryContractError,
    build_e1_cap6_skipped_report,
    build_e1_canary_dry_run_report,
    compare_e1_canary_caps,
    load_e1_canary_corpus,
    summarize_e1_canary_cap,
    validate_e1_canary_live_prerequisites,
)


CORPUS_SHA256 = "544587d04353c815561f044cf4cee4f060b8dda3d82fab976e3d602bd1f8390a"
SCHEDULE_SHA256 = "34427b154767405e8e4c1820445ed5004f7a158abcd3243c2fcae560e28d5399"


def test_fixed_v12_corpus_fails_closed_under_current_v13_contract(tmp_path: Path) -> None:
    raw = json.loads(DEFAULT_E1_CANARY_CORPUS_PATH.read_text(encoding="utf-8"))
    for context in raw["contexts"]:
        context["action_context"]["model_context_schema_version"] = 12
        context["action_context"]["prompt_template_version"] = 5
    corpus_path = tmp_path / "seat_only_v12_workload_v1.json"
    corpus_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(
        E1CanaryContractError,
        match="canary_corpus_model_context_contract_unsupported",
    ):
        load_e1_canary_corpus(corpus_path)


def test_schedule_is_reproducible_and_report_does_not_embed_prompts() -> None:
    first = load_e1_canary_corpus()
    second = load_e1_canary_corpus()
    report = build_e1_canary_dry_run_report(first, caps=(3, 4, 6))

    assert [attempt.audit_dict() for attempt in first.attempts] == [
        attempt.audit_dict() for attempt in second.attempts
    ]
    assert report["external_model_requests"] == 0
    assert report["http_client_created"] is False
    assert report["database_accessed"] is False
    assert report["database_writes"] == 0
    assert report["tts_capability_enabled"] is False
    assert report["configured_output_tokens_per_cap"] == 778_240
    assert report["configured_output_tokens_for_plan"] == 2_334_720
    assert report["cap_6_requires_cap_4_pass"] is True
    assert set(report["attempts"][0]) == {
        "attempt_id",
        "ordinal",
        "wave_index",
        "provider",
        "model_id",
        "response_kind",
        "context_id",
        "request_payload_sha256",
        "configured_max_tokens",
    }
    assert "player_statement" not in json.dumps(report, ensure_ascii=False)


def test_fixture_contexts_pass_real_payload_and_parser_contract_with_mock_transport() -> None:
    corpus = load_e1_canary_corpus()
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        payload = json.loads(request.content)
        context_text = payload["input"][1]["content"][0]["text"]
        if '"kind":"boolean"' in context_text:
            output = '{"self_explode":false}'
        elif '"kind":"target"' in context_text:
            output = '{"target_player_id":"seat_2"}'
        else:
            output = '{"speech":"我会继续核对公开发言与投票是否一致。"}'
        event = json.dumps(
            {"type": "response.output_text.delta", "delta": output},
            ensure_ascii=False,
        )
        return httpx.Response(
            200,
            headers={"x-request-id": f"mock-{len(requests)}"},
            text=f"data: {event}\n\ndata: [DONE]\n\n",
        )

    async def run() -> list[Any]:
        client = ModelClient(
            agent_plan_api_key="fake-agent-plan-key",
            agent_plan_base_url="https://ark.example.test/api/plan/v3",
            ark_api_key="",
            ark_base_url="https://ark.example.test/api/v3",
            deepseek_api_key="",
            deepseek_base_url="https://deepseek.example.test",
            first_token_seconds=1,
            stream_idle_seconds=1,
            total_seconds=2,
            agent_plan_max_in_flight=3,
            transport=httpx.MockTransport(handler),
        )
        decisions = []
        for response_kind in ("boolean", "speech", "target"):
            plan = next(
                attempt for attempt in corpus.attempts if attempt.response_kind == response_kind
            )
            target = client.resolve_model_target(
                model_provider=plan.provider,
                model_id=plan.model_id,
                model_supports_thinking=plan.supports_thinking,
                model_parameters=plan.parameters,
            )
            decisions.append(
                await client.generate_action_decision(
                    action_context=plan.action_context,
                    attempt_id=plan.attempt_id,
                    target=target,
                )
            )
        await client.aclose()
        return decisions

    decisions = asyncio.run(run())

    assert len(requests) == 3
    assert decisions[0].boolean_field == "self_explode"
    assert decisions[0].boolean_value is False
    assert decisions[1].speech == "我会继续核对公开发言与投票是否一致。"
    assert decisions[2].target_player_id == "seat_2"


def _observations(
    *,
    corpus: E1CanaryCorpus,
    cap: int,
    queue_ms: int,
    active_ms: int,
    wall_ms: int,
    failure_count: int = 0,
) -> list[E1CanaryAttemptObservation]:
    return [
        E1CanaryAttemptObservation(
            attempt_id=attempt.attempt_id,
            canary_run_id=f"e1-test-cap-{cap}",
            cap=cap,
            admitted=True,
            queue_wait_ms=queue_ms,
            active_elapsed_ms=active_ms,
            wall_elapsed_ms=wall_ms,
            outcome="success" if index >= failure_count else "http_error",
            http_status=None if index >= failure_count else 503,
            provider_in_flight=min(cap, index + 1),
            total_tokens=100,
        )
        for index, attempt in enumerate(corpus.attempts)
    ]


def _passing_cap4_report() -> dict[str, Any]:
    corpus = load_e1_canary_corpus()
    baseline = summarize_e1_canary_cap(
        corpus=corpus,
        cap=3,
        observations=_observations(
            corpus=corpus,
            cap=3,
            queue_ms=100,
            active_ms=100,
            wall_ms=200,
        ),
        batch_wall_ms=1_000,
    )
    candidate = summarize_e1_canary_cap(
        corpus=corpus,
        cap=4,
        observations=_observations(
            corpus=corpus,
            cap=4,
            queue_ms=70,
            active_ms=110,
            wall_ms=180,
            failure_count=1,
        ),
        batch_wall_ms=850,
    )
    return compare_e1_canary_caps(
        corpus=corpus,
        baseline=baseline,
        candidate=candidate,
    ).as_dict()


def test_cap_summary_uses_all_admitted_attempts_and_nearest_rank() -> None:
    corpus = load_e1_canary_corpus()
    observations = _observations(
        corpus=corpus,
        cap=3,
        queue_ms=100,
        active_ms=200,
        wall_ms=300,
        failure_count=1,
    )
    observations[113] = E1CanaryAttemptObservation(
        attempt_id=observations[113].attempt_id,
        canary_run_id=observations[113].canary_run_id,
        cap=3,
        admitted=True,
        queue_wait_ms=500,
        active_elapsed_ms=900,
        wall_elapsed_ms=1_400,
        outcome="output_budget",
        provider_in_flight=3,
        total_tokens=200,
    )
    summary = summarize_e1_canary_cap(
        corpus=corpus,
        cap=3,
        observations=observations,
        batch_wall_ms=20_000,
    )

    assert summary.admitted_attempt_count == 120
    assert summary.success_count == 118
    assert summary.output_budget_count == 1
    assert summary.http_429_or_5xx_count == 1
    assert summary.queue.p50_ms == 100
    assert summary.queue.p95_ms == 100
    assert summary.queue.max_ms == 500
    assert summary.active.max_ms == 900
    assert summary.provider_in_flight_peak == 3
    assert summary.actual_total_tokens == 12_100


def test_cap_summary_rejects_in_flight_measurement_above_configured_cap() -> None:
    corpus = load_e1_canary_corpus()
    observations = _observations(
        corpus=corpus,
        cap=3,
        queue_ms=100,
        active_ms=200,
        wall_ms=300,
    )
    observations[0] = E1CanaryAttemptObservation(
        attempt_id=observations[0].attempt_id,
        canary_run_id=observations[0].canary_run_id,
        cap=3,
        admitted=True,
        queue_wait_ms=100,
        active_elapsed_ms=200,
        wall_elapsed_ms=300,
        outcome="success",
        provider_in_flight=4,
        total_tokens=100,
    )

    with pytest.raises(E1CanaryContractError, match="provider_in_flight_invalid"):
        summarize_e1_canary_cap(
            corpus=corpus,
            cap=3,
            observations=observations,
            batch_wall_ms=20_000,
        )


def test_cap4_exact_thresholds_pass_and_select_complete_denominator() -> None:
    corpus = load_e1_canary_corpus()
    baseline = summarize_e1_canary_cap(
        corpus=corpus,
        cap=3,
        observations=_observations(
            corpus=corpus,
            cap=3,
            queue_ms=100,
            active_ms=100,
            wall_ms=200,
        ),
        batch_wall_ms=1_000,
    )
    candidate = summarize_e1_canary_cap(
        corpus=corpus,
        cap=4,
        observations=_observations(
            corpus=corpus,
            cap=4,
            queue_ms=70,
            active_ms=110,
            wall_ms=180,
            failure_count=1,
        ),
        batch_wall_ms=850,
    )

    report = compare_e1_canary_caps(
        corpus=corpus,
        baseline=baseline,
        candidate=candidate,
    )

    assert report.passed is True
    assert report.checks["queue_p95_improvement"]["observed"] == pytest.approx(0.30)
    assert report.checks["batch_wall_improvement"]["observed"] == pytest.approx(0.15)
    assert report.checks["active_p95_regression"]["observed"] == pytest.approx(0.10)
    assert report.checks["success_rate_drop"]["observed"] == pytest.approx(1 / 120)
    assert report.checks["http_429_or_5xx_increment"]["observed"] == pytest.approx(1 / 120)
    assert report.baseline_summary["corpus_sha256"] == corpus.corpus_sha256
    assert report.baseline_summary["schedule_sha256"] == corpus.schedule_sha256
    assert report.baseline_summary["canary_run_id"] == "e1-test-cap-3"
    assert report.candidate_summary["canary_run_id"] == "e1-test-cap-4"


def test_incomplete_or_regressed_cap4_fails_and_cannot_unlock_cap6() -> None:
    corpus = load_e1_canary_corpus()
    baseline = summarize_e1_canary_cap(
        corpus=corpus,
        cap=3,
        observations=_observations(
            corpus=corpus,
            cap=3,
            queue_ms=100,
            active_ms=100,
            wall_ms=200,
        ),
        batch_wall_ms=1_000,
    )
    candidate_observations = _observations(
        corpus=corpus,
        cap=4,
        queue_ms=80,
        active_ms=120,
        wall_ms=200,
    )
    candidate_observations[-1] = replace(
        candidate_observations[-1],
        admitted=False,
        queue_wait_ms=None,
        active_elapsed_ms=None,
        wall_elapsed_ms=None,
        outcome="not_admitted",
        provider_in_flight=None,
        total_tokens=None,
    )
    candidate = summarize_e1_canary_cap(
        corpus=corpus,
        cap=4,
        observations=candidate_observations,
        batch_wall_ms=900,
        invariant_failures=("permit_leak",),
    )
    report = compare_e1_canary_caps(
        corpus=corpus,
        baseline=baseline,
        candidate=candidate,
    )

    assert report.passed is False
    assert report.checks["complete_120_admitted_each"]["passed"] is False
    assert report.checks["runtime_invariants"]["passed"] is False
    skipped = build_e1_cap6_skipped_report(corpus=corpus, cap4_report=report)
    assert skipped.baseline_cap == 4
    assert skipped.candidate_cap == 6
    assert skipped.passed is False
    assert skipped.skipped_reason == "cap4_go_no_go_failed"
    with pytest.raises(
        E1CanaryContractError,
        match="canary_cap6_requires_same_process_cap4_result",
    ):
        validate_e1_canary_live_prerequisites(
            corpus,
            caps=(6,),
            confirm_external_model_calls=True,
            confirm_billing_authorized=True,
            ledger=_empty_ledger(),
            cap4_report=report.as_dict(),
        )


def _empty_ledger(**overrides: Any) -> E1CanaryBudgetLedger:
    values: dict[str, Any] = {
        "requests_used": 0,
        "wall_seconds_used": 0,
        "configured_output_tokens_used": 0,
        "actual_total_tokens_used": 0,
        "billing_authorization_id": "approval-test-only",
    }
    values.update(overrides)
    return E1CanaryBudgetLedger(**values)


def test_live_prerequisites_require_two_confirmations_and_budget_capacity() -> None:
    corpus = load_e1_canary_corpus()

    with pytest.raises(E1CanaryContractError, match="external_model_calls_not_confirmed"):
        validate_e1_canary_live_prerequisites(
            corpus,
            caps=(3, 4),
            confirm_external_model_calls=False,
            confirm_billing_authorized=True,
            ledger=_empty_ledger(),
        )
    with pytest.raises(E1CanaryContractError, match="billing_not_confirmed"):
        validate_e1_canary_live_prerequisites(
            corpus,
            caps=(3, 4),
            confirm_external_model_calls=True,
            confirm_billing_authorized=False,
            ledger=_empty_ledger(),
        )

    reservation = validate_e1_canary_live_prerequisites(
        corpus,
        caps=(3, 4),
        confirm_external_model_calls=True,
        confirm_billing_authorized=True,
        ledger=_empty_ledger(),
    )
    assert reservation == {
        "planned_requests": 240,
        "planned_wall_seconds": 14_400,
        "planned_configured_output_tokens": 1_556_480,
        "remaining_requests_after_reservation": 530,
        "remaining_wall_seconds_after_reservation": 36_000,
        "remaining_configured_output_tokens_after_reservation": 4_843_520,
    }
    cap3_reservation = validate_e1_canary_live_prerequisites(
        corpus,
        caps=(3,),
        confirm_external_model_calls=True,
        confirm_billing_authorized=True,
        ledger=_empty_ledger(actual_total_tokens_used=None),
    )
    assert cap3_reservation["planned_requests"] == 120
    assert cap3_reservation["planned_configured_output_tokens"] == 778_240

    with pytest.raises(E1CanaryContractError, match="global_request_budget_exceeded"):
        validate_e1_canary_live_prerequisites(
            corpus,
            caps=(3, 4),
            confirm_external_model_calls=True,
            confirm_billing_authorized=True,
            ledger=_empty_ledger(requests_used=600),
        )
    with pytest.raises(E1CanaryContractError, match="actual_token_budget_exhausted"):
        validate_e1_canary_live_prerequisites(
            corpus,
            caps=(3,),
            confirm_external_model_calls=True,
            confirm_billing_authorized=True,
            ledger=_empty_ledger(actual_total_tokens_used=12_000_000),
        )


def test_cap6_rejects_even_self_consistent_external_cap4_report() -> None:
    corpus = load_e1_canary_corpus()
    forged_report = _passing_cap4_report()
    forged_report["baseline_summary"]["canary_run_id"] = "forged-external-cap3"
    forged_report["candidate_summary"]["canary_run_id"] = "forged-external-cap4"

    with pytest.raises(
        E1CanaryContractError,
        match="canary_cap6_requires_same_process_cap4_result",
    ):
        validate_e1_canary_live_prerequisites(
            corpus,
            caps=(6,),
            confirm_external_model_calls=True,
            confirm_billing_authorized=True,
            ledger=_empty_ledger(),
            cap4_report=forged_report,
        )


@pytest.mark.parametrize(
    ("caps", "expected_code"),
    (
        ((4,), "canary_live_cap_plan_invalid"),
        ((6,), "canary_cap6_requires_same_process_cap4_result"),
        ((3, 6), "canary_cap6_requires_same_process_cap4_result"),
        ((4, 6), "canary_cap6_requires_same_process_cap4_result"),
        ((3, 4, 6), "canary_cap6_requires_same_process_cap4_result"),
        ((4, 3), "canary_caps_order_invalid"),
    ),
)
def test_live_prerequisites_reject_partial_or_untrusted_cap_transitions(
    caps: tuple[int, ...],
    expected_code: str,
) -> None:
    corpus = load_e1_canary_corpus()

    with pytest.raises(E1CanaryContractError, match=expected_code):
        validate_e1_canary_live_prerequisites(
            corpus,
            caps=caps,
            confirm_external_model_calls=True,
            confirm_billing_authorized=True,
            ledger=_empty_ledger(),
        )


def test_external_cap4_report_is_never_an_authorization_artifact() -> None:
    corpus = load_e1_canary_corpus()

    with pytest.raises(
        E1CanaryContractError,
        match="canary_external_cap4_report_not_authoritative",
    ):
        validate_e1_canary_live_prerequisites(
            corpus,
            caps=(3, 4),
            confirm_external_model_calls=True,
            confirm_billing_authorized=True,
            ledger=_empty_ledger(),
            cap4_report=_passing_cap4_report(),
        )


@pytest.mark.parametrize(
    ("ledger_overrides", "expected_code"),
    (
        ({"requests_used": -1}, "canary_budget_requests_invalid"),
        ({"requests_used": True}, "canary_budget_requests_invalid"),
        ({"wall_seconds_used": -1}, "canary_budget_wall_invalid"),
        (
            {"configured_output_tokens_used": -1},
            "canary_budget_configured_tokens_invalid",
        ),
        ({"actual_total_tokens_used": -1}, "canary_budget_actual_tokens_invalid"),
        ({"actual_total_tokens_used": True}, "canary_budget_actual_tokens_invalid"),
        (
            {"billing_authorization_id": "   "},
            "canary_budget_billing_authorization_missing",
        ),
    ),
)
def test_live_prerequisites_revalidate_direct_budget_ledger_dataclass(
    ledger_overrides: dict[str, Any],
    expected_code: str,
) -> None:
    corpus = load_e1_canary_corpus()

    with pytest.raises(E1CanaryContractError, match=expected_code):
        validate_e1_canary_live_prerequisites(
            corpus,
            caps=(3,),
            confirm_external_model_calls=True,
            confirm_billing_authorized=True,
            ledger=_empty_ledger(**ledger_overrides),
        )


def test_corpus_rejects_non_seat_identity_marker(tmp_path: Path) -> None:
    raw = json.loads(DEFAULT_E1_CANARY_CORPUS_PATH.read_text(encoding="utf-8"))
    raw["contexts"][0]["action_context"]["self"]["player_id"] = "system-player-09"
    path = tmp_path / "bad-corpus.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        E1CanaryContractError,
        match="canary_context_contains_real_identifier_marker",
    ):
        load_e1_canary_corpus(path)


@pytest.mark.parametrize(
    ("context_index", "path"),
    (
        (0, ("state", "alive_player_ids", 0)),
        (1, ("state", "speech_order", 0)),
        (2, ("candidates", 0, "player_id")),
    ),
)
def test_corpus_rejects_uuid_in_player_reference_lists(
    tmp_path: Path,
    context_index: int,
    path: tuple[str | int, ...],
) -> None:
    raw = json.loads(DEFAULT_E1_CANARY_CORPUS_PATH.read_text(encoding="utf-8"))
    target: Any = raw["contexts"][context_index]["action_context"]
    for component in path[:-1]:
        target = target[component]
    target[path[-1]] = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
    corpus_path = tmp_path / f"uuid-list-{context_index}.json"
    corpus_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        E1CanaryContractError,
        match="canary_context_player_ref_not_seat_only",
    ):
        load_e1_canary_corpus(corpus_path)


def test_corpus_rejects_uuid_in_injected_allowed_target_ids(tmp_path: Path) -> None:
    raw = json.loads(DEFAULT_E1_CANARY_CORPUS_PATH.read_text(encoding="utf-8"))
    target_policy = raw["contexts"][2]["action_context"]["response"]["target_policy"]
    target_policy["allowed_target_ids"] = ["f47ac10b-58cc-4372-a567-0e02b2c3d479"]
    corpus_path = tmp_path / "uuid-allowed-targets.json"
    corpus_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        E1CanaryContractError,
        match="canary_context_player_ref_not_seat_only",
    ):
        load_e1_canary_corpus(corpus_path)


@pytest.mark.parametrize(
    ("context_index", "container_path", "field", "value"),
    (
        (
            1,
            ("task",),
            "resulting_speech_order",
            ["f47ac10b-58cc-4372-a567-0e02b2c3d479"],
        ),
        (
            0,
            ("state",),
            "teammate_refs",
            ["f47ac10b-58cc-4372-a567-0e02b2c3d479"],
        ),
        (
            2,
            ("response", "target_policy"),
            "target_ref",
            "f47ac10b-58cc-4372-a567-0e02b2c3d479",
        ),
    ),
)
def test_corpus_rejects_uuid_in_known_v13_player_ref_paths(
    tmp_path: Path,
    context_index: int,
    container_path: tuple[str, ...],
    field: str,
    value: Any,
) -> None:
    raw = json.loads(DEFAULT_E1_CANARY_CORPUS_PATH.read_text(encoding="utf-8"))
    target: Any = raw["contexts"][context_index]["action_context"]
    for component in container_path:
        target = target[component]
    target[field] = value
    corpus_path = tmp_path / f"uuid-v13-ref-{context_index}-{field}.json"
    corpus_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(
        E1CanaryContractError,
        match="canary_context_player_ref_not_seat_only",
    ):
        load_e1_canary_corpus(corpus_path)


def test_live_prerequisites_reject_valid_but_unpinned_corpus(tmp_path: Path) -> None:
    raw = json.loads(DEFAULT_E1_CANARY_CORPUS_PATH.read_text(encoding="utf-8"))
    raw["corpus_id"] = "e1_agent_plan_seat_only_v13_unpinned_test"
    corpus_path = tmp_path / "unpinned-corpus.json"
    corpus_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    corpus = load_e1_canary_corpus(corpus_path)

    with pytest.raises(E1CanaryContractError, match="canary_live_corpus_not_pinned"):
        validate_e1_canary_live_prerequisites(
            corpus,
            caps=(3,),
            confirm_external_model_calls=True,
            confirm_billing_authorized=True,
            ledger=_empty_ledger(),
        )


def test_cap_summary_rejects_relabelled_attempt_ids_and_mixed_run_ids() -> None:
    corpus = load_e1_canary_corpus()
    observations = _observations(
        corpus=corpus,
        cap=3,
        queue_ms=100,
        active_ms=100,
        wall_ms=200,
    )
    observations[0] = replace(
        observations[0],
        attempt_id="f47ac10b-58cc-4372-a567-0e02b2c3d479",
    )
    with pytest.raises(E1CanaryContractError, match="attempt_set_mismatch"):
        summarize_e1_canary_cap(
            corpus=corpus,
            cap=3,
            observations=observations,
            batch_wall_ms=1_000,
        )

    observations = _observations(
        corpus=corpus,
        cap=3,
        queue_ms=100,
        active_ms=100,
        wall_ms=200,
    )
    observations[0] = replace(observations[0], canary_run_id="another-run")
    with pytest.raises(E1CanaryContractError, match="run_id_invalid"):
        summarize_e1_canary_cap(
            corpus=corpus,
            cap=3,
            observations=observations,
            batch_wall_ms=1_000,
        )


def test_cap_summary_rejects_tampered_corpus_plan_with_stale_schedule_hash() -> None:
    corpus = load_e1_canary_corpus()
    tampered_attempts = list(corpus.attempts)
    tampered_attempts[0] = replace(
        tampered_attempts[0],
        attempt_id="f47ac10b-58cc-4372-a567-0e02b2c3d479",
    )
    tampered = replace(corpus, attempts=tuple(tampered_attempts))
    observations = _observations(
        corpus=tampered,
        cap=3,
        queue_ms=100,
        active_ms=100,
        wall_ms=200,
    )

    with pytest.raises(E1CanaryContractError, match="corpus_attempt_plan_invalid"):
        summarize_e1_canary_cap(
            corpus=tampered,
            cap=3,
            observations=observations,
            batch_wall_ms=1_000,
        )


def test_cli_defaults_to_zero_request_dry_run(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    def forbidden_http_client(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("dry-run must not create an HTTP client")

    def forbidden_database_session(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("dry-run must not create a database session")

    monkeypatch.setattr("app.match.model_client.httpx.AsyncClient", forbidden_http_client)
    monkeypatch.setattr("app.cli.SessionLocal", forbidden_database_session)

    exit_code = cli.main(["run-v2-agent-plan-canary"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "e1_canary=dry_run" in captured.out
    assert "external_requests=0" in captured.out
    assert "http_client_created=false" in captured.out
    assert captured.err == ""


def test_cli_execute_fails_closed_even_after_all_offline_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    def forbidden_http_client(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("offline E1 build must not create an HTTP client")

    def forbidden_database_session(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("offline E1 build must not create a database session")

    monkeypatch.setattr("app.match.model_client.httpx.AsyncClient", forbidden_http_client)
    monkeypatch.setattr("app.cli.SessionLocal", forbidden_database_session)
    ledger = tmp_path / "ledger.json"
    ledger.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "requests_used": 0,
                "wall_seconds_used": 0,
                "configured_output_tokens_used": 0,
                "actual_total_tokens_used": 0,
                "billing_authorization_id": "approval-test-only",
            }
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "run-v2-agent-plan-canary",
            "--execute",
            "--confirm-external-model-calls",
            "--confirm-billing-authorized",
            "--budget-ledger",
            str(ledger),
            "--caps",
            "3",
            "4",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "live_execution_not_implemented" in captured.err
    assert "no HTTP client was created" in captured.err


def test_cli_execute_without_dual_confirmation_refuses_before_live_mode(
    tmp_path: Path,
    capsys,
) -> None:
    ledger = tmp_path / "ledger.json"
    ledger.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "requests_used": 0,
                "wall_seconds_used": 0,
                "configured_output_tokens_used": 0,
                "actual_total_tokens_used": None,
                "billing_authorization_id": "approval-test-only",
            }
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "run-v2-agent-plan-canary",
            "--execute",
            "--budget-ledger",
            str(ledger),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "canary_external_model_calls_not_confirmed" in captured.err
