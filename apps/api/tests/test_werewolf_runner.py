import json

import pytest

from app.werewolf.runner import GameRunError, run_game


def test_run_game_with_local_models_writes_complete_logs(tmp_path) -> None:
    result = run_game(logs_dir=tmp_path, seed=7, max_rounds=8)

    assert result.winner in {"Villagers", "Werewolves"}
    assert result.session_id.startswith("session_")
    assert result.log_directory.exists()
    assert (result.log_directory / "game_complete.json").exists()
    assert (result.log_directory / "game_logs.json").exists()

    state = json.loads((result.log_directory / "game_complete.json").read_text())
    assert state["winner"] == result.winner
    assert len(state["players"]) == 8
    assert state["error_message"] == ""


def test_run_game_is_reproducible_for_same_seed(tmp_path) -> None:
    first = run_game(logs_dir=tmp_path / "first", seed=11, max_rounds=8)
    second = run_game(logs_dir=tmp_path / "second", seed=11, max_rounds=8)

    first_state = json.loads((first.log_directory / "game_complete.json").read_text())
    second_state = json.loads((second.log_directory / "game_complete.json").read_text())

    assert first.winner == second.winner
    assert first_state["players"] == second_state["players"]


def test_run_game_records_partial_log_when_max_rounds_is_exceeded(tmp_path) -> None:
    with pytest.raises(GameRunError) as error:
        run_game(logs_dir=tmp_path, seed=3, max_rounds=0)

    assert error.value.log_directory is not None
    partial_file = error.value.log_directory / "game_partial.json"
    assert partial_file.exists()

    state = json.loads(partial_file.read_text())
    assert "Maximum rounds exceeded" in state["error_message"]
