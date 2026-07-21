from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Final

from sqlalchemy.orm import Session

from app.models.rule_set import RuleSetRecord, RuleSetRevisionRecord
from app.rule_sets.snapshots import (
    compile_rule_set_config,
    resolve_rule_set_snapshot,
    rule_set_content_hash,
)
from app.rule_sets.types import CompiledRuleSet
from app.rule_sets.validation import normalize_rule_set_config
from app.werewolf.rules import get_rule_set, rule_set_snapshot


PUBLISHED_AT: Final = datetime(2026, 7, 12, tzinfo=UTC)

# Test-owned copy of migration 15's immutable official seeds. Production code must
# never import test fixtures, and tests deliberately do not import Alembic modules.
OFFICIAL_RULE_SET_SEEDS: Final = (
    {
        "id": "classic_8",
        "revision_id": "e9fa678e-9b18-5079-91d2-f74835364fb6",
        "content_hash": "00095728147a022c48eab88faf21a14567ad0afa13ab9418306e84ff85b10131",
        "display_order": 1,
        "is_default": True,
        "role_summary": "2 狼人 / 1 预言家 / 1 守卫 / 4 村民",
        "config": {
            "name": "经典 8 人局",
            "description": "包含狼人、预言家、守卫与村民的官方标准局。",
            "complexity": "标准",
            "estimated_duration": "中",
            "rule_tags": ["无警长", "顺序发言", "标准"],
            "role_counts": {
                "werewolf": 2,
                "villager": 4,
                "seer": 1,
                "guard": 1,
                "witch": 0,
                "hunter": 0,
                "idiot": 0,
            },
            "win_condition": "wolves_gte_others",
            "sheriff_enabled": False,
            "sheriff_vote_weight": 1.0,
            "speech_policy": "sequential",
            "werewolf_self_explosion_enabled": False,
            "sheriff_badge_bomb_policy": "none",
        },
    },
    {
        "id": "starter_6",
        "revision_id": "b607e17e-b86f-5eb0-9dc2-b8df09aa71ab",
        "content_hash": "f2c52827ff3eea2725fbf2f1a01436f69c7e6465a64dec9a92bd7a07a9368f4c",
        "display_order": 2,
        "is_default": False,
        "role_summary": "1 狼人 / 1 预言家 / 1 守卫 / 3 村民",
        "config": {
            "name": "新手 6 人快局",
            # ASCII comma is authoritative. The obsolete fullwidth-comma variant
            # intentionally has a different hash and is not a compatible seed.
            "description": "更短的官方入门局,适合快速观察模型策略。",
            "complexity": "入门",
            "estimated_duration": "短",
            "rule_tags": ["无警长", "顺序发言", "新手"],
            "role_counts": {
                "werewolf": 1,
                "villager": 3,
                "seer": 1,
                "guard": 1,
                "witch": 0,
                "hunter": 0,
                "idiot": 0,
            },
            "win_condition": "wolves_gte_others",
            "sheriff_enabled": False,
            "sheriff_vote_weight": 1.0,
            "speech_policy": "sequential",
            "werewolf_self_explosion_enabled": False,
            "sheriff_badge_bomb_policy": "none",
        },
    },
    {
        "id": "social_8",
        "revision_id": "2b4a993f-e4e6-5312-b11d-92874851a70a",
        "content_hash": "21e1bd2bb495e4479a346724c85a9722477f840afc2c99c389558a52427a0fbc",
        "display_order": 3,
        "is_default": False,
        "role_summary": "2 狼人 / 6 村民",
        "config": {
            "name": "社交 8 人局",
            "description": "仅保留狼人夜晚行动的官方心理博弈局。",
            "complexity": "心理",
            "estimated_duration": "中",
            "rule_tags": ["无警长", "顺序发言", "心理"],
            "role_counts": {
                "werewolf": 2,
                "villager": 6,
                "seer": 0,
                "guard": 0,
                "witch": 0,
                "hunter": 0,
                "idiot": 0,
            },
            "win_condition": "wolves_gte_others",
            "sheriff_enabled": False,
            "sheriff_vote_weight": 1.0,
            "speech_policy": "sequential",
            "werewolf_self_explosion_enabled": False,
            "sheriff_badge_bomb_policy": "none",
        },
    },
    {
        "id": "classic_12_seer_witch_hunter_idiot",
        "revision_id": "0489f6ac-16fd-5323-96ce-ee256c98cf32",
        "content_hash": "bcae38e48a7791fa0f7ae236c90f1852056938ea60f5447532e5d879260d6da2",
        "display_order": 4,
        "is_default": False,
        "role_summary": "4 狼人 / 1 预言家 / 1 女巫 / 1 猎人 / 1 白痴 / 4 村民",
        "config": {
            "name": "12 人预女猎白局",
            "description": "4 狼、预言家、女巫、猎人、白痴与 4 民的标准屠边局。",
            "complexity": "进阶",
            "estimated_duration": "长",
            "rule_tags": ["有警长", "警徽 1.5 票", "屠边", "预女猎白"],
            "role_counts": {
                "werewolf": 4,
                "villager": 4,
                "seer": 1,
                "guard": 0,
                "witch": 1,
                "hunter": 1,
                "idiot": 1,
            },
            "win_condition": "slaughter_side",
            "sheriff_enabled": True,
            "sheriff_vote_weight": 1.5,
            "speech_policy": "sheriff_directed",
            "werewolf_self_explosion_enabled": True,
            "sheriff_badge_bomb_policy": "double",
        },
    },
)


