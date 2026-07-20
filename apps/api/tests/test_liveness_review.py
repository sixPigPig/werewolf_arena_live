from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.werewolf.liveness_review import (
    FrozenReviewManifest,
    ReviewRating,
    analyze_review_ratings,
    build_review_package,
    write_review_package,
)
from app.werewolf.liveness_review_panel import (
    PANEL_DIMENSIONS,
    build_panel_prompt,
    normalize_panel_batch,
    panel_json_schema,
    random_user_sample,
    reconcile_orientation_ratings,
    swapped_packet,
)
from app.werewolf.liveness_review_pilot import (
    PilotSourceManifest,
    generate_manifest,
)


def _manifest() -> FrozenReviewManifest:
    return FrozenReviewManifest.model_validate(
        {
            "schema_version": 1,
            "experiment_id": "lifelike-v1",
            "scenarios": [
                {
                    "scenario_id": "debate-001",
                    "slice": "debate",
                    "context": "上一位玩家刚刚质疑了当前发言者。",
                    "baseline": {
                        "timeline": [
                            {
                                "speaker": "2号玩家",
                                "text": "我没有问题。",
                                "audio_ref": "baseline/001.mp3",
                                "start_ms": 300,
                                "end_ms": 1600,
                            }
                        ]
                    },
                    "candidate": {
                        "timeline": [
                            {
                                "speaker": "2号玩家",
                                "text": "你刚才点我，那我就把这票型说清楚。",
                                "audio_ref": "candidate/001.mp3",
                                "start_ms": 180,
                                "end_ms": 2100,
                            }
                        ]
                    },
                },
                {
                    "scenario_id": "pk-001",
                    "slice": "pk",
                    "context": "两位玩家进入放逐 PK。",
                    "baseline": {
                        "timeline": [
                            {
                                "speaker": "5号玩家",
                                "text": "请相信我。",
                                "start_ms": 400,
                                "end_ms": 1200,
                            }
                        ]
                    },
                    "candidate": {
                        "timeline": [
                            {
                                "speaker": "5号玩家",
                                "text": "到了 PK 我只回答三号刚才那个问题。",
                                "start_ms": 220,
                                "end_ms": 1800,
                            }
                        ]
                    },
                },
            ],
        }
    )


def test_review_export_is_stable_anonymous_and_keeps_key_private(tmp_path):
    manifest = _manifest()
    audio = tmp_path / "baseline" / "001.mp3"
    audio.parent.mkdir()
    audio.write_bytes(b"fake-mp3")
    candidate_audio = tmp_path / "candidate" / "001.mp3"
    candidate_audio.parent.mkdir()
    candidate_audio.write_bytes(b"fake-candidate-mp3")
    first = build_review_package(manifest, randomization_seed="secret-seed")
    second = build_review_package(manifest, randomization_seed="secret-seed")
    assert first == second
    public_json = json.dumps(first.reviewer_packet, ensure_ascii=False)
    assert "baseline" not in public_json
    assert "candidate" not in public_json
    assert "lifelike-v1" not in public_json
    assert "model" not in public_json

    output = tmp_path / "review"
    write_review_package(first, output, media_root=tmp_path)
    assert (output / "reviewer_packet.json").is_file()
    assert (output / "private" / "answer_key.json").is_file()
    assert (output / "ratings_template.json").is_file()
    assert list((output / "media").glob("**/*.mp3"))
    with pytest.raises(FileExistsError):
        write_review_package(first, output, media_root=tmp_path)


def test_manifest_rejects_duplicate_scenario_and_invalid_timeline():
    raw = _manifest().model_dump(mode="json")
    raw["scenarios"][1]["scenario_id"] = "debate-001"
    with pytest.raises(ValidationError, match="scenario_id must be unique"):
        FrozenReviewManifest.model_validate(raw)

    raw = _manifest().model_dump(mode="json")
    raw["scenarios"][0]["candidate"]["timeline"][0]["end_ms"] = 1
    raw["scenarios"][0]["candidate"]["timeline"][0]["start_ms"] = 2
    with pytest.raises(ValidationError, match="end_ms"):
        FrozenReviewManifest.model_validate(raw)


def test_analysis_uses_scenario_cluster_bootstrap_and_reports_gates():
    package = build_review_package(_manifest(), randomization_seed="secret-seed")
    ratings = []
    for reviewer in ("r1", "r2", "r3"):
        for item in package.answer_key["items"]:
            ratings.append(
                ReviewRating(
                    reviewer_id=reviewer,
                    item_id=item["item_id"],
                    choice=item["candidate_side"],
                )
            )
    result = analyze_review_ratings(
        answer_key=package.answer_key,
        ratings=ratings,
        bootstrap_samples=1_000,
        bootstrap_seed=7,
    )
    assert result["cluster_unit"] == "scenario_id"
    assert result["candidate_preference"] == 1.0
    assert result["confidence_interval_95"] == {"lower": 1.0, "upper": 1.0}
    assert result["minimum_reviewers_per_item"] == 3
    assert all(result["gates"].values())


