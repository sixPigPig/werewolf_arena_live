from __future__ import annotations

import random

VILLAGER = "村民"
WEREWOLF = "狼人"
SEER = "预言家"
DOCTOR = "医生"

WINNER_VILLAGERS = "好人阵营"
WINNER_WEREWOLVES = "狼人阵营"

DEFAULT_PLAYER_COUNT = 8
DEFAULT_DEBATE_TURNS = 2
DEFAULT_MAX_ROUNDS = 8

PLAYER_NAMES = (
    "Derek",
    "Scott",
    "Jacob",
    "Isaac",
    "Hayley",
    "David",
    "Tyler",
    "Ginger",
    "Jackson",
    "Mason",
    "Dan",
    "Bert",
    "Will",
    "Sam",
    "Paul",
    "Leah",
    "Harold",
)


def choose_player_names(seed: int | None, player_count: int = DEFAULT_PLAYER_COUNT) -> list[str]:
    rng = random.Random(seed)
    return rng.sample(list(PLAYER_NAMES), player_count)
