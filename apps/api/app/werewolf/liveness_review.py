from __future__ import annotations

import hashlib
import json
import math
import random
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewTimelineEntry(_StrictModel):
    speaker: str = Field(min_length=1, max_length=100)
    text: str = Field(default="", max_length=10_000)
    audio_ref: str | None = Field(default=None, max_length=2_000)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)

    @field_validator("end_ms")
    @classmethod
    def _end_is_not_negative(cls, value: int) -> int:
        return value


class ReviewVariant(_StrictModel):
    timeline: list[ReviewTimelineEntry] = Field(min_length=1, max_length=100)


class FrozenScenarioPair(_StrictModel):
    scenario_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,100}$")
    slice: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,100}$")
    context: str = Field(default="", max_length=20_000)
    baseline: ReviewVariant
    candidate: ReviewVariant


class FrozenReviewManifest(_StrictModel):
    schema_version: Literal[1]
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,100}$")
    scenarios: list[FrozenScenarioPair] = Field(min_length=1, max_length=5_000)

    @field_validator("scenarios")
    @classmethod
    def _unique_scenarios(
        cls, scenarios: list[FrozenScenarioPair]
    ) -> list[FrozenScenarioPair]:
        ids = [scenario.scenario_id for scenario in scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("scenario_id must be unique")
        for scenario in scenarios:
            for variant in (scenario.baseline, scenario.candidate):
                for entry in variant.timeline:
                    if entry.end_ms < entry.start_ms:
                        raise ValueError("timeline end_ms must be >= start_ms")
        return scenarios


class ReviewRating(_StrictModel):
    reviewer_id: str = Field(min_length=1, max_length=200)
    item_id: str = Field(pattern=r"^item_[0-9a-f]{16}$")
    choice: Literal["left", "right", "tie", "skip"]
    media_status: Literal["ok", "missing", "damaged"] = "ok"
    dimensions: dict[str, int] = Field(default_factory=dict)

    @field_validator("dimensions")
    @classmethod
    def _bounded_dimensions(cls, dimensions: dict[str, int]) -> dict[str, int]:
        if len(dimensions) > 20:
            raise ValueError("too many rating dimensions")
        if any(not 1 <= score <= 5 for score in dimensions.values()):
            raise ValueError("dimension ratings must be between 1 and 5")
        return dimensions


@dataclass(frozen=True)
class ExportedReviewPackage:
    reviewer_packet: dict[str, Any]
    answer_key: dict[str, Any]
    ratings_template: dict[str, Any]


def build_review_package(
    manifest: FrozenReviewManifest,
    *,
    randomization_seed: str,
) -> ExportedReviewPackage:
    """Create a deterministic A/B package without model, variant or revision labels."""

    manifest_hash = _digest(manifest.model_dump(mode="json"))
    review_id = f"review_{_digest({'manifest': manifest_hash, 'seed': randomization_seed})[:16]}"
    public_items: list[dict[str, Any]] = []
    private_items: list[dict[str, Any]] = []
    template_items: list[dict[str, Any]] = []
    for scenario in manifest.scenarios:
        item_id = f"item_{_digest({'review': review_id, 'scenario': scenario.scenario_id})[:16]}"
        candidate_side = (
            "left"
            if int(
                _digest(
                    {
                        "seed": randomization_seed,
                        "scenario": scenario.scenario_id,
                    }
                )[:8],
                16,
            )
            % 2
            == 0
            else "right"
        )
        left = scenario.candidate if candidate_side == "left" else scenario.baseline
        right = scenario.baseline if candidate_side == "left" else scenario.candidate
        left_public, left_media = _anonymize_variant(left, item_id=item_id, side="left")
        right_public, right_media = _anonymize_variant(
            right, item_id=item_id, side="right"
        )
        public_items.append(
            {
                "item_id": item_id,
                "cluster_id": f"scenario_{_digest(scenario.scenario_id)[:12]}",
                "slice": scenario.slice,
                "context": scenario.context,
                "question": "哪一个更像真人正在狼人杀现场自然接话？",
                "left": left_public,
                "right": right_public,
            }
        )
        private_items.append(
            {
                "item_id": item_id,
                "scenario_id": scenario.scenario_id,
                "slice": scenario.slice,
                "candidate_side": candidate_side,
                "media_sources": [*left_media, *right_media],
            }
        )
        template_items.append(
            {
                "item_id": item_id,
                "choice": "left|right|tie|skip",
                "media_status": "ok|missing|damaged",
                "dimensions": {
                    "responsiveness": "1-5",
                    "spoken_naturalness": "1-5",
                    "persona_distinctiveness": "1-5",
                    "emotion_fit": "1-5",
                    "relationship_continuity": "1-5",
                },
            }
        )
    return ExportedReviewPackage(
        reviewer_packet={
            "schema_version": 1,
            "review_id": review_id,
            "items": public_items,
        },
        answer_key={
            "schema_version": 1,
            "review_id": review_id,
            "experiment_id": manifest.experiment_id,
            "manifest_sha256": manifest_hash,
            "items": private_items,
        },
        ratings_template={
            "schema_version": 1,
            "review_id": review_id,
            "reviewer_id": "replace-with-anonymous-reviewer-id",
            "ratings": template_items,
        },
    )


def write_review_package(
    package: ExportedReviewPackage,
    output_dir: Path,
    *,
    media_root: Path | None = None,
) -> None:
    media_copies: list[tuple[Path, Path]] = []
    for item in package.answer_key["items"]:
        for media in item.get("media_sources", []):
            source_ref = media["source_ref"]
            if "://" in source_ref:
                raise ValueError("review audio_ref must be a local file path")
            source = Path(source_ref)
            if not source.is_absolute():
                source = (media_root or Path.cwd()) / source
            if not source.is_file():
                raise FileNotFoundError(source)
            media_copies.append((source, output_dir / media["public_ref"]))
    output_dir.mkdir(parents=True, exist_ok=False)
    _write_json(output_dir / "reviewer_packet.json", package.reviewer_packet)
    private_dir = output_dir / "private"
    private_dir.mkdir(mode=0o700)
    _write_json(private_dir / "answer_key.json", package.answer_key)
    _write_json(output_dir / "ratings_template.json", package.ratings_template)
    for source, target in media_copies:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def analyze_review_ratings(
    *,
    answer_key: dict[str, Any],
    ratings: list[ReviewRating],
    bootstrap_samples: int = 10_000,
    bootstrap_seed: int = 0,
) -> dict[str, Any]:
    if not 1_000 <= bootstrap_samples <= 100_000:
        raise ValueError("bootstrap_samples must be between 1000 and 100000")
    key_items = answer_key.get("items")
    if not isinstance(key_items, list):
        raise ValueError("answer key items are invalid")
    item_keys: dict[str, dict[str, str]] = {}
    for item in key_items:
        if not isinstance(item, dict):
            raise ValueError("answer key item is invalid")
        item_id = item.get("item_id")
        scenario_id = item.get("scenario_id")
        slice_name = item.get("slice")
        candidate_side = item.get("candidate_side")
        if (
            not isinstance(item_id, str)
            or not isinstance(scenario_id, str)
            or not isinstance(slice_name, str)
            or candidate_side not in {"left", "right"}
        ):
            raise ValueError("answer key item fields are invalid")
        item_keys[item_id] = {
            "scenario_id": scenario_id,
            "slice": slice_name,
            "candidate_side": candidate_side,
        }

    seen: set[tuple[str, str]] = set()
    usable: list[tuple[str, str, float]] = []
    skipped = missing = damaged = 0
    reviewers: set[str] = set()
    for rating in ratings:
        key = item_keys.get(rating.item_id)
        if key is None:
            raise ValueError(f"rating references unknown item {rating.item_id}")
        duplicate_key = (rating.reviewer_id, rating.item_id)
        if duplicate_key in seen:
            raise ValueError("reviewer submitted the same item more than once")
        seen.add(duplicate_key)
        reviewers.add(rating.reviewer_id)
        if rating.media_status == "missing":
            missing += 1
        elif rating.media_status == "damaged":
            damaged += 1
        if rating.choice == "skip" or rating.media_status != "ok":
            skipped += 1
            continue
        score = (
            0.5
            if rating.choice == "tie"
            else 1.0
            if rating.choice == key["candidate_side"]
            else 0.0
        )
        usable.append((key["scenario_id"], key["slice"], score))

    clusters: dict[str, list[float]] = defaultdict(list)
    slices: dict[str, list[float]] = defaultdict(list)
    for scenario_id, slice_name, score in usable:
        clusters[scenario_id].append(score)
        slices[slice_name].append(score)
    cluster_scores = [sum(values) / len(values) for values in clusters.values()]
    point = _mean(cluster_scores)
    lower, upper = _cluster_bootstrap_interval(
        cluster_scores,
        samples=bootstrap_samples,
        seed=bootstrap_seed,
    )
    total = len(ratings)
    slice_results = {
        name: {"judgments": len(values), "candidate_preference": _mean(values)}
        for name, values in sorted(slices.items())
    }
    minimum_reviewers_per_item = min(
        (
            len(
                {
                    rating.reviewer_id
                    for rating in ratings
                    if rating.item_id == item_id
                    and rating.choice != "skip"
                    and rating.media_status == "ok"
                }
            )
            for item_id in item_keys
        ),
        default=0,
    )
    return {
        "schema_version": 1,
        "review_id": answer_key.get("review_id"),
        "experiment_id": answer_key.get("experiment_id"),
        "cluster_unit": "scenario_id",
        "judgments_total": total,
        "judgments_usable": len(usable),
        "reviewer_count": len(reviewers),
        "scenario_count": len(clusters),
        "minimum_reviewers_per_item": minimum_reviewers_per_item,
        "skipped_count": skipped,
        "missing_media_count": missing,
        "damaged_media_count": damaged,
        "missing_or_damaged_rate": (missing + damaged) / total if total else None,
        "candidate_preference": point,
        "confidence_interval_95": {"lower": lower, "upper": upper},
        "slices": slice_results,
        "gates": {
            "point_at_least_60_percent": point is not None and point >= 0.6,
            "ci_lower_above_50_percent": lower is not None and lower > 0.5,
            "every_slice_at_least_50_percent": bool(slice_results)
            and all(
                result["candidate_preference"] is not None
                and result["candidate_preference"] >= 0.5
                for result in slice_results.values()
            ),
            "at_least_three_reviewers_per_item": minimum_reviewers_per_item >= 3,
        },
    }


def load_manifest(path: Path) -> FrozenReviewManifest:
    return FrozenReviewManifest.model_validate(_load_json(path))


def load_ratings(path: Path) -> list[ReviewRating]:
    value = _load_json(path)
    if not isinstance(value, dict) or not isinstance(value.get("ratings"), list):
        raise ValueError("ratings file must contain a ratings list")
    reviewer_id = value.get("reviewer_id")
    normalized: list[ReviewRating] = []
    for item in value["ratings"]:
        if not isinstance(item, dict):
            raise ValueError("rating entry is invalid")
        payload = dict(item)
        payload.setdefault("reviewer_id", reviewer_id)
        normalized.append(ReviewRating.model_validate(payload))
    return normalized


def _cluster_bootstrap_interval(
    cluster_scores: list[float],
    *,
    samples: int,
    seed: int,
) -> tuple[float | None, float | None]:
    if not cluster_scores:
        return None, None
    rng = random.Random(seed)
    size = len(cluster_scores)
    draws = sorted(
        sum(rng.choice(cluster_scores) for _ in range(size)) / size
        for _ in range(samples)
    )
    return draws[math.floor(0.025 * (samples - 1))], draws[
        math.ceil(0.975 * (samples - 1))
    ]


def _anonymize_variant(
    variant: ReviewVariant,
    *,
    item_id: str,
    side: Literal["left", "right"],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    timeline: list[dict[str, Any]] = []
    media_sources: list[dict[str, str]] = []
    for index, entry in enumerate(variant.timeline):
        public_entry = entry.model_dump(mode="json")
        if entry.audio_ref:
            suffix = Path(entry.audio_ref).suffix.lower()
            if not suffix or len(suffix) > 10:
                suffix = ".audio"
            public_ref = f"media/{item_id}/{side}-{index}{suffix}"
            public_entry["audio_ref"] = public_ref
            media_sources.append(
                {"public_ref": public_ref, "source_ref": entry.audio_ref}
            )
        timeline.append(public_entry)
    return {"timeline": timeline}, media_sources


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _digest(value: Any) -> str:
    raw = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
