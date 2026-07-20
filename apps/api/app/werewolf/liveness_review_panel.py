from __future__ import annotations

import copy
import hashlib
import json
import random
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.werewolf.liveness_review import ReviewRating


PANEL_DIMENSIONS = (
    "responsiveness",
    "spoken_naturalness",
    "persona_distinctiveness",
    "emotion_fit",
    "relationship_continuity",
    "factual_grounding",
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PanelItemJudgment(_StrictModel):
    item_id: str = Field(pattern=r"^item_[0-9a-f]{16}$")
    choice: Literal["left", "right", "tie", "skip"]
    dimensions: dict[str, int]
    reason: str = Field(min_length=1, max_length=600)

    @field_validator("dimensions")
    @classmethod
    def _dimensions_contract(cls, value: dict[str, int]) -> dict[str, int]:
        if set(value) != set(PANEL_DIMENSIONS):
            raise ValueError("panel judgment dimensions do not match the contract")
        if any(type(score) is not int or not 1 <= score <= 5 for score in value.values()):
            raise ValueError("panel judgment dimensions must be integers from 1 to 5")
        return value


class PanelBatchJudgment(_StrictModel):
    ratings: list[PanelItemJudgment] = Field(min_length=1, max_length=5_000)


def panel_json_schema(*, expected_items: int) -> dict[str, Any]:
    if not 1 <= expected_items <= 5_000:
        raise ValueError("expected_items must be between 1 and 5000")
    score_properties = {
        name: {"type": "integer", "minimum": 1, "maximum": 5}
        for name in PANEL_DIMENSIONS
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["ratings"],
        "properties": {
            "ratings": {
                "type": "array",
                "minItems": expected_items,
                "maxItems": expected_items,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["item_id", "choice", "dimensions", "reason"],
                    "properties": {
                        "item_id": {
                            "type": "string",
                            "pattern": "^item_[0-9a-f]{16}$",
                        },
                        "choice": {
                            "type": "string",
                            "enum": ["left", "right", "tie", "skip"],
                        },
                        "dimensions": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": list(PANEL_DIMENSIONS),
                            "properties": score_properties,
                        },
                        "reason": {"type": "string", "minLength": 1, "maxLength": 600},
                    },
                },
            }
        },
    }


def build_panel_prompt(reviewer_packet: dict[str, Any]) -> str:
    items = _packet_items(reviewer_packet)
    compact_items = [
        {
            "item_id": item["item_id"],
            "slice": item.get("slice"),
            "context": item.get("context"),
            "question": item.get("question"),
            "left": item.get("left"),
            "right": item.get("right"),
        }
        for item in items
    ]
    return (
        "你是匿名狼人杀活人感盲评员。逐题比较同一公开情境下的左、右发言，"
        "选择更像真人正在桌边听完前文后自然接话的一侧。不要猜版本、模型或来源。\n"
        "本轮是文本行为校准，不包含音频，因此只评价文本可观察到的临场回应、口语自然、"
        "人设辨识、情绪适配、关系连续和事实落地。短不等于自然，长不等于充分；"
        "机械压缩、报告腔、复述上下文和装饰性口头禅都要扣分。若一侧编造、错引或违反公开情境，"
        "不能仅因语气鲜活而胜出。两侧实质相当选 tie，材料不足选 skip。\n"
        "dimensions 是你对获选一侧的六项 1-5 分；tie 时按两侧共同水平评分。"
        "reason 必须指出具体文本证据，不能只写结论。每个 item_id 恰好输出一次。\n"
        "输出必须是一个 JSON 对象且只含 ratings 数组。每项字段必须严格命名为 "
        "item_id、choice、dimensions、reason；choice 只能是 left/right/tie/skip；"
        "dimensions 必须且只能包含英文键 responsiveness、spoken_naturalness、"
        "persona_distinctiveness、emotion_fit、relationship_continuity、factual_grounding。"
        "不要把 choice 改名为 selected，不要输出顶层数组或 Markdown。\n"
        "评审题目："
        + json.dumps(compact_items, ensure_ascii=False, separators=(",", ":"))
    )


