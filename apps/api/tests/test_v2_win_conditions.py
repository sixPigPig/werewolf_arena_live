from app.v2.win_conditions import (
    all_hunter_settlement_branches_terminal,
    build_public_win_condition_contract,
    hunter_settlement_can_change_winner,
    winner_from_alive_roles,
)


def test_slaughter_side_public_contract_derives_gods_from_frozen_roles() -> None:
    contract = build_public_win_condition_contract(
        "slaughter_side",
        frozen_role_keys=(
            "werewolf",
            "villager",
            "seer",
            "witch",
            "hunter",
            "idiot",
            "guard",
        ),
    )

    assert contract["mode"] == "slaughter_side"
    assert contract["evaluation_order"] == ["villagers", "werewolves"]
    assert contract["post_elimination_resolution"] == {
        "check": "after_each_elimination_before_next_ordinary_action",
        "outcome_changing_death_triggers": "resolve_before_final_result",
    }
    assert contract["groups"]["living_gods"] == {
        "role_keys": ["seer", "witch", "hunter", "idiot", "guard"]
    }
    assert contract["werewolves_victory"] == {
        "operator": "any",
        "conditions": [
            {
                "metric": "living_villagers",
                "operator": "eq",
                "value": 0,
                "boundary": "slaughter_villagers",
            },
            {
                "metric": "living_gods",
                "operator": "eq",
                "value": 0,
                "boundary": "slaughter_gods",
            },
        ],
    }


def test_parity_public_contract_uses_all_frozen_non_werewolf_roles() -> None:
    contract = build_public_win_condition_contract(
        "wolves_gte_others",
        frozen_role_keys=("werewolf", "villager", "seer", "villager", "hunter"),
    )

    assert contract["groups"]["living_non_werewolves"] == {
        "role_keys": ["villager", "seer", "hunter"]
    }
    assert contract["werewolves_victory"] == {
        "left_metric": "living_werewolves",
        "operator": "gte",
        "right_metric": "living_non_werewolves",
        "boundary": "werewolf_parity",
    }


def test_slaughter_side_terminal_matrix_prefers_no_wolves() -> None:
    assert (
        winner_from_alive_roles(
            ["villager", "seer"],
            win_condition="slaughter_side",
        )
        == "villagers"
    )
    assert (
        winner_from_alive_roles(
            ["werewolf", "seer"],
            win_condition="slaughter_side",
        )
        == "werewolves"
    )
    assert (
        winner_from_alive_roles(
            ["werewolf", "villager"],
            win_condition="slaughter_side",
        )
        == "werewolves"
    )
    assert (
        winner_from_alive_roles(
            ["werewolf", "villager", "seer"],
            win_condition="slaughter_side",
        )
        is None
    )


def test_parity_terminal_matrix() -> None:
    assert (
        winner_from_alive_roles(
            ["villager", "hunter"],
            win_condition="wolves_gte_others",
        )
        == "villagers"
    )
    assert (
        winner_from_alive_roles(
            ["werewolf", "villager"],
            win_condition="wolves_gte_others",
        )
        == "werewolves"
    )
    assert (
        winner_from_alive_roles(
            ["werewolf", "villager", "seer"],
            win_condition="wolves_gte_others",
        )
        is None
    )


def test_terminal_hunter_only_settles_when_a_legal_branch_can_change_winner() -> None:
    roles = {
        "wolf_1": "werewolf",
        "wolf_2": "werewolf",
        "villager": "villager",
        "hunter": "hunter",
    }
    assert hunter_settlement_can_change_winner(
        living_player_ids=frozenset({"wolf_1"}),
        pending_hunter_ids=("hunter",),
        role_by_player_id=roles,
        win_condition="wolves_gte_others",
    )
    assert not hunter_settlement_can_change_winner(
        living_player_ids=frozenset({"wolf_1", "wolf_2"}),
        pending_hunter_ids=("hunter",),
        role_by_player_id=roles,
        win_condition="wolves_gte_others",
    )


def test_pre_dawn_election_is_skipped_only_if_every_hunter_branch_is_terminal() -> None:
    roles = {
        "wolf": "werewolf",
        "villager": "villager",
        "seer": "seer",
        "hunter": "hunter",
    }
    assert all_hunter_settlement_branches_terminal(
        living_player_ids=frozenset({"wolf"}),
        pending_hunter_ids=("hunter",),
        role_by_player_id=roles,
        win_condition="wolves_gte_others",
    )
    assert not all_hunter_settlement_branches_terminal(
        living_player_ids=frozenset({"wolf", "villager", "seer"}),
        pending_hunter_ids=("hunter",),
        role_by_player_id=roles,
        win_condition="slaughter_side",
    )
