from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.v2.ability_runtime import normalize_role_key, normalize_team_key


MODEL_INFORMATION_SEMANTICS = {
    "public_rule_contract": (
        "本局冻结的公开规则；enabled=false 表示对应机制在本局不存在。"
    ),
    "public_match_state": (
        "当前法官确认的公开存活状态；只包含座位与是否仍在场，不包含任何身份或阵营信息。"
    ),
    "private_authoritative_facts": (
        "法官只向当前行动玩家确认的真实私有事实；是否公开以及如何使用由玩家自主决定。"
    ),
    "authoritative_public_facts": "法官已经向全体玩家确认的公开事实。",
    "public_statements": (
        "玩家的公开说法，可能包含欺骗、误判或遗漏，不会改变冻结规则或法官事实。"
    ),
    "peaceful_night": (
        "night_result.outcome=peaceful 只表示该夜无人出局，不表示当前玩家没有其他私有信息。"
    ),
    "decision_freedom": (
        "这些字段只描述当前玩家可知的信息；如何判断、是否公开私有事实以及采用何种策略"
        "均由玩家自主决定。"
    ),
}


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
    projected = _project_value(context, players=players)
    public_history = context.get("public_history")
    if isinstance(public_history, list) or isinstance(public_history, tuple):
        facts, statements = _project_public_history(public_history, players=players)
        projected.pop("public_history", None)
        projected["authoritative_public_facts"] = facts
        projected["public_statements"] = statements
    projected["information_semantics"] = dict(MODEL_INFORMATION_SEMANTICS)
    projected["player_reference_rule"] = {
        "reference_format": "seat_N",
        "spoken_format": "N号",
        "names_available": False,
        "instruction": "只使用座位号称呼玩家，不得猜测或生成玩家姓名。",
    }
    return projected


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
    werewolf_count = sum(
        item["count"] for item in roles if item["role_key"] == "werewolf"
    )
    sheriff_enabled = bool(rule.get("sheriff_enabled"))
    role_composition = "、".join(
        f"{item['count']}名{item['role_label']}" for item in roles
    )
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
            float(rule.get("sheriff_vote_weight") or 1)
            if sheriff_enabled
            else None
        ),
        "sheriff_rule": (
            "本局启用警长系统。"
            if sheriff_enabled
            else "本局不启用警长系统，不存在上警、警徽或警徽流机制。"
        ),
        "speech_policy": rule.get("speech_policy") or "sequential",
        "speech_rounds": int(rule.get("speech_rounds") or 1),
        "werewolf_self_explosion_enabled": bool(
            rule.get("werewolf_self_explosion_enabled")
        ),
        "exile_last_words_enabled": bool(rule.get("exile_last_words_enabled")),
    }


def build_public_match_state(
    *,
    round_no: int,
    players: Iterable[Any],
) -> dict[str, Any]:
    player_list = tuple(players)
    alive_player_ids = [
        str(player.player_id) for player in player_list if bool(player.alive)
    ]
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
                isinstance(guard_policy, dict)
                and guard_policy.get("first_night_self_protect")
            ),
            "can_repeat_previous_night_target": bool(
                isinstance(guard_policy, dict)
                and guard_policy.get("consecutive_same_target")
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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    facts: list[dict[str, Any]] = []
    statements: list[dict[str, Any]] = []
    latest_round = 1
    for raw_item in history:
        if not isinstance(raw_item, dict):
            continue
        event_type = raw_item.get("event_type")
        payload = raw_item.get("payload")
        if not isinstance(event_type, str) or not isinstance(payload, dict):
            continue
        round_no = payload.get("round_no")
        if isinstance(round_no, int) and round_no > 0:
            latest_round = round_no
        projected_payload = _project_value(payload, players=players)

        if event_type == "day_speech_committed":
            statements.append(
                {
                    "kind": "player_statement",
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
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "action_type": projected_payload.get("action_type"),
                    "voter_ref": projected_payload.get("voter_player_id"),
                    "target_ref": projected_payload.get("target_player_id"),
                    "weight": projected_payload.get("weight"),
                }
            )
            speech = projected_payload.get("speech")
            if isinstance(speech, str) and speech:
                statements.append(
                    {
                        "kind": "player_statement",
                        "occurred_in": {"period": "day", "round_no": latest_round},
                        "stage": projected_payload.get("action_type"),
                        "speaker_ref": projected_payload.get("voter_player_id"),
                        "speech": speech,
                    }
                )
            continue
        if event_type == "dawn_public_result":
            eliminated = projected_payload.get("dead_player_ids")
            eliminated_refs = eliminated if isinstance(eliminated, list) else []
            facts.append(
                {
                    "kind": "night_result",
                    "occurred_in": {"period": "night", "round_no": latest_round},
                    "announced_in": {"period": "dawn", "round_no": latest_round},
                    "outcome": "deaths" if eliminated_refs else "peaceful",
                    "eliminated_player_refs": eliminated_refs,
                }
            )
            continue
        if event_type == "player_exiled":
            facts.append(
                {
                    "kind": "player_eliminated",
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "public_reason": "exile",
                    "player_ref": projected_payload.get("player_id"),
                }
            )
            continue
        if event_type == "werewolf_self_exploded":
            facts.append(
                {
                    "kind": "player_eliminated",
                    "occurred_in": {"period": "day", "round_no": latest_round},
                    "public_reason": "self_explosion",
                    "player_ref": projected_payload.get("player_id"),
                    "stage": projected_payload.get("stage"),
                }
            )
            continue
        if event_type == "hunter_response_resolved":
            facts.append(
                {
                    "kind": "hunter_response",
                    "occurred_in": {
                        "period": projected_payload.get("period") or "day",
                        "round_no": latest_round,
                    },
                    "hunter_ref": projected_payload.get("hunter_player_id"),
                    "target_ref": projected_payload.get("target_player_id"),
                }
            )
            continue
        facts.append(
            {
                "kind": event_type,
                "occurred_in": {
                    "period": _public_event_period(event_type),
                    "round_no": latest_round,
                },
                "payload": projected_payload,
            }
        )
    return facts, statements


def _public_event_period(event_type: str) -> str:
    return "dawn" if event_type == "dawn_public_result" else "day"


def _project_value(
    value: Any,
    *,
    players: tuple[V2ModelPlayerReference, ...],
) -> Any:
    if isinstance(value, dict):
        return {
            (
                _project_text(key, players=players)
                if isinstance(key, str)
                else key
            ): _project_value(item, players=players)
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
