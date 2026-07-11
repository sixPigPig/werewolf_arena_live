import json

from sqlalchemy import create_engine, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.cli as cli
from app.cli import main
from app.db.base import Base
from app.models.player_avatar_asset import PlayerAvatarAsset
from app.models.user import User
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.werewolf.runner import GameRunError, RunGameResult

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
)


class FakeSession:
    def close(self) -> None:
        pass


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
        return RunGameResult(winner="狼人阵营", session_id="game_1200abcd")

    monkeypatch.setattr("app.cli.run_game", fake_run_game)
    monkeypatch.setattr(cli, "SessionLocal", lambda: FakeSession())

    exit_code = main(["run-game", "--seed", "13", "--max-rounds", "8"])

    output = capsys.readouterr().out

    assert exit_code == 0
    assert output.strip().splitlines() == [
        "胜利阵营=狼人阵营",
        "session_id=game_1200abcd",
    ]
    assert "record_store" in calls
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
        return RunGameResult(winner="狼人阵营", session_id="game_1200abcd")

    monkeypatch.setattr("app.cli.run_game", fake_run_game)
    monkeypatch.setattr(cli, "SessionLocal", lambda: FakeSession())

    exit_code = main(["run-game", "--seed", "13", "--max-rounds", "8"])

    capsys.readouterr()

    assert exit_code == 0
    assert "record_store" in calls
    assert calls["villager_model"] == "MiniMax-M2.7"
    assert calls["werewolf_model"] == "MiniMax-M2.7"


def test_run_game_command_returns_nonzero_on_engine_failure(capsys, monkeypatch) -> None:
    def fake_run_game(**kwargs) -> RunGameResult:
        raise GameRunError("Maximum rounds exceeded", "game_failed")

    monkeypatch.setattr("app.cli.run_game", fake_run_game)
    monkeypatch.setattr(cli, "SessionLocal", lambda: FakeSession())

    exit_code = main(["run-game", "--seed", "13", "--max-rounds", "0"])

    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Maximum rounds exceeded" in captured.err
    assert "session_id=game_failed" in captured.err