def swapped_packet(reviewer_packet: dict[str, Any]) -> dict[str, Any]:
    swapped = copy.deepcopy(reviewer_packet)
    for item in _packet_items(swapped):
        item["left"], item["right"] = item.get("right"), item.get("left")
    return swapped


def normalize_panel_batch(
    value: object,
    *,
    reviewer_id: str,
    expected_item_ids: set[str],
    sides_swapped: bool,
) -> tuple[list[ReviewRating], list[dict[str, Any]]]:
    batch = PanelBatchJudgment.model_validate(value)
    ids = [rating.item_id for rating in batch.ratings]
    if len(ids) != len(set(ids)) or set(ids) != expected_item_ids:
        raise ValueError("panel batch must contain every expected item exactly once")
    normalized: list[ReviewRating] = []
    evidence: list[dict[str, Any]] = []
    for item in batch.ratings:
        choice = item.choice
        if sides_swapped and choice in {"left", "right"}:
            choice = "right" if choice == "left" else "left"
        normalized.append(
            ReviewRating(
                reviewer_id=reviewer_id,
                item_id=item.item_id,
                choice=choice,
                dimensions=item.dimensions,
            )
        )
        evidence.append(
            {
                "reviewer_id": reviewer_id,
                "item_id": item.item_id,
                "presented_choice": item.choice,
                "normalized_choice": choice,
                "sides_swapped": sides_swapped,
                "dimensions": item.dimensions,
                "reason": item.reason,
            }
        )
    return normalized, evidence


def reconcile_orientation_ratings(
    first: list[ReviewRating],
    second: list[ReviewRating],
    *,
    reviewer_id: str,
) -> tuple[list[ReviewRating], list[dict[str, Any]]]:
    first_by_id = {rating.item_id: rating for rating in first}
    second_by_id = {rating.item_id: rating for rating in second}
    if set(first_by_id) != set(second_by_id):
        raise ValueError("orientation batches do not cover the same items")
    reconciled: list[ReviewRating] = []
    stability: list[dict[str, Any]] = []
    for item_id in sorted(first_by_id):
        left = first_by_id[item_id]
        right = second_by_id[item_id]
        stable = left.choice == right.choice
        choice = left.choice if stable else "tie"
        dimensions = {
            name: round((left.dimensions[name] + right.dimensions[name]) / 2)
            for name in PANEL_DIMENSIONS
        }
        reconciled.append(
            ReviewRating(
                reviewer_id=reviewer_id,
                item_id=item_id,
                choice=choice,
                dimensions=dimensions,
            )
        )
        stability.append(
            {
                "reviewer_id": reviewer_id,
                "item_id": item_id,
                "first_choice": left.choice,
                "swapped_choice": right.choice,
                "stable": stable,
                "final_choice": choice,
            }
        )
    return reconciled, stability


def random_user_sample(
    reviewer_packet: dict[str, Any],
    *,
    sample_size: int,
    seed: str,
) -> dict[str, Any]:
    items = _packet_items(reviewer_packet)
    if not 1 <= sample_size <= len(items):
        raise ValueError("sample_size must fit within reviewer packet")
    digest = hashlib.sha256(seed.encode()).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    selected = rng.sample(items, sample_size)
    return {
        "schema_version": 1,
        "review_id": reviewer_packet.get("review_id"),
        "sampling": {
            "method": "uniform_without_replacement",
            "seed_sha256": hashlib.sha256(seed.encode()).hexdigest(),
            "population_size": len(items),
            "sample_size": sample_size,
        },
        "reviewer_id": "user",
        "items": copy.deepcopy(selected),
    }


def _packet_items(packet: dict[str, Any]) -> list[dict[str, Any]]:
    items = packet.get("items")
    if not isinstance(items, list) or not items or any(not isinstance(item, dict) for item in items):
        raise ValueError("reviewer packet items are invalid")
    return items
