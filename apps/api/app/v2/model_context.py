from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
import re
from typing import Any

from app.v2.ability_runtime import normalize_role_key, normalize_team_key


MODEL_PROMPT_SCHEMA_VERSION = 2
_RECENT_STATEMENT_LIMIT = 3
_RECENT_STATEMENT_CHAR_BUDGET = 5_000
_PUBLIC_JUDGE_FACT_LIMIT = 20
_OLDER_CLAIM_LIMIT = 18
_OLDER_CLAIM_CHAR_BUDGET = 5_000
_CLAIMS_PER_STATEMENT_LIMIT = 4
_CLAIM_CHAR_LIMIT = 180
_PERSONA_TEXT_LIMIT = 600


@dataclass(frozen=True)
class V2ModelPlayerReference:
    player_id: str
    seat: int
    display_name: str

    @property
    def ref(self) -> str:
        return f"seat_{self.seat}"

    @property
    def label(self) -> str:
        return f"{self.seat}号"


def project_model_action_context(
    context: dict[str, Any],
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> dict[str, Any]:
    if not players:
        return dict(context)
    source = _project_value(context, players=players)
    private_facts = source.pop("private_authoritative_facts", None)
    private_facts = private_facts if isinstance(private_facts, list) else []
    public_history = context.get("public_history")
    if isinstance(public_history, list) or isinstance(public_history, tuple):
        facts, statements, role_confirmations, vote_snapshots = _project_public_history(
            public_history,
            players=players,
        )
    else:
        facts = []
        statements = []
        role_confirmations = []
        vote_snapshots = []

    recent_statements, older_claims = _compact_public_statements(statements)
    hard_rules = _model_hard_rules(source.get("public_rule_contract"))
    return {
        "prompt_schema_version": MODEL_PROMPT_SCHEMA_VERSION,
        "task": _model_task(source),
        "hard_rules": hard_rules,
        "self": _model_self(
            source,
            private_facts=private_facts,
            hard_rules=hard_rules,
        ),
        "public_state": _model_public_state(
            source,
            facts=facts,
            role_confirmations=role_confirmations,
            vote_snapshots=vote_snapshots,
        ),
        "history": {
            "recent_statements": recent_statements,
            "older_claims": older_claims,
        },
        "persona": _compact_persona(source.get("actor_profile")),
        "candidates": (
            source.get("candidates") if isinstance(source.get("candidates"), list) else []
        ),
        "output_contract": (
            source.get("output_contract") if isinstance(source.get("output_contract"), dict) else {}
        ),
        "player_reference_rule": {
            "reference_format": "seat_N",
            "spoken_format": "N号",
            "names_available": False,
        },
    }


def model_prompt_metadata(context: dict[str, Any]) -> dict[str, Any]:
    history = context.get("history")
    history = history if isinstance(history, dict) else {}
    recent = history.get("recent_statements")
    older = history.get("older_claims")
    return {
        "prompt_schema_version": context.get("prompt_schema_version"),
        "serialized_char_count": len(
            json.dumps(context, ensure_ascii=False, separators=(",", ":"))
        ),
        "recent_statement_count": len(recent) if isinstance(recent, list) else 0,
        "older_claim_count": len(older) if isinstance(older, list) else 0,
    }


def _model_task(source: dict[str, Any]) -> dict[str, Any]:
    task: dict[str, Any] = {
        "action_type": source.get("action_type"),
        "objective": source.get("objective"),
        "phase_id": source.get("phase_id"),
        "round_no": source.get("round_no"),
    }
    for field in (
        "night_no",
        "speech_round",
        "speech_order",
        "vote_round",
        "pk_candidate_ids",
        "original_candidate_ids",
        "original_off_sheriff_voter_ids",
        "public_stage",
        "ability_id",
        "decision_rules",
    ):
        if field in source:
            task[field] = source[field]
    current_action_effect = source.get("current_action_effect")
    if not isinstance(current_action_effect, dict):
        current_action_effect = _default_current_action_effect(source)
    task["mechanical_effect"] = _without_explanations(current_action_effect)
    return {key: value for key, value in task.items() if value is not None}


def _model_hard_rules(value: Any) -> dict[str, Any]:
    contract = value if isinstance(value, dict) else {}
    roles = contract.get("roles")
    roles = roles if isinstance(roles, list) else []
    configured_werewolf_count = contract.get("werewolf_count")
    if isinstance(configured_werewolf_count, int) and not isinstance(
        configured_werewolf_count,
        bool,
    ):
        werewolf_count: int | None = configured_werewolf_count
    elif roles:
        werewolf_count = sum(
            int(item.get("count") or 0)
            for item in roles
            if isinstance(item, dict) and item.get("role_key") == "werewolf"
        )
    else:
        werewolf_count = None
    night_rules = contract.get("night_action_rules")
    night_rules = night_rules if isinstance(night_rules, dict) else {}
    ability_rules: dict[str, Any] = {}
    for ability_id, raw_rule in night_rules.items():
        if not isinstance(ability_id, str) or not isinstance(raw_rule, dict):
            continue
        rule = _without_explanations(raw_rule)
        if ability_id == "werewolf_attack":
            rule.pop("actor_scope", None)
            rule.pop("single_werewolf_resolution", None)
            if werewolf_count == 1:
                rule["coordination"] = "solo"
                rule.pop("team_resolution", None)
                rule.pop("can_target_werewolf_teammates", None)
            elif isinstance(werewolf_count, int) and werewolf_count > 1:
                rule["coordination"] = "team"
        ability_rules[ability_id] = rule
    result = {
        "rule_id": contract.get("rule_id"),
        "rule_version": contract.get("rule_version"),
        "player_count": contract.get("player_count"),
        "roles": [
            {
                key: item.get(key)
                for key in ("role_key", "role_label", "count", "team")
                if item.get(key) is not None
            }
            for item in roles
            if isinstance(item, dict)
        ],
        "werewolf_count": werewolf_count,
        "max_rounds": contract.get("max_rounds"),
        "win_condition": contract.get("win_condition"),
        "reveal_policy": contract.get("reveal_policy"),
        "role_reveal_rule": contract.get("role_reveal_rule"),
        "sheriff": {
            "enabled": bool(contract.get("sheriff_enabled")),
            "vote_weight": contract.get("sheriff_vote_weight"),
        },
        "speech": {
            "policy": contract.get("speech_policy"),
            "rounds": contract.get("speech_rounds"),
            "exile_last_words_enabled": bool(contract.get("exile_last_words_enabled")),
        },
        "werewolf_self_explosion_enabled": bool(contract.get("werewolf_self_explosion_enabled")),
        "ability_rules": ability_rules,
    }
    return {key: item for key, item in result.items() if item is not None}


def _model_self(
    source: dict[str, Any],
    *,
    private_facts: list[Any],
    hard_rules: dict[str, Any],
) -> dict[str, Any]:
    identity = source.get("self_identity")
    identity = identity if isinstance(identity, dict) else {}
    role_key = identity.get("role_key")
    self_ref = identity.get("player_id")
    visible_private_facts = (
        [
            fact
            for fact in private_facts
            if not isinstance(fact, dict)
            or fact.get("fact_type")
            not in {"werewolf_teammates", "living_werewolf_teammates"}
        ]
        if role_key == "werewolf"
        else private_facts
    )
    result: dict[str, Any] = {
        "identity": {
            key: identity.get(key)
            for key in ("player_id", "seat", "role_key", "team")
            if identity.get(key) is not None
        },
        "private_judge_facts": visible_private_facts,
        "role_capabilities": _without_explanations(source.get("role_capabilities")),
        "ability_runtime_state": _without_explanations(source.get("ability_runtime_state")),
        "public_office_capabilities": _without_explanations(
            source.get("public_office_capabilities")
        ),
        "state_restrictions": _without_explanations(source.get("current_state_restrictions")),
    }
    if role_key == "werewolf":
        living_teammates = _living_werewolf_teammates(
            private_facts,
            self_ref=self_ref if isinstance(self_ref, str) else None,
            werewolf_count=hard_rules.get("werewolf_count"),
        )
        result["werewolf_coordination"] = (
            {"mode": "solo"}
            if hard_rules.get("werewolf_count") == 1
            else {
                "mode": "team",
                "living_teammate_refs": living_teammates or [],
            }
        )
    return result


def _living_werewolf_teammates(
    private_facts: list[Any],
    *,
    self_ref: str | None,
    werewolf_count: Any,
) -> list[str] | None:
    if werewolf_count == 1:
        return []
    for fact in reversed(private_facts):
        if not isinstance(fact, dict):
            continue
        if fact.get("fact_type") not in {
            "werewolf_teammates",
            "living_werewolf_teammates",
        }:
            continue
        payload = fact.get("payload")
        if not isinstance(payload, list):
            continue
        return [item for item in payload if isinstance(item, str) and item != self_ref]
    return None


def _model_public_state(
    source: dict[str, Any],
    *,
    facts: list[dict[str, Any]],
    role_confirmations: list[dict[str, Any]],
    vote_snapshots: list[dict[str, Any]],
) -> dict[str, Any]:
    public_match_state = source.get("public_match_state")
    public_match_state = dict(public_match_state) if isinstance(public_match_state, dict) else {}
    sheriff_player_id = source.get("sheriff_player_id")
    if sheriff_player_id is not None:
        public_match_state["sheriff_player_id"] = sheriff_player_id
    office = source.get("public_office_capabilities")
    if isinstance(office, dict):
        badge_state = office.get("sheriff_badge_state")
        if badge_state is not None:
            public_match_state["sheriff_badge_state"] = badge_state
    if facts:
        public_match_state["judge_facts"] = facts[-_PUBLIC_JUDGE_FACT_LIMIT:]
    if role_confirmations:
        public_match_state["role_confirmations"] = role_confirmations
    if vote_snapshots:
        public_match_state["latest_vote_snapshot"] = vote_snapshots[-1]
    return public_match_state


def _compact_persona(value: Any) -> dict[str, Any]:
    profile = value if isinstance(value, dict) else {}
    personality = profile.get("personality")
    if isinstance(personality, str) and len(personality) > _PERSONA_TEXT_LIMIT:
        personality = personality[:_PERSONA_TEXT_LIMIT].rstrip() + "…"
    catchphrases = profile.get("catchphrases")
    return {
        key: item
        for key, item in {
            "personality": personality,
            "strategy_profile": profile.get("strategy_profile"),
            "catchphrases": (catchphrases[:3] if isinstance(catchphrases, list) else None),
            "delivery_mood": profile.get("base_delivery_mood"),
            "delivery_intensity": profile.get("base_delivery_intensity"),
            "delivery_pace": profile.get("base_delivery_pace"),
            "delivery_instruction": profile.get("base_delivery_instruction"),
        }.items()
        if item not in (None, [], "")
    }


def _without_explanations(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_explanations(item)
            for key, item in value.items()
            if key not in {"source", "instruction"}
        }
    if isinstance(value, list):
        return [_without_explanations(item) for item in value]
    return value


def sanitize_model_speech(
    speech: str,
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> str:
    return _project_text(speech, players=players)


def resolve_model_target(
    target: str | None,
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> str | None:
    if target is None:
        return None
    return {player.ref: player.player_id for player in players}.get(target)


def _default_current_action_effect(context: dict[str, Any]) -> dict[str, Any]:
    output_contract = context.get("output_contract")
    output_contract = output_contract if isinstance(output_contract, dict) else {}
    target_policy = output_contract.get("target_policy")
    target_policy = target_policy if isinstance(target_policy, dict) else {}
    return {
        "action_type": context.get("action_type"),
        "source": "current_action_contract",
        "target_mode": target_policy.get("mode", "none"),
        "speech_has_gameplay_effect": False,
        "instruction": (
            "该字段只描述本次动作契约已经确定的机械边界；speech 可以表达策略、"
            "判断或伪装，但不会自行产生死亡、技能、投票或其他游戏效果。"
        ),
    }


def build_public_rule_contract(
    *,
    rule: dict[str, Any],
    max_rounds: int,
) -> dict[str, Any]:
    raw_roles = rule.get("roles")
    roles: list[dict[str, Any]] = []
    if isinstance(raw_roles, list):
        for raw_role in raw_roles:
            if not isinstance(raw_role, dict):
                continue
            role_label = raw_role.get("role")
            count = raw_role.get("count")
            if (
                not isinstance(role_label, str)
                or not role_label.strip()
                or not isinstance(count, int)
                or isinstance(count, bool)
                or count < 1
            ):
                continue
            role_key = normalize_role_key(role_label)
            roles.append(
                {
                    "role_key": role_key,
                    "role_label": role_label.strip(),
                    "count": count,
                    "team": normalize_team_key(raw_role.get("team"), role_key=role_key),
                }
            )

    player_count = rule.get("player_count")
    if not isinstance(player_count, int) or isinstance(player_count, bool):
        player_count = sum(item["count"] for item in roles)
    werewolf_count = sum(item["count"] for item in roles if item["role_key"] == "werewolf")
    sheriff_enabled = bool(rule.get("sheriff_enabled"))
    role_composition = "、".join(f"{item['count']}名{item['role_label']}" for item in roles)
    night_action_rules = _night_action_rules(
        role_keys={item["role_key"] for item in roles},
        werewolf_count=werewolf_count,
        ability_policies=rule.get("ability_policies"),
    )
    reveal_policy = str(rule.get("reveal_policy") or "hidden")
    return {
        "schema_version": 1,
        "source": "frozen_rule_snapshot",
        "rule_id": rule.get("id"),
        "rule_name": rule.get("name"),
        "rule_version": rule.get("version"),
        "player_count": player_count,
        "roles": roles,
        "role_composition": (
            f"本局共有{player_count}名玩家：{role_composition}。"
            if role_composition
            else f"本局共有{player_count}名玩家。"
        ),
        "werewolf_count": werewolf_count,
        "night_action_rules": night_action_rules,
        "max_rounds": max_rounds,
        "win_condition": rule.get("win_condition") or "wolves_gte_others",
        "reveal_policy": reveal_policy,
        "role_reveal_rule": (
            "玩家死亡或被放逐后，法官不会公开其身份或阵营；"
            "出局方式、发言和投票结果均不能作为法官已证实其身份的依据。"
            if reveal_policy == "hidden"
            else "玩家死亡或被放逐后，法官会按照本局公开身份规则播报其身份。"
        ),
        "sheriff_enabled": sheriff_enabled,
        "sheriff_vote_weight": (
            float(rule.get("sheriff_vote_weight") or 1) if sheriff_enabled else None
        ),
        "sheriff_rule": (
            "本局启用警长系统。"
            if sheriff_enabled
            else "本局不启用警长系统，不存在上警、警徽或警徽流机制。"
        ),
        "speech_policy": rule.get("speech_policy") or "sequential",
        "speech_rounds": int(rule.get("speech_rounds") or 1),
        "werewolf_self_explosion_enabled": bool(rule.get("werewolf_self_explosion_enabled")),
        "exile_last_words_enabled": bool(rule.get("exile_last_words_enabled")),
    }


def build_public_match_state(
    *,
    round_no: int,
    players: Iterable[Any],
) -> dict[str, Any]:
    player_list = tuple(players)
    alive_player_ids = [str(player.player_id) for player in player_list if bool(player.alive)]
    eliminated_player_ids = [
        str(player.player_id) for player in player_list if not bool(player.alive)
    ]
    return {
        "round_no": round_no,
        "alive_player_count": len(alive_player_ids),
        "alive_player_ids": alive_player_ids,
        "eliminated_player_count": len(eliminated_player_ids),
        "eliminated_player_ids": eliminated_player_ids,
        "identity_information_included": False,
    }


def build_actor_information(
    *,
    player_id: str,
    seat: int,
    role_key: str,
    team: str,
    persona: dict[str, Any],
    alive: bool,
    sheriff_player_id: str | None,
    sheriff_badge_state: str,
    rule: dict[str, Any],
    player_state: dict[str, Any] | None = None,
    private_facts: Iterable[dict[str, Any]] | None = None,
    current_action_type: str | None = None,
    current_action_knowledge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_role = normalize_role_key(role_key)
    state = player_state if isinstance(player_state, dict) else {}
    role_capabilities = _role_capabilities(
        role_key=normalized_role,
        rule=rule,
    )
    is_sheriff = (
        bool(rule.get("sheriff_enabled"))
        and sheriff_badge_state == "held"
        and sheriff_player_id == player_id
    )
    return {
        "self_identity": {
            "player_id": player_id,
            "seat": seat,
            "role_key": normalized_role,
            "team": normalize_team_key(team, role_key=normalized_role),
            "source": "private_role_assignment",
            "authoritative": True,
        },
        "role_capabilities": role_capabilities,
        "ability_runtime_state": _ability_runtime_state(
            abilities=role_capabilities["abilities"],
            alive=alive,
            player_state=state,
            private_facts=private_facts,
            current_action_type=current_action_type,
            current_action_knowledge=current_action_knowledge,
        ),
        "public_office_capabilities": _public_office_capabilities(
            is_sheriff=is_sheriff,
            sheriff_badge_state=sheriff_badge_state,
            rule=rule,
        ),
        "current_state_restrictions": {
            "alive": alive,
            "can_vote": bool(state.get("can_vote", True)) if alive else False,
            "idiot_revealed": bool(state.get("idiot_revealed")),
            "sheriff_badge_state": sheriff_badge_state,
            "instruction": (
                "角色能力与公开职位职权相加后，再受当前状态和本次动作候选范围限制；"
                "公开伪装或谎报身份不受此字段禁止。"
            ),
        },
        "actor_profile": persona,
    }


def _role_capabilities(
    *,
    role_key: str,
    rule: dict[str, Any],
) -> dict[str, Any]:
    werewolf_count = _werewolf_count_from_rule(rule)
    capabilities: dict[str, list[dict[str, Any]]] = {
        "villager": [],
        "werewolf": [
            {
                "ability_id": "werewolf.attack",
                "timing": "night",
                "description": (
                    "你是本局唯一狼人，独自选择一名存活的非狼人玩家作为袭击目标。"
                    if werewolf_count == 1
                    else (
                        "与存活狼人队友共同选择一名存活的非狼人玩家作为袭击目标。"
                        if werewolf_count > 1
                        else "选择一名存活的非狼人玩家作为袭击目标。"
                    )
                ),
            }
        ],
        "seer": [
            {
                "ability_id": "seer.investigate",
                "timing": "night",
                "description": "选择一名其他存活玩家，法官私下返回其狼人或好人阵营结果。",
            }
        ],
        "guard": [
            {
                "ability_id": "guard.protect",
                "timing": "night",
                "description": "按照本局守卫规则选择一名存活玩家守护。",
            }
        ],
        "witch": [
            {
                "ability_id": "witch.heal",
                "timing": "night",
                "description": "在解药仍可用且符合本局规则时决定是否救治狼人袭击目标。",
            },
            {
                "ability_id": "witch.poison",
                "timing": "night",
                "description": "在毒药仍可用且符合本局规则时决定是否毒杀合法目标。",
            },
        ],
        "hunter": [
            {
                "ability_id": "hunter.death_shot",
                "timing": "death_reaction",
                "description": "死亡且符合本局猎人规则时，可以选择一名存活玩家开枪或放弃。",
            }
        ],
        "idiot": [
            {
                "ability_id": "idiot.exile_immunity",
                "timing": "first_exile",
                "description": "第一次被投票放逐时公开白痴身份并免于出局，之后失去投票权。",
            }
        ],
    }
    abilities = list(capabilities.get(role_key, []))
    if role_key == "werewolf" and bool(rule.get("werewolf_self_explosion_enabled")):
        abilities.append(
            {
                "ability_id": "werewolf.self_explosion",
                "timing": "eligible_day_windows",
                "description": (
                    "在本局允许的白天窗口决定是否自爆；执行后只有本人立即出局并公开确认"
                    "狼人身份，不会选择、杀死或带走其他玩家。"
                ),
            }
        )
    return {
        "source": "private_role_assignment_and_frozen_rules",
        "role_key": role_key,
        "abilities": abilities,
        "no_exclusive_active_ability": not abilities,
        "instruction": "这些是真实角色能力；获得或失去警长职位都不会改变此列表。",
    }


def _werewolf_count_from_rule(rule: dict[str, Any]) -> int:
    roles = rule.get("roles")
    if not isinstance(roles, list):
        return 0
    return sum(
        int(item.get("count") or 0)
        for item in roles
        if isinstance(item, dict) and normalize_role_key(item.get("role")) == "werewolf"
    )


def _ability_runtime_state(
    *,
    abilities: Iterable[dict[str, Any]],
    alive: bool,
    player_state: dict[str, Any],
    private_facts: Iterable[dict[str, Any]] | None,
    current_action_type: str | None,
    current_action_knowledge: dict[str, Any] | None,
) -> dict[str, Any]:
    facts = tuple(private_facts or ())
    knowledge = current_action_knowledge if isinstance(current_action_knowledge, dict) else {}
    current_ability_id = _ability_id_for_action(current_action_type)
    latest_commits: dict[str, dict[str, Any]] = {}
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        if fact.get("fact_type") != "private_ability_action_committed":
            continue
        payload = fact.get("payload")
        if not isinstance(payload, dict):
            continue
        ability_id = payload.get("ability_id")
        if isinstance(ability_id, str):
            latest_commits[ability_id] = payload

    limited_uses = {
        "witch.heal": ("heal_remaining", "heal_used"),
        "witch.poison": ("poison_remaining", "poison_used"),
        "hunter.death_shot": (None, "shot_used"),
        "idiot.exile_immunity": (None, None),
    }
    runtime_abilities: list[dict[str, Any]] = []
    for ability in abilities:
        if not isinstance(ability, dict):
            continue
        ability_id = ability.get("ability_id")
        if not isinstance(ability_id, str):
            continue
        last_commit = latest_commits.get(ability_id)
        remaining_uses: int | None = None
        resource_status = "not_limited"
        limited = limited_uses.get(ability_id)
        if limited is not None:
            remaining_key, result_key = limited
            remaining_uses = 1
            if ability_id == "idiot.exile_immunity" and bool(player_state.get("idiot_revealed")):
                remaining_uses = 0
            elif (
                isinstance(last_commit, dict)
                and isinstance(last_commit.get("result"), dict)
                and result_key is not None
                and last_commit["result"].get(result_key) is True
            ):
                remaining_uses = 0
            explicit_remaining = (
                knowledge.get(remaining_key) if isinstance(remaining_key, str) else None
            )
            if isinstance(explicit_remaining, int) and not isinstance(explicit_remaining, bool):
                remaining_uses = max(0, explicit_remaining)
            resource_status = "consumed" if remaining_uses == 0 else "available"

        in_current_action_window = current_ability_id == ability_id
        can_execute_now = alive and in_current_action_window and resource_status != "consumed"
        unavailable_now_reason: str | None = None
        if not alive:
            unavailable_now_reason = "actor_not_alive"
        elif resource_status == "consumed":
            unavailable_now_reason = "resource_consumed"
        elif not in_current_action_window:
            unavailable_now_reason = "not_current_action_window"

        runtime_ability: dict[str, Any] = {
            "ability_id": ability_id,
            "owned": True,
            "resource_status": resource_status,
            "remaining_uses": remaining_uses,
            "in_current_action_window": in_current_action_window,
            "can_execute_now": can_execute_now,
            "unavailable_now_reason": unavailable_now_reason,
        }
        if last_commit is not None:
            runtime_ability["last_committed_action"] = dict(last_commit)
        runtime_abilities.append(runtime_ability)

    return {
        "source": "private_role_assignment_action_history_and_current_window",
        "current_action_ability_id": current_ability_id,
        "abilities": runtime_abilities,
        "instruction": (
            "owned 只表示真实角色拥有该能力；是否已消耗以及本次动作能否执行，"
            "必须以 resource_status、remaining_uses 和 can_execute_now 为准。"
        ),
    }


def _ability_id_for_action(action_type: str | None) -> str | None:
    if not isinstance(action_type, str):
        return None
    if action_type.startswith("ability_") and action_type.endswith("_decision"):
        return action_type[len("ability_") : -len("_decision")]
    if action_type == "werewolf_self_explosion":
        return "werewolf.self_explosion"
    return None


def _public_office_capabilities(
    *,
    is_sheriff: bool,
    sheriff_badge_state: str,
    rule: dict[str, Any],
) -> dict[str, Any]:
    sheriff_enabled = bool(rule.get("sheriff_enabled"))
    abilities: list[dict[str, Any]] = []
    if is_sheriff:
        abilities.append(
            {
                "authority_id": "sheriff.weighted_exile_vote",
                "timing": "weighted_exile_vote",
                "vote_weight": float(rule.get("sheriff_vote_weight") or 1),
            }
        )
        if str(rule.get("speech_policy") or "sequential") == "sheriff_directed":
            abilities.append(
                {
                    "authority_id": "sheriff.choose_speech_order",
                    "timing": "day_discussion_opening",
                }
            )
        abilities.append(
            {
                "authority_id": "sheriff.resolve_badge_after_death",
                "timing": "death_reaction",
                "choices": ["transfer_to_alive_player", "destroy_badge"],
            }
        )
    return {
        "source": "public_match_state_and_frozen_rules",
        "sheriff_system_enabled": sheriff_enabled,
        "is_current_sheriff": is_sheriff,
        "sheriff_badge_state": sheriff_badge_state,
        "abilities": abilities,
        "instruction": ("警长职权只与职位有关，不会授予验人、用药、守护、开枪或其他角色能力。"),
    }


def _night_action_rules(
    *,
    role_keys: set[str],
    werewolf_count: int,
    ability_policies: Any,
) -> dict[str, Any]:
    policies = ability_policies if isinstance(ability_policies, dict) else {}
    result: dict[str, Any] = {
        "werewolf_attack": {
            "enabled": werewolf_count > 0,
            "actor_scope": "所有存活狼人",
            "target_scope": "一名存活的非狼人玩家",
            "each_actor_must_choose_target": True,
            "can_target_self": False,
            "can_target_werewolf_teammates": False,
            "team_resolution": dict(policies.get("werewolf_consensus") or {}),
            "single_werewolf_resolution": (
                "本局只有1名狼人时，该狼人每夜必须选择一名存活的非狼人玩家，"
                "不会因团队意见不一致而空刀。"
                if werewolf_count == 1
                else None
            ),
        }
    }
    if "guard" in role_keys:
        guard_policy = policies.get("guard")
        result["guard_protect"] = {
            "enabled": True,
            "target_scope": "一名存活玩家，可以选择自己",
            "target_required": True,
            "first_night_self_protect": bool(
                isinstance(guard_policy, dict) and guard_policy.get("first_night_self_protect")
            ),
            "can_repeat_previous_night_target": bool(
                isinstance(guard_policy, dict) and guard_policy.get("consecutive_same_target")
            ),
            "successful_protection_effect": (
                "若守护目标当夜受到狼人攻击，该目标不会因这次攻击出局。"
            ),
        }
    if "seer" in role_keys:
        result["seer_investigate"] = {
            "enabled": True,
            "target_scope": "一名其他存活玩家",
            "target_required": True,
            "result_scope": "法官只向预言家确认目标属于狼人阵营或好人阵营",
        }
    if "witch" in role_keys:
        witch_policy = policies.get("witch")
        witch_policy = witch_policy if isinstance(witch_policy, dict) else {}
        result["witch"] = {
            "enabled": True,
            "first_night_self_heal": bool(witch_policy.get("first_night_self_heal")),
            "heal_poison_mutually_exclusive": bool(
                witch_policy.get("heal_poison_mutually_exclusive")
            ),
            "poison_excludes_self": bool(witch_policy.get("poison_excludes_self")),
            "poison_excludes_attacked_target": bool(
                witch_policy.get("poison_excludes_attacked_target")
            ),
        }
    if "hunter" in role_keys:
        hunter_policy = policies.get("hunter")
        hunter_policy = hunter_policy if isinstance(hunter_policy, dict) else {}
        result["hunter_death_shot"] = {
            "enabled": True,
            "poison_disables_shot": bool(hunter_policy.get("poison_disables_shot")),
        }
    return result


def private_authoritative_facts(knowledge: Any) -> list[dict[str, Any]]:
    if isinstance(knowledge, list):
        return [dict(item) for item in knowledge if isinstance(item, dict)]
    if not isinstance(knowledge, dict):
        return []

    facts: list[dict[str, Any]] = []
    for fact_type, payload in knowledge.items():
        if fact_type == "known_investigations" and isinstance(payload, list):
            facts.extend(dict(item) for item in payload if isinstance(item, dict))
            continue
        facts.append({"fact_type": fact_type, "payload": payload})
    return facts


def _project_public_history(
    history: Iterable[Any],
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    facts: list[dict[str, Any]] = []
    statements: list[dict[str, Any]] = []
    role_confirmations: list[dict[str, Any]] = []
    vote_snapshots: list[dict[str, Any]] = []
    has_presented_player_speech = any(
        isinstance(item, dict) and item.get("event_type") == "public_player_speech_presented"
        for item in history
    )
    latest_round = 1
    for history_index, raw_item in enumerate(history, start=1):
        if not isinstance(raw_item, dict):
            continue
        event_type = raw_item.get("event_type")
        payload = raw_item.get("payload")
        if not isinstance(event_type, str) or not isinstance(payload, dict):
            continue
        source_event_id = _source_id(raw_item.get("source_event_id"))
        if source_event_id is None:
            source_event_id = f"history_{history_index}"
        round_no = payload.get("round_no")
        if isinstance(round_no, int) and round_no > 0:
            latest_round = round_no
        projected_payload = _project_value(payload, players=players)
        if event_type == "public_player_speech_presented":
            statements.append(
                {
                    "kind": "player_statement",
                    "source_event_id": source_event_id,
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "stage": projected_payload.get("stage"),
                    "speaker_ref": projected_payload.get("player_id"),
                    "speech": projected_payload.get("speech"),
                }
            )
            continue
        if event_type == "day_speech_committed":
            if not has_presented_player_speech:
                statements.append(
                    {
                        "kind": "player_statement",
                        "source_event_id": source_event_id,
                        "occurred_in": {"period": "day", "round_no": latest_round},
                        "stage": projected_payload.get("stage"),
                        "speaker_ref": projected_payload.get("player_id"),
                        "speech": projected_payload.get("speech"),
                    }
                )
            continue
        if event_type == "day_vote_committed":
            facts.append(
                {
                    "kind": "day_vote",
                    "source_event_id": source_event_id,
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "action_type": projected_payload.get("action_type"),
                    "voter_ref": projected_payload.get("voter_player_id"),
                    "target_ref": projected_payload.get("target_player_id"),
                    "weight": projected_payload.get("weight"),
                }
            )
            speech = projected_payload.get("speech")
            if not has_presented_player_speech and isinstance(speech, str) and speech:
                statements.append(
                    {
                        "kind": "player_statement",
                        "source_event_id": f"{source_event_id}:speech",
                        "occurred_in": {"period": "day", "round_no": latest_round},
                        "stage": projected_payload.get("action_type"),
                        "speaker_ref": projected_payload.get("voter_player_id"),
                        "speech": speech,
                    }
                )
            continue
        if event_type == "day_vote_resolved":
            vote_snapshots.append(
                {
                    "kind": "vote_result",
                    "source_event_id": source_event_id,
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "action_type": projected_payload.get("action_type"),
                    "eligible_voter_refs": projected_payload.get("eligible_voter_ids", []),
                    "ineligible_voter_refs": projected_payload.get("ineligible_voter_ids", []),
                    "candidate_refs": projected_payload.get("candidate_player_ids", []),
                    "weighted": projected_payload.get("weighted"),
                    "sheriff_ref": projected_payload.get("sheriff_player_id"),
                    "sheriff_vote_weight": projected_payload.get("sheriff_vote_weight"),
                    "voter_weights": projected_payload.get("voter_weights", {}),
                    "totals": projected_payload.get("totals", {}),
                    "leader_refs": projected_payload.get("leaders", []),
                    "identity_reveal": "none",
                }
            )
            continue
        if event_type == "dawn_public_result":
            eliminated = projected_payload.get("dead_player_ids")
            eliminated_refs = eliminated if isinstance(eliminated, list) else []
            facts.append(
                {
                    "kind": "night_result",
                    "source_event_id": source_event_id,
                    "occurred_in": {"period": "night", "round_no": latest_round},
                    "announced_in": {"period": "dawn", "round_no": latest_round},
                    "outcome": "deaths" if eliminated_refs else "peaceful",
                    "eliminated_player_refs": eliminated_refs,
                    "role_revealed": False,
                    "known_role": None,
                    "identity_reveal": "none",
                }
            )
            continue
        if event_type == "player_exiled":
            facts.append(
                {
                    "kind": "player_eliminated",
                    "source_event_id": source_event_id,
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "public_reason": "exile",
                    "player_ref": projected_payload.get("player_id"),
                    "role_revealed": False,
                    "known_role": None,
                    "identity_reveal": "none",
                }
            )
            continue
        if event_type == "idiot_revealed":
            confirmation = {
                "source_event_id": source_event_id,
                "player_ref": projected_payload.get("player_id"),
                "role_key": "idiot",
                "confirmation_reason": "idiot_exile_immunity_triggered",
                "confirmation_status": "confirmed_by_judge",
            }
            role_confirmations.append(confirmation)
            facts.append(
                {
                    "kind": "role_revealed",
                    "source_event_id": source_event_id,
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "player_ref": projected_payload.get("player_id"),
                    "role_revealed": True,
                    "known_role": "idiot",
                    "survived": bool(projected_payload.get("survived")),
                }
            )
            continue
        if event_type == "werewolf_self_exploded":
            role_confirmations.append(
                {
                    "source_event_id": source_event_id,
                    "player_ref": projected_payload.get("player_id"),
                    "role_key": "werewolf",
                    "confirmation_reason": "werewolf_self_explosion",
                    "confirmation_status": "confirmed_by_judge",
                }
            )
            facts.append(
                {
                    "kind": "player_eliminated",
                    "source_event_id": source_event_id,
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "public_reason": "self_explosion",
                    "player_ref": projected_payload.get("player_id"),
                    "stage": projected_payload.get("stage"),
                    "role_revealed": True,
                    "known_role": "werewolf",
                    "identity_reveal": "werewolf_confirmed",
                }
            )
            continue
        if event_type == "hunter_response_resolved":
            hunter_ref = projected_payload.get("hunter_player_id")
            target_ref = projected_payload.get("target_player_id")
            if target_ref is not None:
                role_confirmations.append(
                    {
                        "source_event_id": source_event_id,
                        "player_ref": hunter_ref,
                        "role_key": "hunter",
                        "confirmation_reason": "hunter_public_shot",
                        "confirmation_status": "confirmed_by_judge",
                    }
                )
            facts.append(
                {
                    "kind": "hunter_response",
                    "source_event_id": source_event_id,
                    "occurred_in": {
                        "period": projected_payload.get("period") or "day",
                        "round_no": latest_round,
                    },
                    "hunter_ref": hunter_ref,
                    "target_ref": target_ref,
                    "hunter_role_revealed": target_ref is not None,
                    "target_role_revealed": False,
                    "target_known_role": None,
                }
            )
            continue
        facts.append(
            {
                "kind": event_type,
                "source_event_id": source_event_id,
                "occurred_in": {
                    "period": _public_event_period(event_type),
                    "round_no": latest_round,
                },
                "payload": projected_payload,
            }
        )
    return facts, statements, role_confirmations, vote_snapshots


_DURABLE_STATEMENT_TERMS = (
    "预言家",
    "狼人",
    "狼",
    "好人",
    "金水",
    "查杀",
    "村民",
    "女巫",
    "猎人",
    "白痴",
    "守卫",
    "警长",
    "警徽",
    "上警",
    "退水",
    "对跳",
    "悍跳",
    "自爆",
    "站边",
    "怀疑",
    "认下",
    "保",
    "打",
    "出",
    "投",
    "验",
    "毒",
    "救",
    "刀",
    "归票",
    "票型",
    "身份",
    "阵营",
    "狼坑",
    "承诺",
    "明天",
    "今晚",
)
_STRUCTURED_SENTENCE_BOUNDARY = re.compile(r"(?<=[。！？!?；;])|[，,：:]|\n+")
_SEAT_REFERENCE = re.compile(r"(?<!\d)(?:seat_)?(2[0-9]|1[0-9]|[1-9])号?")
_ROLE_CLAIM = re.compile(r"(?:我是|我跳|我拍)(?:真)?(?:预言家|女巫|猎人|白痴|守卫|村民|好人|狼人)")


def _compact_public_statements(
    statements: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not statements:
        return [], []

    exact_ids: set[str] = set()
    exact_statements_reversed: list[dict[str, Any]] = []
    remaining_recent_chars = _RECENT_STATEMENT_CHAR_BUDGET
    for statement in reversed(statements):
        source_id = _source_id(statement.get("source_event_id"))
        speech = statement.get("speech")
        if source_id is None or not isinstance(speech, str):
            continue
        if len(exact_statements_reversed) >= _RECENT_STATEMENT_LIMIT or remaining_recent_chars <= 0:
            break
        bounded_speech = speech[:remaining_recent_chars]
        if not bounded_speech:
            continue
        bounded_statement = dict(statement)
        bounded_statement["speech"] = bounded_speech
        if len(bounded_speech) < len(speech):
            bounded_statement["speech_truncated"] = True
        exact_statements_reversed.append(bounded_statement)
        exact_ids.add(source_id)
        remaining_recent_chars -= len(bounded_speech)

    exact_statements = list(reversed(exact_statements_reversed))
    older_ledger_reversed: list[dict[str, Any]] = []
    remaining_claim_chars = _OLDER_CLAIM_CHAR_BUDGET
    for statement in reversed(statements):
        if len(older_ledger_reversed) >= _OLDER_CLAIM_LIMIT or remaining_claim_chars <= 0:
            break
        source_id = _source_id(statement.get("source_event_id"))
        speaker_ref = statement.get("speaker_ref")
        speech = statement.get("speech")
        if (
            source_id is None
            or source_id in exact_ids
            or not isinstance(speaker_ref, str)
            or not isinstance(speech, str)
        ):
            continue
        claims: list[str] = []
        for clause in _durable_statement_clauses(speech):
            if len(claims) >= _CLAIMS_PER_STATEMENT_LIMIT or remaining_claim_chars <= 0:
                break
            bounded_claim = clause[: min(_CLAIM_CHAR_LIMIT, remaining_claim_chars)]
            if bounded_claim:
                claims.append(bounded_claim)
                remaining_claim_chars -= len(bounded_claim)
        if not claims:
            continue
        older_ledger_reversed.append(
            {
                "source_event_id": source_id,
                "occurred_in": statement.get("occurred_in"),
                "stage": statement.get("stage"),
                "speaker_ref": speaker_ref,
                "mentioned_player_refs": sorted(
                    _mentioned_player_refs(speech),
                    key=_seat_sort_key,
                ),
                "exact_claim_fragments": claims,
                "confirmation_status": "unverified",
            }
        )
    older_ledger = list(reversed(older_ledger_reversed))
    return exact_statements, older_ledger


def _mentioned_player_refs(speech: str) -> set[str]:
    return {f"seat_{match.group(1)}" for match in _SEAT_REFERENCE.finditer(speech)}


def _durable_statement_clauses(speech: str) -> list[str]:
    clauses: list[str] = []
    for raw_clause in _STRUCTURED_SENTENCE_BOUNDARY.split(speech):
        clause = raw_clause.strip()
        if not clause:
            continue
        has_stance = any(term in clause for term in _DURABLE_STATEMENT_TERMS)
        if (_SEAT_REFERENCE.search(clause) and has_stance) or _ROLE_CLAIM.search(clause):
            clauses.append(clause)
    return clauses


def _source_id(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


def _seat_sort_key(ref: str) -> tuple[int, str]:
    if ref.startswith("seat_") and ref[5:].isdigit():
        return int(ref[5:]), ref
    return 10_000, ref


def _public_event_period(event_type: str) -> str:
    return "dawn" if event_type == "dawn_public_result" else "day"


def _project_value(
    value: Any,
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> Any:
    if isinstance(value, dict):
        return {
            (_project_text(key, players=players) if isinstance(key, str) else key): _project_value(
                item, players=players
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_project_value(item, players=players) for item in value]
    if isinstance(value, tuple):
        return [_project_value(item, players=players) for item in value]
    if isinstance(value, str):
        return _project_text(value, players=players)
    return value


def _project_text(
    value: str,
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> str:
    projected = value
    for player in sorted(players, key=lambda item: len(item.player_id), reverse=True):
        projected = projected.replace(player.player_id, player.ref)
    for player in sorted(players, key=lambda item: len(item.display_name), reverse=True):
        if player.display_name:
            projected = projected.replace(player.display_name, player.label)
    return projected
