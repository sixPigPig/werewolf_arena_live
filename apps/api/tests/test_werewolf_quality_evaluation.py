from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.werewolf.evaluation_bundle import build_quality_evaluation_bundle
from app.werewolf.quality_evaluation import evaluate_quality_bundle


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "werewolf_quality"
HMAC_KEY = "test-quality-evaluation-key"
SENTINEL = "P3_PRIVATE_SENTINEL_11号计划刀10号并嫁祸12号"


def _evaluate_fixture(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    bundle = build_quality_evaluation_bundle(
        state=data["state"],
        logs=data["logs"],
        live_events=data["live_events"],
        voice_utterances=data["voice_utterances"],
        run_id=data["run_id"],
    )
    return evaluate_quality_bundle(bundle, hmac_key=HMAC_KEY).to_dict()


def test_leaking_fixture_detects_every_public_channel_without_returning_text() -> None:
    report = _evaluate_fixture(FIXTURE_DIR / "run_05aa0b0f2b92_leaking.json")

    channels = {issue["channel"] for issue in report["safe_issues"]}
    assert {"live_event", "voice", "subtitle", "replay", "public_state"} <= channels
    assert report["verdict"] == "fail"
    assert report["issue_counts"]["P0"] >= 5
    assert SENTINEL not in json.dumps(report, ensure_ascii=False)


def test_sanitized_fixture_allows_legal_reveals_and_has_no_p0() -> None:
    report = _evaluate_fixture(FIXTURE_DIR / "run_05aa0b0f2b92_sanitized.json")

    assert report["verdict"] == "pass"
    assert report["issue_counts"]["P0"] == 0
    assert report["voice"]["terminal_judge_voice_coverage"] is True


def test_quality_coverage_counts_coalesced_live_voice_range() -> None:
    bundle = build_quality_evaluation_bundle(
        state={"session_id": "game_1234abcd", "rounds": []},
        logs=[],
        live_events=[
            {
                "id": 9,
                "type": "action_parsed",
                "run_id": "run_voice_range",
                "session_id": "game_1234abcd",
                "created_at": "2026-07-14T00:00:00Z",
                "actor": "阿青",
                "action": "debate",
                "payload": {"visible_result": {"say": "完整发言。"}},
            }
        ],
        voice_utterances=[
            {
                "utterance_id": "voice_live",
                "source_event_id": 7,
                "last_source_event_id": 9,
                "speaker_kind": "player",
                "status": "complete",
                "text": "完整发言。",
            }
        ],
        run_id="run_voice_range",
    )

    report = evaluate_quality_bundle(bundle, hmac_key=HMAC_KEY)

    assert report.voice["effective_voice_event_count"] == 1
    assert report.voice["missing_narratable_event_count"] == 0


def test_liveness_metrics_have_explicit_denominators_and_stage_breakdown() -> None:
    bundle = build_quality_evaluation_bundle(
        state={"session_id": "game_liveness", "rounds": []},
        logs=[
            {
                "actor": "阿青",
                "action": "debate",
                "prompt_chars": 420,
                "liveness_timing": {
                    "turn_ready_at": 1_784_505_599_200,
                    "actor_brain_started_at": 1_784_505_599_210,
                    "turn_plan_ready_at": 1_784_505_599_240,
                    "renderer_started_at": 1_784_505_599_250,
                    "first_model_delta_at": 1_784_505_599_290,
                    "first_clause_committed_at": 1_784_505_599_320,
                    "hard_gate_duration_ms": 4,
                },
                "speech_turn_receipt": {
                    "speech_id": "speech_liveness",
                    "status": "partial",
                },
                "lm_log": {
                    "action_id": "action_liveness",
                    "hard_speech_gate_rejected_count": 1,
                },
            }
        ],
        liveness_runtime={
            "experience_revision": "liveness-v1",
            "experiment_id": "experiment-1",
            "variant": "treatment",
            "experience_snapshot": {
                "feature_modes": {"sentence_stream": "committed_segments"}
            },
            "voice_timings": [
                {
                    "speech_id": "speech_liveness",
                    "status": "complete",
                    "tts_started_at": "2026-07-20T00:00:00+00:00",
                    "first_audio_chunk_at": "2026-07-20T00:00:00.080000+00:00",
                }
            ],
            "playback_observations": [
                {
                    "playback_session_id": "playback-1",
                    "client_status": "completed",
                    "playback_started_at": "2026-07-20T00:00:00.100000+00:00",
                    "playback_finished_at": "2026-07-20T00:00:01+00:00",
                    "ack_received_at": "2026-07-20T00:00:01.020000+00:00",
                },
                {
                    "playback_session_id": "playback-1",
                    "client_status": "completed",
                    "playback_started_at": "2026-07-20T00:00:01.120000+00:00",
                    "playback_finished_at": "2026-07-20T00:00:02+00:00",
                    "ack_received_at": "2026-07-20T00:00:02.020000+00:00",
                }
            ],
            "actor_mind": {
                "snapshot_count": 3,
                "update_count": 8,
                "source_complete_count": 8,
            },
        },
    )

    liveness = evaluate_quality_bundle(bundle, hmac_key=HMAC_KEY).liveness

    assert liveness["public_speech_count"] == 1
    assert liveness["timing_coverage"]["first_clause_committed_at"] == {
        "count": 1,
        "denominator": 1,
        "rate": 1.0,
    }
    assert liveness["stage_latency_ms"]["renderer_to_first_delta"]["p95"] == 40
    assert liveness["stage_latency_ms"]["turn_to_first_clause"]["p95"] == 120
    assert liveness["tts_to_first_audio_ms"]["p95"] == 80
    assert liveness["turn_to_first_audio_ms"]["p95"] == 880
    assert liveness["voice_timing_coverage"]["denominator"] == 1
    assert liveness["playback_timing_coverage"]["denominator"] == 2
    assert liveness["speaker_gap_ms"]["p95"] == 120
    assert liveness["hard_retry_rate"] == 1.0
    assert liveness["partial_speech_count"] == 1
    assert liveness["actor_mind"]["source_complete_count"] == 8


def test_bundle_revision_and_issue_ids_are_deterministic() -> None:
    data = json.loads((FIXTURE_DIR / "run_05aa0b0f2b92_leaking.json").read_text(encoding="utf-8"))
    first_bundle = build_quality_evaluation_bundle(
        state=data["state"],
        logs=data["logs"],
        live_events=data["live_events"],
        voice_utterances=data["voice_utterances"],
        run_id=data["run_id"],
    )
    second_bundle = build_quality_evaluation_bundle(
        state=data["state"],
        logs=data["logs"],
        live_events=list(reversed(data["live_events"])),
        voice_utterances=list(reversed(data["voice_utterances"])),
        run_id=data["run_id"],
    )
    timestamp = datetime(2026, 7, 14, tzinfo=UTC)
    first = evaluate_quality_bundle(first_bundle, hmac_key=HMAC_KEY, evaluated_at=timestamp)
    second = evaluate_quality_bundle(second_bundle, hmac_key=HMAC_KEY, evaluated_at=timestamp)

    assert first_bundle.source_revision == second_bundle.source_revision
    assert first.to_dict() == second.to_dict()


def test_private_action_visible_result_is_p0_even_without_text_overlap() -> None:
    bundle = build_quality_evaluation_bundle(
        state={"session_id": "game_1234abcd", "rounds": []},
        logs=[],
        live_events=[
            {
                "id": 1,
                "type": "action_parsed",
                "run_id": "run_private",
                "session_id": "game_1234abcd",
                "created_at": "2026-07-14T00:00:00Z",
                "round": 1,
                "phase": "night",
                "actor": "1号玩家",
                "action": "werewolf_kill_vote",
                "payload": {"visible_result": {"target": "2号玩家"}},
            }
        ],
        voice_utterances=[],
    )

    report = evaluate_quality_bundle(bundle, hmac_key=HMAC_KEY)

    assert "private_action_public_artifact" in {issue.code for issue in report.safe_issues}


def test_rejected_draft_marker_is_p0_and_safe() -> None:
    bundle = build_quality_evaluation_bundle(
        state={"session_id": "game_1234abcd", "rounds": []},
        logs=[],
        live_events=[
            {
                "id": 2,
                "type": "speech_published",
                "run_id": "run_rejected",
                "session_id": "game_1234abcd",
                "created_at": "2026-07-14T00:00:00Z",
                "round": 1,
                "phase": "day",
                "actor": "1号玩家",
                "action": "debate",
                "payload": {"visible_text": "REJECTED_SECRET", "rejected": True},
            }
        ],
        voice_utterances=[],
    )

    report = evaluate_quality_bundle(bundle, hmac_key=HMAC_KEY)

    assert "rejected_draft_public" in {issue.code for issue in report.safe_issues}
    assert "REJECTED_SECRET" not in json.dumps(report.to_dict(), ensure_ascii=False)


def test_critical_action_cards_are_bounded_and_never_copy_private_reasoning() -> None:
    sentinel = "PRIVATE_REASONING_DECISION_CARD_SENTINEL"
    logs = [
        {
            "number": 1,
            "votes": [
                {
                    "actor": f"{index + 1}号玩家",
                    "action": "vote",
                    "options": ["1号玩家"],
                    "choice": "1号玩家",
                    "lifecycle_status": "completed",
                    "effective_origin": "model",
                    "lm_log": {
                        "action_id": f"act_bounded_{index:03d}",
                        "request_id": f"req_bounded_{index:03d}",
                        "prompt": "白天放逐按唯一最高票结算，平票进入PK二轮投票。",
                        "raw_response": sentinel,
                        "result": {
                            "reasoning": f"普通战术判断。{sentinel}",
                            "vote": "1号玩家",
                        },
                    },
                }
                for index in range(80)
            ],
        }
    ]
    bundle = build_quality_evaluation_bundle(
        state={"session_id": "game_bounded_cards", "rounds": []},
        logs=logs,
    )

    report = evaluate_quality_bundle(bundle, hmac_key=HMAC_KEY)
    payload = report.to_dict()

    assert len(payload["critical_actions"]) == 64
    assert payload["critical_actions"][0]["action_id"] == "act_bounded_000"
    assert payload["critical_actions"][-1]["action_id"] == "act_bounded_063"
    assert {item["reasoning_observation"] for item in payload["critical_actions"]} == {
        "not_available"
    }
    assert sentinel not in json.dumps(payload, ensure_ascii=False)


def test_critical_action_cards_derive_stable_id_for_legacy_system_fallback() -> None:
    logs = [
        {
            "number": 2,
            "werewolf_votes": [
                [
                    {
                        "actor": "system",
                        "action": "remove",
                        "options": ["3号玩家", "4号玩家"],
                        "choice": "3号玩家",
                        "lifecycle_status": "fallback",
                        "effective_origin": "system_fallback",
                        "reason_code": "collective_no_result",
                        "lm_log": {
                            "prompt": "",
                            "raw_response": "",
                            "result": {"target": "3号玩家"},
                        },
                    }
                ]
            ],
        }
    ]
    bundle = build_quality_evaluation_bundle(
        state={"session_id": "game_legacy_system_card", "rounds": []},
        logs=logs,
    )

    first = evaluate_quality_bundle(bundle, hmac_key=HMAC_KEY).to_dict()[
        "critical_actions"
    ]
    second = evaluate_quality_bundle(bundle, hmac_key=HMAC_KEY).to_dict()[
        "critical_actions"
    ]

    assert first == second
    assert len(first) == 1
    assert first[0]["action_id"].startswith("act_safe_")
    assert first[0]["action_origin"] == "system_fallback"
    assert first[0]["direct_impact"] == "game_state_effect_applied"
