from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from app.werewolf.models import SheriffBadgeResolution, SheriffElectionResolution

NightPublicOutcome = Literal["peaceful", "deaths"]


@dataclass(frozen=True)
class JudgeCueSpec:
    cue_id: str
    visible_text: str
    static_asset_id: str | None
    params: dict[str, object] = field(default_factory=dict)

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "cue_id": self.cue_id,
            "cue": self.cue_id,
            "visible_text": self.visible_text,
            "static_asset_id": self.static_asset_id,
            "params": self.params.copy(),
            **self.params,
        }


STATIC_CUE_TEXT: dict[str, str] = {
    "dawn_peaceful": "昨夜平安夜。",
    "sheriff_raise_hands": "想要竞选警长的玩家请举手。",
    "sheriff_tie": "警长首轮投票出现平票，进入 PK 发言。",
    "sheriff_pk_start": "平票候选人依次进行 PK 发言。",
    "sheriff_runoff_vote": "PK 发言结束，警下玩家开始二轮投票。",
    "sheriff_no_voters": "本轮没有警下投票者，警徽流失。",
    "sheriff_runoff_tied": "警长二轮投票仍未产生唯一领先者。",
    "sheriff_no_badge": "本局警徽流失，不再产生警长。",
    "self_explosion_skip": "本轮剩余发言和放逐投票终止，直接进入夜晚。",
    "hunter_shot_start": "猎人死亡，可以发动技能。",
    "hunter_shot_choose": "请猎人选择要带走的玩家。",
    "hunter_shot_skipped": "猎人选择不发动技能。",
    "idiot_stays": "该玩家免于本次放逐，但失去后续投票权。",
    "badge_owner_out": "警长出局，请选择移交警徽或撕毁警徽。",
    "badge_destroyed": "警徽被撕毁。",
}


def cue_spec(
    cue_id: str,
    visible_text: str | None = None,
    *,
    static_asset_id: str | None = None,
    params: dict[str, object] | None = None,
) -> JudgeCueSpec:
    text = visible_text or STATIC_CUE_TEXT.get(cue_id)
    if not text:
        raise ValueError(f"Judge cue {cue_id} requires visible text")
    return JudgeCueSpec(
        cue_id=cue_id,
        visible_text=text,
        static_asset_id=static_asset_id,
        params=(params or {}).copy(),
    )


def dawn_result_cue(death_players: list[str]) -> JudgeCueSpec:
    if not death_players:
        return cue_spec("dawn_peaceful", static_asset_id="dawn_peaceful")
    names = "、".join(death_players)
    return cue_spec(
        "dawn_deaths",
        f"昨夜死亡的玩家是 {names}。",
        params={"players": death_players.copy()},
    )


def sheriff_election_cues(
    resolution: SheriffElectionResolution,
) -> list[JudgeCueSpec]:
    params: dict[str, object] = {
        "outcome": resolution.outcome,
        "reason_code": resolution.reason_code,
    }
    if resolution.reason_code == "no_off_sheriff_voters":
        return [
            cue_spec(
                "sheriff_no_voters",
                params=params,
            )
        ]
    if resolution.reason_code == "runoff_tied":
        return [
            cue_spec(
                "sheriff_runoff_tied",
                params=params,
            ),
            cue_spec(
                "sheriff_no_badge",
                static_asset_id="sheriff_no_badge",
                params=params,
            ),
        ]
    if resolution.outcome == "elected" and resolution.sheriff:
        return [
            cue_spec(
                "sheriff_result",
                f"{resolution.sheriff}当选警长，获得警徽。",
                static_asset_id=seat_asset_id("sheriff_result", resolution.sheriff),
                params={**params, "sheriff": resolution.sheriff},
            )
        ]
    if resolution.outcome == "postponed":
        return [
            cue_spec(
                "sheriff_election_postponed",
                "本轮警长竞选中断，竞选顺延至下一轮。",
                params=params,
            )
        ]
    return [
        cue_spec(
            "sheriff_no_badge",
            f"{resolution.reason_text}，本局警徽流失。",
            static_asset_id="sheriff_no_badge",
            params=params,
        )
    ]