def test_analysis_keeps_skip_and_broken_media_in_denominator_reporting():
    package = build_review_package(_manifest(), randomization_seed="secret-seed")
    item = package.answer_key["items"][0]
    result = analyze_review_ratings(
        answer_key=package.answer_key,
        ratings=[
            ReviewRating(
                reviewer_id="r1",
                item_id=item["item_id"],
                choice="skip",
                media_status="missing",
            )
        ],
        bootstrap_samples=1_000,
    )
    assert result["judgments_total"] == 1
    assert result["judgments_usable"] == 0
    assert result["missing_or_damaged_rate"] == 1.0
    assert result["candidate_preference"] is None


def test_analysis_rejects_duplicate_reviewer_item():
    package = build_review_package(_manifest(), randomization_seed="secret-seed")
    item = package.answer_key["items"][0]
    rating = ReviewRating(
        reviewer_id="r1",
        item_id=item["item_id"],
        choice="tie",
    )
    with pytest.raises(ValueError, match="same item"):
        analyze_review_ratings(
            answer_key=package.answer_key,
            ratings=[rating, rating],
            bootstrap_samples=1_000,
        )


def _panel_batch(packet, *, choice="left"):
    return {
        "ratings": [
            {
                "item_id": item["item_id"],
                "choice": choice,
                "dimensions": {name: 4 for name in PANEL_DIMENSIONS},
                "reason": "能具体接住前文，并保持公开事实一致。",
            }
            for item in packet["items"]
        ]
    }


def test_panel_prompt_swap_and_normalization_hide_orientation():
    packet = build_review_package(_manifest(), randomization_seed="panel").reviewer_packet
    prompt = build_panel_prompt(packet)
    assert "不要猜版本" in prompt
    assert set(item["item_id"] for item in packet["items"]) <= set(prompt.split('"'))

    swapped = swapped_packet(packet)
    assert swapped["items"][0]["left"] == packet["items"][0]["right"]
    assert swapped["items"][0]["right"] == packet["items"][0]["left"]
    normalized, evidence = normalize_panel_batch(
        _panel_batch(swapped, choice="left"),
        reviewer_id="model-swapped",
        expected_item_ids={item["item_id"] for item in packet["items"]},
        sides_swapped=True,
    )
    assert all(rating.choice == "right" for rating in normalized)
    assert all(item["presented_choice"] == "left" for item in evidence)


def test_panel_reconcile_turns_orientation_disagreement_into_tie():
    packet = build_review_package(_manifest(), randomization_seed="panel").reviewer_packet
    expected = {item["item_id"] for item in packet["items"]}
    first, _ = normalize_panel_batch(
        _panel_batch(packet, choice="left"),
        reviewer_id="first",
        expected_item_ids=expected,
        sides_swapped=False,
    )
    second, _ = normalize_panel_batch(
        _panel_batch(packet, choice="right"),
        reviewer_id="second",
        expected_item_ids=expected,
        sides_swapped=False,
    )
    result, stability = reconcile_orientation_ratings(
        first,
        second,
        reviewer_id="model",
    )
    assert all(rating.choice == "tie" for rating in result)
    assert all(not item["stable"] for item in stability)


def test_panel_schema_and_user_sample_are_deterministic_and_anonymous():
    packet = build_review_package(_manifest(), randomization_seed="panel").reviewer_packet
    schema = panel_json_schema(expected_items=2)
    assert schema["properties"]["ratings"]["minItems"] == 2
    first = random_user_sample(packet, sample_size=1, seed="user-sample")
    second = random_user_sample(packet, sample_size=1, seed="user-sample")
    assert first == second
    public_json = json.dumps(first, ensure_ascii=False)
    assert "baseline" not in public_json
    assert "candidate" not in public_json
    assert first["sampling"]["seed_sha256"] != "user-sample"


def test_pilot_generation_uses_current_public_renderer_and_keeps_source_private():
    class _Generator:
        def __init__(self):
            self.prompts = []

        def complete_json(self, *, model, prompt, temperature):
            self.prompts.append((model, prompt, temperature))
            return '{"say":"你刚才点我，那我就把这票说清楚。"}'

    source = PilotSourceManifest.model_validate(
        {
            "schema_version": 1,
            "experiment_id": "pilot-test",
            "generator_model": "deepseek-v4-flash",
            "scenarios": [
                {
                    "scenario_id": "scene-001",
                    "slice": "debate",
                    "action": "debate",
                    "speaker": "2号玩家",
                    "context": "1号刚刚质疑2号。",
                    "baseline_text": "我没有问题。",
                    "public_speech_scene": {
                        "schema_version": 1,
                        "public_actor_name": "2号玩家",
                        "persona_style": "直接",
                        "public_state_boundary": {},
                        "recent_committed_turns": ["1号：我质疑2号。"],
                        "relevant_public_facts": [],
                        "public_stimulus": [],
                        "turn_plan": {"primary_speech_act": "respond"},
                    },
                    "source_trace": {"session_id": "private-session"},
                }
            ],
        }
    )
    provider = _Generator()
    manifest, evidence = generate_manifest(source, provider=provider)  # type: ignore[arg-type]
    assert manifest.scenarios[0].candidate.timeline[0].text.startswith("你刚才点我")
    assert "狼人杀桌边口语表达器" in provider.prompts[0][1]
    assert "private-session" not in manifest.model_dump_json()
    assert evidence["items"][0]["source_trace"]["session_id"] == "private-session"
