from __future__ import annotations

VILLAGER = "村民"
WEREWOLF = "狼人"
SEER = "预言家"
GUARD = "守卫"
DOCTOR = GUARD
WITCH = "女巫"
HUNTER = "猎人"
IDIOT = "白痴"

WINNER_VILLAGERS = "好人阵营"
WINNER_WEREWOLVES = "狼人阵营"

DEFAULT_PLAYER_COUNT = 8
DEFAULT_DEBATE_TURNS = 2
DEFAULT_MAX_ROUNDS = 8


def choose_player_names(seed: int | None, player_count: int = DEFAULT_PLAYER_COUNT) -> list[str]:
    return [f"{index}号玩家" for index in range(1, player_count + 1)]
