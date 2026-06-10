import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.cli as cli
from app.cli import main
from app.db.base import Base
from app.models.virtual_player_profile import VirtualPlayerProfile
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
    assert calls["villager_model"] == "deepseek-v4-flash"
    assert calls["werewolf_model"] == "deepseek-v4-flash"


def test_run_game_command_defaults_to_minimax_when_only_minimax_key_is_configured(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    (tmp_path / ".env").write_text(
        "#DEEPSEEK_API_KEY=\n"
        "DEEPSEEK_MODEL=deepseek-v4-flash\n"
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


def test_import_player_profiles_command_is_idempotent(tmp_path, capsys, monkeypatch) -> None:
    source = tmp_path / "player_profiles.json"
    source.write_text(
        json.dumps(
            {
                "version": 3,
                "profiles": [
                    {
                        "id": "legacy-profile",
                        "display_name": "旧档玩家",
                        "model": "deepseek-v4-flash",
                        "personality_id": "cautious",
                        "personality_text": "先听后判。",
                        "appearance_id": "moonlit",
                        "tags": ["本地"],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cli, "SessionLocal", testing_session, raising=False)

    first_exit_code = main(["import-player-profiles", "--source", str(source)])
    first_output = capsys.readouterr().out
    second_exit_code = main(["import-player-profiles", "--source", str(source)])
    second_output = capsys.readouterr().out

    with testing_session() as session:
        imported = session.get(VirtualPlayerProfile, "legacy-profile")

    assert first_exit_code == 0
    assert "读取=1 导入=1 跳过=0" in first_output
    assert second_exit_code == 0
    assert "读取=1 导入=0 跳过=1" in second_output
    assert imported is not None
    assert imported.display_name == "旧档玩家"
    assert imported.personality_text == "先听后判。"
    assert imported.tags == ["本地"]


def test_import_player_profiles_command_rejects_missing_malformed_or_empty_files(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cli, "SessionLocal", testing_session, raising=False)
    missing = tmp_path / "missing.json"
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{not-json", encoding="utf-8")
    empty = tmp_path / "empty.json"
    empty.write_text('{"version":3,"profiles":[]}', encoding="utf-8")

    missing_exit_code = main(["import-player-profiles", "--source", str(missing)])
    missing_error = capsys.readouterr().err
    malformed_exit_code = main(["import-player-profiles", "--source", str(malformed)])
    malformed_error = capsys.readouterr().err
    empty_exit_code = main(["import-player-profiles", "--source", str(empty)])
    empty_error = capsys.readouterr().err

    assert missing_exit_code == 1
    assert "无法读取玩家档案文件" in missing_error
    assert malformed_exit_code == 1
    assert "无法读取玩家档案文件" in malformed_error
    assert empty_exit_code == 1
    assert "没有可导入的玩家档案" in empty_error


def test_import_player_profiles_command_rolls_back_database_failure(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    source = tmp_path / "player_profiles.json"
    source.write_text(
        json.dumps(
            {
                "version": 3,
                "profiles": [
                    {
                        "id": "legacy-profile",
                        "display_name": "旧档玩家",
                        "model": "deepseek-v4-flash",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class FailingSession:
        def __init__(self) -> None:
            self.rolled_back = False

        def get(self, *_args: object) -> None:
            return None

        def add(self, _value: object) -> None:
            pass

        def commit(self) -> None:
            raise OperationalError("commit", {}, Exception("database unavailable"))

        def rollback(self) -> None:
            self.rolled_back = True

        def close(self) -> None:
            pass

    session = FailingSession()
    monkeypatch.setattr(cli, "SessionLocal", lambda: session, raising=False)

    exit_code = main(["import-player-profiles", "--source", str(source)])
    error = capsys.readouterr().err

    assert exit_code == 1
    assert "导入玩家档案失败" in error
    assert session.rolled_back is True
