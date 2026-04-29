from pathlib import Path

from app.cli import main
from app.werewolf.runner import GameRunError, RunGameResult


def test_run_game_command_defaults_to_deepseek_and_prints_chinese_result(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    calls = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEREWOLF_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)

    def fake_run_game(**kwargs) -> RunGameResult:
        calls.update(kwargs)
        return RunGameResult(
            winner="狼人阵营",
            session_id="session_test",
            log_directory=Path(tmp_path) / "session_test",
        )

    monkeypatch.setattr("app.cli.run_game", fake_run_game)

    exit_code = main(
        [
            "run-game",
            "--logs-dir",
            str(tmp_path),
            "--seed",
            "13",
            "--max-rounds",
            "8",
        ]
    )

    output = capsys.readouterr().out

    assert exit_code == 0
    assert "胜利阵营=狼人阵营" in output
    assert "session_id=session_test" in output
    assert "日志目录=" in output
    assert calls["villager_model"] == "deepseek-chat"
    assert calls["werewolf_model"] == "deepseek-chat"


def test_run_game_command_defaults_to_minimax_when_only_minimax_key_is_configured(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    (tmp_path / ".env").write_text(
        "#DEEPSEEK_API_KEY=\n"
        "DEEPSEEK_MODEL=deepseek-chat\n"
        "MINIMAX_API_KEY=minimax-key\n"
        "MINIMAX_MODEL=MiniMax-M2.7\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEREWOLF_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    calls = {}

    def fake_run_game(**kwargs) -> RunGameResult:
        calls.update(kwargs)
        return RunGameResult(
            winner="狼人阵营",
            session_id="session_test",
            log_directory=Path(tmp_path) / "session_test",
        )

    monkeypatch.setattr("app.cli.run_game", fake_run_game)

    exit_code = main(
        [
            "run-game",
            "--logs-dir",
            str(tmp_path),
            "--seed",
            "13",
            "--max-rounds",
            "8",
        ]
    )

    capsys.readouterr()

    assert exit_code == 0
    assert calls["villager_model"] == "MiniMax-M2.7"
    assert calls["werewolf_model"] == "MiniMax-M2.7"


def test_run_game_command_returns_nonzero_on_engine_failure(tmp_path, capsys, monkeypatch) -> None:
    def fake_run_game(**kwargs) -> RunGameResult:
        raise GameRunError("Maximum rounds exceeded", Path(kwargs["logs_dir"]) / "failed")

    monkeypatch.setattr("app.cli.run_game", fake_run_game)

    exit_code = main(
        [
            "run-game",
            "--logs-dir",
            str(tmp_path),
            "--seed",
            "13",
            "--max-rounds",
            "0",
        ]
    )

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Maximum rounds exceeded" in captured.err


def test_serve_command_starts_uvicorn(monkeypatch) -> None:
    calls = {}

    def fake_run(app_path: str, *, host: str, port: int, reload: bool) -> None:
        calls["app_path"] = app_path
        calls["host"] = host
        calls["port"] = port
        calls["reload"] = reload

    monkeypatch.setattr("app.cli.uvicorn.run", fake_run)

    exit_code = main(["serve", "--host", "0.0.0.0", "--port", "9000", "--reload"])

    assert exit_code == 0
    assert calls == {
        "app_path": "app.main:app",
        "host": "0.0.0.0",
        "port": 9000,
        "reload": True,
    }
