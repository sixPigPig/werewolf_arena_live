import base64
import json
from contextlib import nullcontext

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
from app.werewolf.orphan_reaper import OrphanRecoveryResult
from app.werewolf.private_memory_cleanup import PrivateMemoryCleanupResult
from app.werewolf.runner import GameRunError, RunGameResult
from app.werewolf.rules import (
    DEFAULT_RULE_SET_ID,
    freeze_rule_set_snapshot,
    get_rule_set,
)

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
    monkeypatch.delenv("ARK_AGENT_PLAN_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

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
    assert "rule_set_id" not in calls
    compiled = calls["compiled_rule_set"]
    assert compiled.rule_set.id == DEFAULT_RULE_SET_ID
    assert compiled.snapshot == freeze_rule_set_snapshot(
        get_rule_set(DEFAULT_RULE_SET_ID)
    )
    assert compiled.revision_id is None
    assert compiled.revision_no is None
    assert compiled.content_hash == (
        "00095728147a022c48eab88faf21a14567ad0afa13ab9418306e84ff85b10131"
    )


def test_run_game_command_defaults_to_agent_plan_when_plan_key_is_configured(
    tmp_path,
    capsys,
    monkeypatch,
) -> None:
    (tmp_path / ".env").write_text(
        "#DEEPSEEK_API_KEY=\n"
        "DEEPSEEK_MODEL=deepseek-v4-flash\n"
        "ARK_AGENT_PLAN_API_KEY=agent-plan-key\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEREWOLF_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("ARK_AGENT_PLAN_API_KEY", raising=False)
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
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
    assert calls["villager_model"] == "doubao-seed-2-0-lite-260215"
    assert calls["werewolf_model"] == "doubao-seed-2-0-lite-260215"


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


def test_redact_private_round_memory_defaults_to_dry_run(capsys, monkeypatch) -> None:
    calls: list[bool] = []

    class CleanupSession:
        def __init__(self) -> None:
            self.commits = 0
            self.rollbacks = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            self.rollbacks += 1

    db = CleanupSession()

    def fake_cleanup(_db: object, *, apply: bool) -> PrivateMemoryCleanupResult:
        calls.append(apply)
        return PrivateMemoryCleanupResult(
            applied=apply,
            run_count=2,
            event_count=3,
            voice_count=1,
            audio_chunk_count=4,
        )

    monkeypatch.setattr(cli, "SessionLocal", lambda: db)
    monkeypatch.setattr(cli, "cleanup_private_round_memory", fake_cleanup)

    exit_code = main(["redact-private-round-memory"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert calls == [False]
    assert db.commits == 0
    assert db.rollbacks == 1
    assert "模式=dry-run run=2 事件=3 语音=1 音频块=4 失败=0" in output
    assert "数据库未修改" in output


def test_redact_private_round_memory_apply_commits(capsys, monkeypatch) -> None:
    class CleanupSession:
        def __init__(self) -> None:
            self.commits = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            pass

    db = CleanupSession()
    monkeypatch.setattr(cli, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        cli,
        "cleanup_private_round_memory",
        lambda _db, *, apply: PrivateMemoryCleanupResult(
            applied=apply,
            run_count=1,
            event_count=1,
            voice_count=1,
            audio_chunk_count=1,
        ),
    )

    exit_code = main(["redact-private-round-memory", "--apply"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert db.commits == 1
    assert "模式=apply" in output
    assert "数据库未修改" not in output


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

    class FakeTelemetry:
        def __init__(self) -> None:
            self.started = False
            self.stopped = False

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.stopped = True

    telemetry = FakeTelemetry()

    def fake_worker(session_factory, **kwargs) -> int:
        calls["session_factory"] = session_factory
        calls.update(kwargs)
        kwargs["on_job"]("voice-job-1")
        return 1

    monkeypatch.setattr(cli, "run_voice_generation_worker", fake_worker)
    monkeypatch.setattr(
        cli,
        "RuntimeWorkerTelemetry",
        lambda *_args, **_kwargs: telemetry,
    )

    exit_code = main(["run-judge-voice-worker", "--once"])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "job_id=voice-job-1"
    assert calls["once"] is True
    assert calls["poll_seconds"] == 2.0
    assert telemetry.started is True
    assert telemetry.stopped is True


def test_voice_worker_rejects_unsafe_poll_interval(capsys) -> None:
    exit_code = main(["run-judge-voice-worker", "--poll-seconds", "0"])

    assert exit_code == 2
    assert "between 0.25 and 60" in capsys.readouterr().err


def test_voice_worker_probe_reports_fresh_and_stale(capsys, monkeypatch) -> None:
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(object()))
    monkeypatch.setattr(cli, "runtime_worker_is_alive", lambda *_args, **_kwargs: True)

    healthy = main(["check-judge-voice-worker"])
    assert healthy == 0
    assert capsys.readouterr().out.strip() == "judge_voice_worker=ok"

    monkeypatch.setattr(cli, "runtime_worker_is_alive", lambda *_args, **_kwargs: False)
    stale = main(["check-judge-voice-worker"])
    assert stale == 1
    assert capsys.readouterr().out.strip() == "judge_voice_worker=stale"


def test_live_run_reaper_once_reports_recovery(capsys, monkeypatch) -> None:
    calls = {}

    class FakeTelemetry:
        def __init__(self) -> None:
            self.started = False
            self.stopped = False
            self.results = []

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.stopped = True

        def record_scan(self) -> None:
            return None

        def record_recovery(self, result) -> None:
            self.results.append(result)

        def record_error(self, _code: str) -> None:
            return None

    telemetry = FakeTelemetry()

    def fake_reaper(session_factory, registry, **kwargs) -> int:
        calls["session_factory"] = session_factory
        calls["registry"] = registry
        calls.update(kwargs)
        kwargs["on_recovery"](
            OrphanRecoveryResult(
                run_id="run_123456789abc",
                session_id="game_1234abcd",
                attempt=2,
                outcome="resumed",
            )
        )
        return 1

    monkeypatch.setattr(cli, "run_live_run_reaper", fake_reaper)
    monkeypatch.setattr(cli, "RuntimeWorkerTelemetry", lambda *_args, **_kwargs: telemetry)

    exit_code = main(["run-live-run-reaper", "--once"])

    assert exit_code == 0
    assert capsys.readouterr().out.strip() == ("run_id=run_123456789abc outcome=resumed attempt=2")
    assert calls["once"] is True
    assert calls["poll_seconds"] == 5.0
    assert calls["stale_grace_seconds"] == 30.0
    assert calls["backoff_seconds"] == 30.0
    assert calls["max_attempts"] == 3
    assert calls["on_scan"] == telemetry.record_scan
    assert calls["on_error"] == telemetry.record_error
    assert telemetry.started is True
    assert telemetry.stopped is True
    assert len(telemetry.results) == 1


def test_live_run_reaper_rejects_unsafe_options(capsys) -> None:
    exit_code = main(["run-live-run-reaper", "--backoff-seconds", "1"])

    assert exit_code == 2
    assert "between 5 and 3600" in capsys.readouterr().err


def test_live_run_reaper_probe_reports_fresh_and_stale(capsys, monkeypatch) -> None:
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(object()))
    monkeypatch.setattr(cli, "live_run_reaper_is_alive", lambda *_args, **_kwargs: True)

    healthy = main(["check-live-run-reaper"])
    assert healthy == 0
    assert capsys.readouterr().out.strip() == "reaper=ok"

    monkeypatch.setattr(cli, "live_run_reaper_is_alive", lambda *_args, **_kwargs: False)
    stale = main(["check-live-run-reaper"])
    assert stale == 1
    assert capsys.readouterr().out.strip() == "reaper=stale"


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
                        "model_provider": "deepseek",
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
                        "model_provider": "deepseek",
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
                display_name="旧图玩家",
                model_provider="deepseek",
                model="deepseek-v4-flash",
                personality_id="balanced",
                personality_text="稳健推进。",
                appearance_id="default",
                avatar_image_url="/api/v1/player-profiles/avatar/legacy.png",
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
    assert assets[0].data_base64 == base64.b64encode(PNG_BYTES).decode("ascii")


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
                    display_name=profile_id,
                    model_provider="deepseek",
                    model="deepseek-v4-flash",
                    personality_id="balanced",
                    personality_text="稳健推进。",
                    appearance_id="default",
                    avatar_image_url=f"/api/v1/player-profiles/avatar/{filename}",
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
                        "model_provider": "deepseek",
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