def test_purge_legacy_game_records_dry_run_lists_matches(tmp_path, capsys) -> None:
    (tmp_path / "game_1200abcd").mkdir()
    (tmp_path / "not-a-game").mkdir()
    (tmp_path / "player_profiles.json").write_text("{}", encoding="utf-8")

    exit_code = main(["purge-legacy-game-records", "--logs-dir", str(tmp_path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "匹配=1 删除=0" in output
    assert (tmp_path / "game_1200abcd").exists()
    assert (tmp_path / "not-a-game").exists()
    assert (tmp_path / "player_profiles.json").exists()


def test_purge_legacy_game_records_deletes_only_matching_directories(tmp_path, capsys) -> None:
    (tmp_path / "game_1200abcd").mkdir()
    (tmp_path / "game_bad").mkdir()
    (tmp_path / "player_profile_assets").mkdir()
    (tmp_path / "player_profiles.json").write_text("{}", encoding="utf-8")
    target = tmp_path / "outside"
    target.mkdir()
    (tmp_path / "game_ffffffff").symlink_to(target, target_is_directory=True)

    exit_code = main(["purge-legacy-game-records", "--logs-dir", str(tmp_path), "--yes"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "匹配=1 删除=1 跳过=1" in output
    assert not (tmp_path / "game_1200abcd").exists()
    assert (tmp_path / "game_bad").exists()
    assert (tmp_path / "player_profile_assets").exists()
    assert (tmp_path / "player_profiles.json").exists()
    assert (tmp_path / "game_ffffffff").is_symlink()
    assert target.exists()


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


def test_voice_worker_once_reports_claimed_job(capsys, monkeypatch) -> None:
    calls = {}

    def fake_worker(session_factory, **kwargs) -> int:
        calls["session_factory"] = session_factory
        calls.update(kwargs)
        kwargs["on_job"]("voice-job-1")
        return 1

    monkeypatch.setattr(cli, "run_voice_generation_worker", fake_worker)

    exit_code = main(["run-judge-voice-worker", "--once"])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "job_id=voice-job-1"
    assert calls["once"] is True
    assert calls["poll_seconds"] == 2.0


def test_voice_worker_rejects_unsafe_poll_interval(capsys) -> None:
    exit_code = main(["run-judge-voice-worker", "--poll-seconds", "0"])

    assert exit_code == 2
    assert "between 0.25 and 60" in capsys.readouterr().err


def test_provision_admin_user_creates_and_updates_authorized_account(
    capsys,
    monkeypatch,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cli, "SessionLocal", testing_session, raising=False)

    first = main(
        [
            "provision-admin-user",
            "--email",
            "Admin@Example.Test",
            "--display-name",
            "OIDC Admin",
            "--role",
            "viewer",
        ]
    )
    first_output = capsys.readouterr().out
    second = main(
        [
            "provision-admin-user",
            "--email",
            "admin@example.test",
            "--display-name",
            "Arena Operator",
            "--role",
            "operator",
        ]
    )
    second_output = capsys.readouterr().out

    with testing_session() as db:
        users = list(db.scalars(select(User)))

    assert first == second == 0
    assert "action=created role=viewer" in first_output
    assert "action=updated role=operator" in second_output
    assert len(users) == 1
    assert users[0].email == "admin@example.test"
    assert users[0].display_name == "Arena Operator"
    assert users[0].admin_role == "operator"


def test_evaluate_replay_command_prints_issue_codes(tmp_path, capsys) -> None:
    replay = {
        "session_id": "game_eval",
        "winner": "",
        "players": [],
        "rounds": [
            {
                "number": 1,
                "summaries": {"10号玩家": "我作为10号狼人。"},
                "private_summaries": {},
                "debate": [],
                "sheriff_speeches": [],
            }
        ],
    }
    path = tmp_path / "game_complete.json"
    path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")

    exit_code = main(["evaluate-replay", "--source", str(path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "session_id=game_eval" in output
    assert "private_summary_leak" in output


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

        def query(self, *_args: object) -> "FailingSession":
            return self

        def scalar(self) -> int:
            return 0

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


def test_migrate_player_avatar_assets_command_imports_legacy_files(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cli, "SessionLocal", testing_session, raising=False)
    asset_dir = tmp_path / "player_profile_assets"
    asset_dir.mkdir()
    (asset_dir / "legacy.png").write_bytes(PNG_BYTES)
    with testing_session() as session:
        session.add(
            VirtualPlayerProfile(
                id="legacy-profile",
                owner_user_id=None,
                display_name="旧图玩家",
                model="deepseek-v4-flash",
                personality_id="balanced",
                personality_text="稳健推进。",
                appearance_id="default",
                avatar_prompt="",
                avatar_image_url="/api/v1/player-profiles/avatar/legacy.png",
                avatar_image_path="",
                avatar_image_mime="image/png",
                tags=[],
            )
        )
        session.commit()

    exit_code = main(["migrate-player-avatar-assets", "--logs-dir", str(tmp_path)])
    output = capsys.readouterr().out

    with testing_session() as session:
        profile = session.get(VirtualPlayerProfile, "legacy-profile")
        assets = session.query(PlayerAvatarAsset).all()

    assert exit_code == 0
    assert "扫描=1 导入=1 复用=0 缺失=0 回填=1" in output
    assert profile is not None
    assert profile.avatar_asset_id == assets[0].id
    assert assets[0].source == "migrated"
    assert assets[0].data == PNG_BYTES


def test_migrate_player_avatar_assets_command_reuses_and_counts_missing_files(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(cli, "SessionLocal", testing_session, raising=False)
    asset_dir = tmp_path / "player_profile_assets"
    asset_dir.mkdir()
    (asset_dir / "shared.png").write_bytes(PNG_BYTES)
    with testing_session() as session:
        for profile_id, filename in (
            ("legacy-profile-a", "shared.png"),
            ("legacy-profile-b", "shared.png"),
            ("missing-profile", "missing.png"),
        ):
            session.add(
                VirtualPlayerProfile(
                    id=profile_id,
                    owner_user_id=None,
                    display_name=profile_id,
                    model="deepseek-v4-flash",
                    personality_id="balanced",
                    personality_text="稳健推进。",
                    appearance_id="default",
                    avatar_prompt="",
                    avatar_image_url=f"/api/v1/player-profiles/avatar/{filename}",
                    avatar_image_path="",
                    avatar_image_mime="image/png",
                    tags=[],
                )
            )
        session.commit()

    exit_code = main(["migrate-player-avatar-assets", "--logs-dir", str(tmp_path)])
    output = capsys.readouterr().out

    with testing_session() as session:
        profile_a = session.get(VirtualPlayerProfile, "legacy-profile-a")
        profile_b = session.get(VirtualPlayerProfile, "legacy-profile-b")
        missing_profile = session.get(VirtualPlayerProfile, "missing-profile")
        assets = session.query(PlayerAvatarAsset).all()

    assert exit_code == 0
    assert "扫描=3 导入=1 复用=1 缺失=1 回填=2" in output
    assert len(assets) == 1
    assert profile_a is not None
    assert profile_b is not None
    assert missing_profile is not None
    assert profile_a.avatar_asset_id == profile_b.avatar_asset_id == assets[0].id
    assert missing_profile.avatar_asset_id is None
    assert missing_profile.avatar_image_url == "/api/v1/player-profiles/avatar/missing.png"


def test_import_player_profiles_maps_legacy_system_avatar_to_asset_id(
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
                        "id": "legacy-system-profile",
                        "display_name": "内设旧图",
                        "model": "deepseek-v4-flash",
                        "appearance_id": "default",
                        "avatar_image_url": "/player-avatars/gothic-female-1.png",
                        "avatar_image_mime": "image/png",
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

    exit_code = main(["import-player-profiles", "--source", str(source)])
    capsys.readouterr()

    with testing_session() as session:
        imported = session.get(VirtualPlayerProfile, "legacy-system-profile")

    assert exit_code == 0
    assert imported is not None
    assert imported.avatar_asset_id == "system-gothic-female-1"
    assert imported.avatar_image_url == (
        "/api/v1/player-profiles/avatar-assets/system-gothic-female-1"
    )