def seed_official_rule_sets(db: Session) -> None:
    for seed in OFFICIAL_RULE_SET_SEEDS:
        config = normalize_rule_set_config(seed["config"])
        assert rule_set_content_hash(config) == seed["content_hash"]
        revision_id = str(seed["revision_id"])
        rule_set_id = str(seed["id"])
        db.add(
            RuleSetRecord(
                id=rule_set_id,
                status="published",
                current_published_revision_id=revision_id,
                draft_revision_id=None,
                is_default=bool(seed["is_default"]),
                display_order=int(seed["display_order"]),
                lock_version=1,
                created_at=PUBLISHED_AT,
                updated_at=PUBLISHED_AT,
            )
        )
        db.add(
            RuleSetRevisionRecord(
                id=revision_id,
                rule_set_id=rule_set_id,
                revision_no=1,
                state="published",
                schema_version=1,
                content_hash=str(seed["content_hash"]),
                lock_version=1,
                name=config.name,
                description=config.description,
                player_count=config.player_count,
                role_summary=str(seed["role_summary"]),
                complexity=config.complexity,
                estimated_duration=config.estimated_duration,
                config=seed["config"],
                published_at=PUBLISHED_AT,
                created_at=PUBLISHED_AT,
                updated_at=PUBLISHED_AT,
            )
        )
    db.flush()


def managed_official_compiled_rule_set(rule_set_id: str = "classic_8") -> CompiledRuleSet:
    seed = next(seed for seed in OFFICIAL_RULE_SET_SEEDS if seed["id"] == rule_set_id)
    config = normalize_rule_set_config(seed["config"])
    compiled = compile_rule_set_config(
        rule_set_id,
        config,
        revision_id=str(seed["revision_id"]),
        revision_no=1,
    )
    assert compiled.content_hash == seed["content_hash"]
    return compiled


def legacy_official_compiled_rule_set(rule_set_id: str = "classic_8") -> CompiledRuleSet:
    return resolve_rule_set_snapshot(rule_set_snapshot(get_rule_set(rule_set_id)))


def complete_resume_checkpoint(
    session_id: str,
    compiled: CompiledRuleSet,
    *,
    checkpoint_schema_version: int = 2,
    include_rule_metadata: bool | None = None,
) -> dict[str, object]:
    if include_rule_metadata is None:
        include_rule_metadata = checkpoint_schema_version >= 2
    run_params: dict[str, object] = {
        "villager_model": "deepseek-chat",
        "werewolf_model": "deepseek-chat",
        "seed": 7,
        "max_rounds": 8,
        "rule_set_id": compiled.rule_set.id,
        "player_configs": [],
    }
    if include_rule_metadata:
        run_params.update(
            {
                "revision_id": compiled.revision_id,
                "revision_no": compiled.revision_no,
                "content_hash": compiled.content_hash,
                "rule_set_snapshot": copy.deepcopy(compiled.snapshot),
            }
        )
    checkpoint: dict[str, object] = {
        "schema_version": checkpoint_schema_version,
        "session_id": session_id,
        "state_at_round_start": {
            "session_id": session_id,
            "players": [],
            "rounds": [],
            "winner": "",
            "error_message": "",
            "rule_set": copy.deepcopy(compiled.snapshot),
        },
        "logs_before_round": [],
        "run_params": run_params,
        "round_number": 1,
        "active_players": [],
        "rng_state": None,
        "cached_model_responses": [],
        "failed_request": None,
        "last_error": None,
    }
    if checkpoint_schema_version >= 3:
        checkpoint["private_runtime"] = {
            "actor_minds_at_round_start": {},
            "actor_minds": {},
        }
        checkpoint["generation_runtime"] = {
            "speech_turn_receipts": {},
        }
    return checkpoint
