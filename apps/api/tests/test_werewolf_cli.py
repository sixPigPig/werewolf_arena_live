from app.cli import main


def test_run_game_command_prints_result(tmp_path, capsys) -> None:
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
    assert "winner=" in output
    assert "session_id=session_" in output
    assert "log_directory=" in output


def test_run_game_command_returns_nonzero_on_engine_failure(tmp_path, capsys) -> None:
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