def sheriff_tie_cues(pk_candidates: list[str]) -> list[JudgeCueSpec]:
    params: dict[str, object] = {"pk_candidates": pk_candidates.copy()}
    return [
        cue_spec("sheriff_tie", static_asset_id="sheriff_tie", params=params),
        cue_spec("sheriff_pk_start", params=params),
        cue_spec(
            "sheriff_runoff_vote",
            static_asset_id="sheriff_vote",
            params=params,
        ),
    ]


def self_explosion_cues(
    player: str,
    *,
    stage: str,
    completed_actors: list[str],
    pending_actors: list[str],
) -> list[JudgeCueSpec]:
    params: dict[str, object] = {
        "player": player,
        "stage": stage,
        "completed_actors": completed_actors.copy(),
        "pending_actors": pending_actors.copy(),
    }
    return [
        cue_spec(
            "werewolf_self_explosion",
            f"{player}自爆为狼人，立即出局。",
            params=params,
        ),
        cue_spec(
            "self_explosion_skip",
            static_asset_id="self_explosion_skip",
            params=params,
        ),
    ]


def hunter_start_cues(hunter: str) -> list[JudgeCueSpec]:
    params = {"hunter": hunter}
    return [
        cue_spec("hunter_shot_start", static_asset_id="hunter_shot_start", params=params),
        cue_spec("hunter_shot_choose", static_asset_id="hunter_shot_choose", params=params),
    ]


def hunter_result_cue(target: str | None) -> JudgeCueSpec:
    if not target:
        return cue_spec("hunter_shot_skipped")
    return cue_spec(
        "hunter_shot_result",
        f"{target}被猎人带走，出局。",
        static_asset_id=seat_asset_id("hunter_shot_result", target),
        params={"target": target},
    )


def idiot_reveal_cues(player: str) -> list[JudgeCueSpec]:
    params = {"player": player}
    return [
        cue_spec(
            "idiot_reveal",
            f"{player}翻牌为白痴。",
            static_asset_id=seat_asset_id("idiot_reveal", player),
            params=params,
        ),
        cue_spec("idiot_stays", static_asset_id="idiot_stays", params=params),
    ]


def sheriff_badge_cues(resolution: SheriffBadgeResolution) -> list[JudgeCueSpec]:
    params: dict[str, object] = resolution.to_dict()
    cues = [cue_spec("badge_owner_out", static_asset_id="badge_owner_out", params=params)]
    if resolution.outcome == "transferred" and resolution.to_player:
        cues.append(
            cue_spec(
                "badge_transfer",
                f"警徽移交给 {resolution.to_player}。",
                static_asset_id=seat_asset_id("badge_transfer", resolution.to_player),
                params=params,
            )
        )
    elif resolution.outcome == "destroyed":
        cues.append(cue_spec("badge_destroyed", static_asset_id="badge_destroyed", params=params))
    else:
        cues.append(
            cue_spec(
                "sheriff_no_badge",
                "没有可移交警徽的玩家，警徽流失。",
                static_asset_id="sheriff_no_badge",
                params=params,
            )
        )
    return cues


def exile_result_cue(player: str) -> JudgeCueSpec:
    return cue_spec(
        "exile_result",
        f"{player}得票最高，被放逐出局。",
        static_asset_id=seat_asset_id("exile_result", player),
        params={"player": player},
    )


def seat_asset_id(template_id: str, player: str) -> str | None:
    match = re.fullmatch(r"(\d+)号玩家", player.strip())
    if match is None:
        return None
    seat = int(match.group(1))
    if not 1 <= seat <= 12:
        return None
    return f"{template_id}_seat_{seat:02d}"
