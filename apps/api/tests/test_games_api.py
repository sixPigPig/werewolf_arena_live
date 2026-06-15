import json
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes.games import (
    _run_game_in_background,
    get_live_registry,
    get_replay_store,
)
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.user import User
from app.models.virtual_player_profile import VirtualPlayerProfile
from app.werewolf.checkpoint import CHECKPOINT_SCHEMA_VERSION, RESUME_CHECKPOINT_FILE
from app.werewolf.live import LiveRunRegistry
from app.werewolf.player_presets import default_personality_text
from app.werewolf.replay import ReplayStore


engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base.metadata.create_all(engine)

client = TestClient(app)


class BrokenSession:
    def get(self, *_args: object) -> None:
        raise OperationalError("select", {}, Exception("database unavailable"))

    def query(self, *_args: object) -> None:
        raise OperationalError("select", {}, Exception("database unavailable"))

    def close(self) -> None:
        pass


def override_broken_db() -> Generator[BrokenSession, None, None]:
    yield BrokenSession()


def override_get_db() -> Generator[Session, None, None]:
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def isolated_db() -> Generator[None, None, None]:
    app.dependency_overrides[get_db] = override_get_db
    with TestingSessionLocal() as session:
        session.query(VirtualPlayerProfile).delete()
        session.query(User).delete()
        session.commit()
    yield
    app.dependency_overrides.clear()
    with TestingSessionLocal() as session:
        session.query(VirtualPlayerProfile).delete()
        session.query(User).delete()
        session.commit()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def override_logs_root(tmp_path: Path) -> None:
    app.dependency_overrides[get_replay_store] = lambda: ReplayStore(tmp_path)


def override_live_registry(registry: LiveRunRegistry) -> None:
    app.dependency_overrides[get_live_registry] = lambda: registry


def clear_overrides() -> None:
    app.dependency_overrides.clear()


def add_virtual_profiles(count: int, *, prefix: str = "profile") -> list[str]:
    profile_ids = [f"{prefix}-{index}" for index in range(1, count + 1)]
    with TestingSessionLocal() as session:
        session.add_all(
            [
                VirtualPlayerProfile(
                    id=profile_id,
                    display_name=f"虚拟玩家{index}",
                    model="profile-model",
                    personality_id="balanced",
                    personality_text="稳健推进。",
                    appearance_id="default",
                    avatar_prompt="",
                    tags=[],
                )
                for index, profile_id in enumerate(profile_ids, start=1)
            ]
        )
        session.commit()
    return profile_ids


class ImmediateThread:
    def __init__(self, *, target, kwargs, daemon):
        self.target = target
        self.kwargs = kwargs
        self.daemon = daemon

    def start(self) -> None:
        self.target(**self.kwargs)


def sample_state(session_id: str, *, winner: str = "狼人阵营", error: str = "") -> dict:
    return {
        "session_id": session_id,
        "players": [
            {"name": "张三", "role": "狼人", "model": "deepseek-chat", "observations": []},
            {"name": "李四", "role": "村民", "model": "deepseek-chat", "observations": []},
        ],
        "rounds": [
            {
                "number": 1,
                "players": ["张三", "李四"],
                "eliminated": "李四",
                "protected": None,
                "investigated": "张三",
                "exiled": None,
                "debate": [],
                "bids": [{"张三": 3}],
                "votes": [{"张三": "李四"}],
                "summaries": {"张三": "我会隐藏身份。"},
                "success": True,
            }
        ],
        "winner": winner,
        "error_message": error,
    }


def sample_logs() -> list[dict]:
    return [
        {
            "number": 1,
            "eliminate": {
                "actor": "张三",
                "action": "remove",
                "options": ["李四"],
                "choice": "李四",
                "lm_log": {
                    "prompt": "请选择今晚击杀对象。",
                    "raw_response": '{"choice":"李四"}',
                    "parsed": {"choice": "李四"},
                },
            },
            "protect": None,
            "investigate": None,
            "bid": [],
            "debate": [],
            "votes": [],
            "summaries": [],
        }
    ]


def test_list_rule_sets_returns_official_rules() -> None:
    response = client.get("/api/v1/games/rule-sets")

    assert response.status_code == 200
    payload = response.json()
    assert [rule["id"] for rule in payload["rule_sets"]] == [
        "classic_8",
        "starter_6",
        "social_8",
        "classic_12_seer_witch_hunter_idiot",
    ]
    assert payload["rule_sets"][0]["role_summary"] == "2 狼人 / 1 预言家 / 1 守卫 / 4 村民"
    assert any(
        rule["id"] == "classic_12_seer_witch_hunter_idiot"
        for rule in payload["rule_sets"]
    )


def test_list_model_options_returns_configured_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEREWOLF_DEFAULT_MODEL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-test")
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-Test")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")
    monkeypatch.setenv("DASHSCOPE_MODEL", "qwen-test")

    response = client.get("/api/v1/games/model-options")

    assert response.status_code == 200
    assert response.json() == {
        "models": [
            {"id": "deepseek-test", "label": "DeepSeek · deepseek-test"},
            {"id": "MiniMax-Test", "label": "MiniMax · MiniMax-Test"},
            {"id": "qwen-test", "label": "Qwen · qwen-test"},
        ]
    }


def test_list_model_options_prefers_default_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEREWOLF_DEFAULT_MODEL", "MiniMax-Test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-test")
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-key")
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-Test")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    response = client.get("/api/v1/games/model-options")

    assert response.status_code == 200
    assert response.json() == {
        "models": [
            {"id": "MiniMax-Test", "label": "MiniMax · MiniMax-Test"},
            {"id": "deepseek-test", "label": "DeepSeek · deepseek-test"},
        ]
    }


def test_list_model_options_falls_back_to_default_without_keys(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WEREWOLF_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

    response = client.get("/api/v1/games/model-options")

    assert response.status_code == 200
    assert response.json() == {
        "models": [
            {"id": "deepseek-v4-flash", "label": "默认模型 · deepseek-v4-flash"}
        ]
    }


def test_create_game_run_accepts_rule_set_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(6)
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"rule_set_id": "starter_6", "seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    payload = response.json()
    assert payload["rule_set"]["id"] == "starter_6"
    assert captured[0]["rule_set_id"] == "starter_6"


def test_create_game_run_randomly_fills_profiles_when_no_lineup_selected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(6)
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"rule_set_id": "starter_6", "seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    configs = response.json()["player_configs"]
    assert [config["seat"] for config in configs] == [1, 2, 3, 4, 5, 6]
    assert {config["profile_id"] for config in configs} == {
        f"profile-{index}" for index in range(1, 7)
    }
    assert len({config["name"] for config in configs}) == 6
    assert [config.to_dict() for config in captured[0]["player_configs"]] == configs


def test_create_game_run_returns_lineup_quality_warnings_for_homogeneous_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(6)
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)

    def fake_background_run(**kwargs: object) -> None:
        del kwargs

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"rule_set_id": "starter_6", "seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    warnings = response.json()["lineup_quality_warnings"]
    assert warnings[0]["code"] == "homogeneous_personality_lineup"


def test_create_game_run_rejects_when_player_library_is_too_small(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(1)
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"rule_set_id": "classic_8", "seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Player profile library has 1 available players, but 8 seats require virtual players"
    )
    assert captured == []


def test_create_game_run_defaults_to_minimax_when_only_minimax_key_is_configured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
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

    registry = LiveRunRegistry()
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post("/api/v1/games/runs", json={"seed": 21, "max_rounds": 1})
    finally:
        clear_overrides()

    assert response.status_code == 201
    payload = response.json()
    assert payload["villager_model"] == "MiniMax-M2.7"
    assert payload["werewolf_model"] == "MiniMax-M2.7"
    assert captured[0]["villager_model"] == "MiniMax-M2.7"
    assert captured[0]["werewolf_model"] == "MiniMax-M2.7"


def test_create_game_run_rejects_unknown_rule_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"rule_set_id": "missing_rule", "seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown rule set: missing_rule"


def test_create_game_run_resolves_profile_configs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestingSessionLocal() as session:
        session.add(
            VirtualPlayerProfile(
                id="profile-alpha",
                display_name="控场位",
                model="profile-model",
                personality_id="cautious",
                personality_text="谨慎控场，避免过早暴露身份。",
                appearance_id="moonlit",
                avatar_prompt="silver moon portrait",
                avatar_image_url="/api/v1/player-profiles/avatar/profile-alpha.png",
                tags=["控场"],
            )
        )
        session.commit()
    add_virtual_profiles(7)

    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "seed": 21,
                "max_rounds": 1,
                "player_configs": [
                    {
                        "seat": 2,
                        "profile_id": "profile-alpha",
                        "name": "覆盖名",
                        "personality_id": "aggressive",
                        "appearance_id": "crimson",
                        "tags": ["压迫", "控场"],
                    }
                ],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    configs = response.json()["player_configs"]
    snapshot = next(config for config in configs if config["seat"] == 2)
    expected_personality = "\n".join(
        [
            default_personality_text("aggressive"),
            "狼人杀策略: 稳健观察，按证据推进，不轻易极端站边。",
            "冒险倾向: 3/5",
            "伪装倾向: 3/5",
            "信任倾向: 3/5",
            "领导倾向: 3/5",
            "发言活跃: 3/5",
        ]
    )
    assert snapshot == {
        "seat": 2,
        "profile_id": "profile-alpha",
        "name": "覆盖名",
        "model": "profile-model",
        "personality_id": "aggressive",
        "personality": expected_personality,
        "appearance_id": "crimson",
        "avatar_prompt": "silver moon portrait",
        "avatar_image_url": "/api/v1/player-profiles/avatar/profile-alpha.png",
        "tags": ["压迫", "控场"],
    }
    background_configs = captured[0]["player_configs"]
    assert len(background_configs) == 8
    assert snapshot in [config.to_dict() for config in background_configs]


def test_create_game_run_returns_503_when_profile_database_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    app.dependency_overrides[get_db] = override_broken_db
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "seed": 21,
                "max_rounds": 1,
                "player_configs": [{"seat": 2, "profile_id": "profile-file"}],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 503
    assert response.json() == {"detail": "Player profile database unavailable"}
    assert captured == []


def test_game_run_player_config_composes_rich_profile_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "控场样本",
            "model": "deepseek-v4-flash",
            "personality_id": "analytical",
            "personality_text": "先找矛盾，再给站边。",
            "short_description": "逻辑控场玩家",
            "speaking_style": "发言会分点列证据。",
            "catchphrases": ["我先拆一下视角"],
            "strategy_profile": "logic_leader",
            "leadership_tendency": 5,
            "talkativeness": 4,
            "example_messages": ["我觉得 2 号的视角漏掉了昨晚信息。"],
        },
    ).json()
    add_virtual_profiles(7)
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "classic_8",
                "player_configs": [{"seat": 1, "profile_id": created["id"]}],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    config = next(item for item in response.json()["player_configs"] if item["seat"] == 1)
    assert config["name"] == "控场样本"
    assert "先找矛盾，再给站边。" in config["personality"]
    assert "逻辑控场玩家" in config["personality"]
    assert "我先拆一下视角" in config["personality"]
    assert "领导倾向: 5/5" in config["personality"]
    assert config in [item.to_dict() for item in captured[0]["player_configs"]]


def test_game_run_player_config_keeps_explicit_personality_text_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post(
        "/api/v1/player-profiles",
        json={
            "display_name": "覆盖样本",
            "model": "deepseek-v4-flash",
            "personality_id": "analytical",
            "personality_text": "先找矛盾，再给站边。",
            "short_description": "这段不应进入运行配置",
            "catchphrases": ["这句也不应进入"],
            "leadership_tendency": 5,
        },
    ).json()
    add_virtual_profiles(7)
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "rule_set_id": "classic_8",
                "player_configs": [
                    {
                        "seat": 1,
                        "profile_id": created["id"],
                        "personality_text": "只使用运行时覆盖。",
                    }
                ],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    config = next(item for item in response.json()["player_configs"] if item["seat"] == 1)
    assert config["personality"] == "只使用运行时覆盖。"
    assert config in [item.to_dict() for item in captured[0]["player_configs"]]


def test_create_game_run_rejects_duplicate_effective_player_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_background_run(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "seed": 21,
                "max_rounds": 1,
                "player_configs": [
                    {"seat": 1, "profile_id": "profile-1", "name": "同名玩家"},
                    {"seat": 2, "profile_id": "profile-2", "name": "同名玩家"},
                ],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 422
    assert response.json()["detail"] == "Duplicate player name: 同名玩家"
    assert captured == []


def test_create_game_run_rejects_missing_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={
                "seed": 21,
                "max_rounds": 1,
                "player_configs": [{"seat": 1, "profile_id": "missing"}],
            },
        )
    finally:
        clear_overrides()

    assert response.status_code == 422
    assert response.json()["detail"] == "Unknown player profile: missing"


def test_resume_game_run_creates_live_run_from_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "game_1200abcd"
    write_json(
        tmp_path / session_id / RESUME_CHECKPOINT_FILE,
        {
            "schema_version": 1,
            "session_id": session_id,
            "run_params": {
                "villager_model": "Qwen3.6-Plus",
                "werewolf_model": "MiniMax-M2.7",
                "seed": 21,
                "max_rounds": 8,
                "rule_set_id": "starter_6",
                "player_configs": [
                    {
                        "seat": 2,
                        "profile_id": "profile-alpha",
                        "name": "控场位",
                        "model": "profile-model",
                        "personality_id": "cautious",
                        "personality": "谨慎控场。",
                        "appearance_id": "moonlit",
                        "avatar_prompt": "silver moon portrait",
                        "avatar_image_url": "/api/v1/player-profiles/avatar/profile-alpha.png",
                        "tags": ["控场"],
                    }
                ],
            },
            "round_number": 1,
            "active_players": ["张三", "李四"],
            "rng_state": None,
            "state_at_round_start": sample_state(session_id, winner="", error=""),
            "logs_before_round": [],
            "cached_model_responses": [],
            "failed_request": None,
            "last_error": None,
        },
    )
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_resume_background(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._resume_game_in_background", fake_resume_background)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(f"/api/v1/games/{session_id}/resume")
    finally:
        clear_overrides()

    assert response.status_code == 201
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["villager_model"] == "Qwen3.6-Plus"
    assert payload["werewolf_model"] == "MiniMax-M2.7"
    assert payload["rule_set"]["id"] == "starter_6"
    assert payload["player_configs"] == [
        {
            "seat": 2,
            "profile_id": "profile-alpha",
            "name": "控场位",
            "model": "profile-model",
            "personality_id": "cautious",
            "personality": "谨慎控场。",
            "appearance_id": "moonlit",
            "avatar_prompt": "silver moon portrait",
            "avatar_image_url": "/api/v1/player-profiles/avatar/profile-alpha.png",
            "tags": ["控场"],
        }
    ]
    assert captured[0]["session_id"] == session_id
    assert captured[0]["logs_dir"] == tmp_path


def test_resume_game_run_reuses_active_run_without_starting_another_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "game_1200abcd"
    write_json(
        tmp_path / session_id / RESUME_CHECKPOINT_FILE,
        {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "session_id": session_id,
            "run_params": {
                "villager_model": "deepseek-chat",
                "werewolf_model": "deepseek-chat",
                "seed": 21,
                "max_rounds": 8,
                "rule_set_id": "starter_6",
                "player_configs": [],
            },
            "round_number": 1,
            "active_players": ["张三", "李四"],
            "rng_state": None,
            "state_at_round_start": sample_state(session_id, winner="", error=""),
            "logs_before_round": [],
            "cached_model_responses": [],
            "failed_request": None,
            "last_error": None,
        },
    )
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    captured: list[dict[str, object]] = []

    def fake_resume_background(**kwargs: object) -> None:
        captured.append(kwargs)

    monkeypatch.setattr("app.api.routes.games._resume_game_in_background", fake_resume_background)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        first_response = client.post(f"/api/v1/games/{session_id}/resume")
        second_response = client.post(f"/api/v1/games/{session_id}/resume")
    finally:
        clear_overrides()

    assert first_response.status_code == 201
    assert second_response.status_code == 200
    assert second_response.json()["run_id"] == first_response.json()["run_id"]
    assert len(captured) == 1


def test_resume_game_run_returns_404_without_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post("/api/v1/games/game_1200abcd/resume")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"] == "Resume checkpoint not found"


def test_list_games_includes_rule_set_summary(tmp_path: Path) -> None:
    session_id = "game_05095066"
    state = sample_state(session_id)
    state["rule_set"] = {
        "id": "social_8",
        "version": "2026.04",
        "name": "无神职心理局",
        "player_count": 8,
        "roles": [{"role": "狼人", "count": 2}, {"role": "村民", "count": 6}],
    }
    write_json(tmp_path / session_id / "game_complete.json", state)
    override_logs_root(tmp_path)

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json()["sessions"][0]["rule_set"]["id"] == "social_8"


def test_create_game_run_returns_run_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    add_virtual_profiles(8)
    registry = LiveRunRegistry()
    override_logs_root(tmp_path)
    override_live_registry(registry)
    started: list[str] = []

    def fake_background_run(**kwargs: object) -> None:
        started.append(str(kwargs["run_id"]))

    monkeypatch.setattr("app.api.routes.games._run_game_in_background", fake_background_run)
    monkeypatch.setattr("app.api.routes.games.threading.Thread", ImmediateThread)

    try:
        response = client.post(
            "/api/v1/games/runs",
            json={"seed": 21, "max_rounds": 1},
        )
    finally:
        clear_overrides()

    assert response.status_code == 201
    payload = response.json()
    assert payload["run_id"].startswith("run_")
    assert payload["session_id"].startswith("game_")
    assert payload["status"] in {"queued", "running", "completed", "failed"}
    assert payload["event_count"] >= 1
    assert started == [payload["run_id"]]


def test_get_game_run_returns_404_for_missing_run() -> None:
    registry = LiveRunRegistry()
    override_live_registry(registry)

    try:
        response = client.get("/api/v1/games/runs/run_missing")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"] == "Game run not found"


def test_run_game_in_background_publishes_registry_and_engine_events_directly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
    )

    def fake_run_game(*, event_sink, **kwargs: object) -> SimpleNamespace:
        event_sink.publish("phase_started", phase="night")
        return SimpleNamespace(winner="狼人阵营")

    monkeypatch.setattr("app.api.routes.games.run_game", fake_run_game)
    monkeypatch.setattr("app.api.routes.games.settings.werewolf_logs_dir", str(tmp_path))

    _run_game_in_background(
        run_id=run.run_id,
        registry=registry,
        session_id=run.session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        rule_set_id="classic_8",
    )

    assert [event.type for event in registry.events_after(run.run_id)] == [
        "run_created",
        "run_started",
        "phase_started",
        "game_completed",
    ]


def test_game_run_events_replays_existing_events() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        rule_set_id="classic_8",
        rule_set={
            "id": "classic_8",
            "version": "2026.04",
            "name": "经典 8 人局",
            "player_count": 8,
            "roles": [],
        },
    )
    registry.publish(run.run_id, "game_started", payload={"players": []})
    registry.mark_completed(run.run_id, winner="狼人阵营")
    override_live_registry(registry)

    try:
        response = client.get(f"/api/v1/games/runs/{run.run_id}/events")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    body = response.text
    assert "event: run_created" in body
    assert "event: game_started" in body
    assert "event: game_completed" in body


def test_game_run_events_honors_after_id_query() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        rule_set_id="classic_8",
        rule_set={
            "id": "classic_8",
            "version": "2026.04",
            "name": "经典 8 人局",
            "player_count": 8,
            "roles": [],
        },
    )
    registry.publish(run.run_id, "game_started", payload={"players": []})
    registry.publish(run.run_id, "round_started", round_number=1, payload={"round": 1})
    registry.mark_completed(run.run_id, winner="狼人阵营")
    override_live_registry(registry)

    try:
        response = client.get(f"/api/v1/games/runs/{run.run_id}/events?after_id=2")
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.text
    assert "id: 1" not in body
    assert "id: 2" not in body
    assert "event: run_created" not in body
    assert "event: game_started" not in body
    assert "id: 3" in body
    assert "event: round_started" in body
    assert "id: 4" in body
    assert "event: game_completed" in body


def test_game_run_events_honors_last_event_id_header() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=None,
        max_rounds=8,
        rule_set_id="classic_8",
        rule_set={
            "id": "classic_8",
            "version": "2026.04",
            "name": "经典 8 人局",
            "player_count": 8,
            "roles": [],
        },
    )
    registry.publish(run.run_id, "game_started", payload={"players": []})
    registry.publish(run.run_id, "round_started", round_number=1, payload={"round": 1})
    registry.mark_completed(run.run_id, winner="狼人阵营")
    override_live_registry(registry)

    try:
        response = client.get(
            f"/api/v1/games/runs/{run.run_id}/events",
            headers={"Last-Event-ID": "2"},
        )
    finally:
        clear_overrides()

    assert response.status_code == 200
    body = response.text
    assert "id: 1" not in body
    assert "id: 2" not in body
    assert "event: run_created" not in body
    assert "event: game_started" not in body
    assert "id: 3" in body
    assert "event: round_started" in body
    assert "id: 4" in body
    assert "event: game_completed" in body


def test_list_games_returns_complete_and_partial_sessions(tmp_path: Path) -> None:
    complete_id = "game_05095066"
    partial_id = "game_0600abcd"
    write_json(tmp_path / complete_id / "game_complete.json", sample_state(complete_id))
    write_json(tmp_path / complete_id / "game_logs.json", sample_logs())
    write_json(
        tmp_path / partial_id / "game_partial.json",
        sample_state(partial_id, winner="", error="Maximum rounds exceeded"),
    )
    write_json(tmp_path / partial_id / "game_logs.json", sample_logs())
    override_logs_root(tmp_path)

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert [item["session_id"] for item in payload["sessions"]] == [
        partial_id,
        complete_id,
    ]
    assert payload["sessions"][0]["status"] == "partial"
    assert payload["sessions"][1]["winner"] == "狼人阵营"
    assert payload["sessions"][1]["round_count"] == 1
    assert payload["sessions"][1]["created_at"].endswith("Z")


def test_get_game_detail_returns_state_and_logs(tmp_path: Path) -> None:
    session_id = "game_05095066"
    write_json(tmp_path / session_id / "game_complete.json", sample_state(session_id))
    write_json(tmp_path / session_id / "game_logs.json", sample_logs())
    override_logs_root(tmp_path)

    try:
        response = client.get(f"/api/v1/games/{session_id}")
    finally:
        clear_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["status"] == "complete"
    assert payload["state"]["players"][0]["name"] == "张三"
    assert payload["logs"][0]["eliminate"]["lm_log"]["prompt"] == "请选择今晚击杀对象。"


def test_get_game_playback_returns_complete_playback_events(tmp_path: Path) -> None:
    session_id = "game_1200abcd"
    state = sample_state(session_id, winner="好人阵营")
    state["rule_set"] = {
        "id": "starter_6",
        "name": "新手 6 人快局",
        "player_count": 6,
        "roles": [],
    }
    state["players"][0]["observations"] = ["private observation secret"]
    state["players"][0]["gamestate"] = {"hidden": "private gamestate secret"}
    state["players"][0]["known_roles"] = {"李四": "村民"}
    state["players"][0]["bidding_rationale"] = "secret player reasoning"
    state["rounds"][0]["debate"] = [{"speaker": "张三", "message": "我认为李四身份偏低。"}]
    state["rounds"][0]["votes"] = [{"张三": "李四"}]
    logs = sample_logs()
    logs[0]["eliminate"]["lm_log"]["parsed"] = {
        "choice": "李四",
        "reasoning": "secret chain",
    }
    write_json(tmp_path / session_id / "game_complete.json", state)
    write_json(tmp_path / session_id / "game_logs.json", logs)
    override_logs_root(tmp_path)

    try:
        response = client.get(f"/api/v1/games/{session_id}/playback")
    finally:
        clear_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == session_id
    assert payload["status"] == "complete"
    assert payload["resumable"] is False
    assert payload["rule_set"]["id"] == "starter_6"
    event_types = [event["type"] for event in payload["events"]]
    events = payload["events"]
    assert event_types[:3] == ["run_created", "run_started", "game_started"]
    run_created, run_started, game_started = events[:3]
    assert run_created["payload"]["playback"] is True
    assert run_created["payload"]["session_id"] == session_id
    assert run_created["payload"]["status"] == "complete"
    assert run_created["payload"]["rule_set"]["id"] == "starter_6"
    assert run_created["payload"]["resumable"] is False
    assert run_started["payload"] == {"playback": True}
    assert game_started["payload"]["playback"] is True
    assert game_started["payload"]["rule_set"]["id"] == "starter_6"
    assert game_started["payload"]["players"][0] == {
        "name": "张三",
        "role": "狼人",
        "model": "deepseek-chat",
    }
    assert "round_started" in event_types
    assert "action_requested" in event_types
    assert "action_parsed" in event_types
    requested_event = next(
        event
        for event in events
        if event["type"] == "action_requested"
        and event["actor"] == "张三"
        and event["action"] == "remove"
    )
    assert requested_event["payload"].get("options") == ["李四"]
    assert "visible_text" not in requested_event["payload"]
    assert any(
        event["type"] == "action_requested"
        and event["actor"] == "张三"
        and event["action"] == "remove"
        and event["payload"].get("options") == ["李四"]
        for event in events
    )
    assert any(
        event["type"] == "action_parsed"
        and event["actor"] == "张三"
        and event["action"] == "remove"
        and event["payload"].get("choice") == "李四"
        for event in events
    )
    parsed_event = next(
        event
        for event in events
        if event["type"] == "action_parsed"
        and event["actor"] == "张三"
        and event["action"] == "remove"
    )
    assert parsed_event["payload"]["result"] == {"choice": "李四"}
    assert parsed_event["payload"]["visible_result"] == {"choice": "李四"}
    assert any(
        event["type"] == "state_updated"
        and event["phase"] == "day"
        and event["payload"].get("votes") == {"张三": "李四"}
        for event in events
    )
    assert event_types[-1] == "game_completed"
    assert payload["events"][-1]["payload"] == {"winner": "好人阵营"}
    assert [event["id"] for event in payload["events"]] == list(
        range(1, len(payload["events"]) + 1)
    )
    assert all(event["run_id"] == f"playback_{session_id}" for event in payload["events"])
    serialized_events = json.dumps(payload["events"], ensure_ascii=False)
    assert "请选择今晚击杀对象。" not in serialized_events
    assert "raw_response" not in serialized_events
    assert "prompt" not in serialized_events
    assert "reasoning" not in serialized_events
    assert "secret chain" not in serialized_events
    assert "observations" not in serialized_events
    assert "gamestate" not in serialized_events
    assert "known_roles" not in serialized_events
    assert "bidding_rationale" not in serialized_events
    assert "private observation secret" not in serialized_events
    assert "private gamestate secret" not in serialized_events
    assert "secret player reasoning" not in serialized_events
    assert "李四" in serialized_events


def test_get_game_playback_suppresses_secret_wolf_consensus_actions(tmp_path: Path) -> None:
    session_id = "game_1200abcd"
    state = sample_state(session_id, winner="好人阵营")
    logs = sample_logs()
    logs[0]["eliminate"] = {
        "actor": "张三",
        "action": "werewolf_kill_vote",
        "options": ["李四"],
        "choice": "李四",
        "lm_log": {
            "prompt": "请选择今晚狼刀对象。",
            "raw_response": '{"target":"李四"}',
            "parsed": {"target": "李四"},
        },
    }
    logs[0]["protect"] = {
        "actor": "王五",
        "action": "protect",
        "options": ["张三", "李四"],
        "choice": "张三",
        "lm_log": {
            "prompt": "请选择守护对象。",
            "raw_response": '{"protect":"张三"}',
            "parsed": {"protect": "张三"},
        },
    }
    write_json(tmp_path / session_id / "game_complete.json", state)
    write_json(tmp_path / session_id / "game_logs.json", logs)
    override_logs_root(tmp_path)

    try:
        response = client.get(f"/api/v1/games/{session_id}/playback")
    finally:
        clear_overrides()

    assert response.status_code == 200
    events = response.json()["events"]
    secret_actions = {"werewolf_discuss", "werewolf_kill_vote"}
    assert [event for event in events if event["action"] in secret_actions] == []
    assert any(
        event["type"] == "action_parsed"
        and event["actor"] == "王五"
        and event["action"] == "protect"
        and event["payload"].get("choice") == "张三"
        for event in events
    )


def test_get_game_playback_suppresses_secret_wolf_self_explosion_check(
    tmp_path: Path,
) -> None:
    session_id = "game_1200abcd"
    state = sample_state(session_id, winner="好人阵营")
    state["rounds"][0]["werewolf_self_exploded"] = "张三"
    state["rounds"][0]["day_ended_by_self_explosion"] = True
    logs = sample_logs()
    logs[0]["werewolf_self_explosion"] = {
        "actor": "张三",
        "action": "werewolf_self_explosion",
        "options": ["自爆", "不自爆"],
        "choice": "自爆",
        "lm_log": {
            "prompt": "行动：狼人自爆判断。",
            "raw_response": '{"reasoning":"秘密判断","self_explode":"自爆"}',
            "parsed": {"reasoning": "秘密判断", "self_explode": "自爆"},
        },
    }
    write_json(tmp_path / session_id / "game_complete.json", state)
    write_json(tmp_path / session_id / "game_logs.json", logs)
    override_logs_root(tmp_path)

    try:
        response = client.get(f"/api/v1/games/{session_id}/playback")
    finally:
        clear_overrides()

    assert response.status_code == 200
    events = response.json()["events"]
    private_event_types = {
        "action_requested",
        "model_request_started",
        "model_response_delta",
        "model_thinking_delta",
        "model_thinking_tick",
        "model_response_received",
        "action_parsed",
    }
    assert [
        event
        for event in events
        if event["action"] == "werewolf_self_explosion"
        and event["type"] in private_event_types
    ] == []
    day_state = next(
        event
        for event in events
        if event["type"] == "state_updated" and event["phase"] == "day"
    )
    assert day_state["payload"]["werewolf_self_exploded"] == "张三"
    serialized_events = json.dumps(events, ensure_ascii=False)
    assert "行动：狼人自爆判断。" not in serialized_events
    assert "秘密判断" not in serialized_events


def test_get_game_playback_preserves_public_day_stage_fields(tmp_path: Path) -> None:
    session_id = "game_1200bcde"
    state = sample_state(session_id, winner="好人阵营")
    state["rounds"][0].update(
        {
            "sheriff": "张三",
            "sheriff_candidates": ["张三", "李四"],
            "sheriff_speech_order": ["张三", "李四"],
            "sheriff_speech_direction": "警左发言",
            "sheriff_speeches": [{"speaker": "张三", "message": "我要竞选警长。"}],
            "sheriff_withdrawn": ["李四"],
            "sheriff_final_candidates": ["张三"],
            "sheriff_voters": ["李四"],
            "sheriff_votes": {"李四": "张三"},
            "sheriff_pk_candidates": ["张三", "李四"],
            "sheriff_pk_speeches": [{"speaker": "李四", "message": "我进入 PK。"}],
            "sheriff_runoff_votes": {"李四": "张三"},
            "sheriff_elected": "张三",
            "speech_order": ["李四", "张三"],
            "speech_order_choice": "警左发言",
            "vote_weights": {"张三": 1.5, "李四": 1},
            "sheriff_badge_target": "李四",
            "sheriff_badge_lost": False,
            "werewolf_self_exploded": "李四",
            "day_ended_by_self_explosion": True,
            "sheriff_pre_election_bomb_count": 1,
            "sheriff_election_pending": True,
            "sheriff_badge_lost_reason": "首爆中断警长竞选",
        }
    )
    write_json(tmp_path / session_id / "game_complete.json", state)
    write_json(tmp_path / session_id / "game_logs.json", sample_logs())
    override_logs_root(tmp_path)

    try:
        response = client.get(f"/api/v1/games/{session_id}/playback")
    finally:
        clear_overrides()

    assert response.status_code == 200
    day_state = next(
        event
        for event in response.json()["events"]
        if event["type"] == "state_updated" and event["phase"] == "day"
    )
    assert day_state["payload"] == {
        "debate": [],
        "bids": [{"张三": 3}],
        "votes": {"张三": "李四"},
        "summaries": {"张三": "我会隐藏身份。"},
        "private_summaries": {},
        "public_summary": "",
        "exiled": None,
        "day_deaths": [],
        "hunter_shot": None,
        "idiot_revealed": None,
        "sheriff": "张三",
        "sheriff_candidates": ["张三", "李四"],
        "sheriff_speech_order": ["张三", "李四"],
        "sheriff_speech_direction": "警左发言",
        "sheriff_speeches": [{"speaker": "张三", "message": "我要竞选警长。"}],
        "sheriff_withdrawn": ["李四"],
        "sheriff_final_candidates": ["张三"],
        "sheriff_voters": ["李四"],
        "sheriff_votes": {"李四": "张三"},
        "sheriff_pk_candidates": ["张三", "李四"],
        "sheriff_pk_speeches": [{"speaker": "李四", "message": "我进入 PK。"}],
        "sheriff_runoff_votes": {"李四": "张三"},
        "sheriff_elected": "张三",
        "speech_order": ["李四", "张三"],
        "speech_order_choice": "警左发言",
        "vote_weights": {"张三": 1.5, "李四": 1},
        "sheriff_badge_target": "李四",
        "sheriff_badge_lost": False,
        "werewolf_self_exploded": "李四",
        "day_ended_by_self_explosion": True,
        "sheriff_pre_election_bomb_count": 1,
        "sheriff_election_pending": True,
        "sheriff_badge_lost_reason": "首爆中断警长竞选",
        "active_players": ["张三", "李四"],
    }


def test_get_game_playback_returns_partial_end_without_resuming(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "game_1200abcd"
    state = sample_state(session_id, winner="", error="Maximum rounds exceeded")
    write_json(tmp_path / session_id / "game_partial.json", state)
    write_json(tmp_path / session_id / "game_logs.json", sample_logs())
    write_json(
        tmp_path / session_id / RESUME_CHECKPOINT_FILE,
        {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "state_at_round_start": state,
            "logs_before_round": sample_logs(),
            "run_params": {
                "villager_model": "deepseek-chat",
                "werewolf_model": "deepseek-chat",
                "seed": 7,
                "max_rounds": 8,
                "rule_set_id": "classic_8",
                "player_configs": [],
            },
        },
    )
    override_logs_root(tmp_path)
    registry = LiveRunRegistry()
    created_runs: list[dict[str, object]] = []

    def fail_create_run(**kwargs: object) -> object:
        created_runs.append(kwargs)
        raise AssertionError("playback must not create a live run")

    monkeypatch.setattr(registry, "create_run", fail_create_run)
    override_live_registry(registry)

    try:
        response = client.get(f"/api/v1/games/{session_id}/playback")
    finally:
        clear_overrides()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "partial"
    assert payload["resumable"] is True
    assert payload["events"][-1]["type"] == "game_failed"
    assert payload["events"][-1]["payload"]["playback_partial"] is True
    assert payload["events"][-1]["payload"]["error"] == "Maximum rounds exceeded"
    assert created_runs == []


def test_get_game_playback_returns_404_for_missing_session(tmp_path: Path) -> None:
    override_logs_root(tmp_path)

    try:
        response = client.get("/api/v1/games/game_1200abcd/playback")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json() == {"detail": "Game session not found"}


def test_get_game_playback_returns_404_for_corrupt_replay_json(tmp_path: Path) -> None:
    session_id = "game_1200abcd"
    write_text(tmp_path / session_id / "game_complete.json", "{")
    override_logs_root(tmp_path)

    try:
        response = client.get(f"/api/v1/games/{session_id}/playback")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json() == {"detail": "Game session not found"}


def test_get_game_detail_returns_404_for_missing_valid_session(tmp_path: Path) -> None:
    override_logs_root(tmp_path)

    try:
        response = client.get("/api/v1/games/game_0000dead")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"] == "Game session not found"


def test_get_game_detail_rejects_invalid_session_id(tmp_path: Path) -> None:
    override_logs_root(tmp_path)

    try:
        response = client.get("/api/v1/games/invalid-session-id")
    finally:
        clear_overrides()

    assert response.status_code == 422


def test_list_games_returns_empty_when_logs_root_is_missing(tmp_path: Path) -> None:
    override_logs_root(tmp_path / "missing")

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json() == {"sessions": []}


def test_list_games_skips_invalid_session_directories(tmp_path: Path) -> None:
    valid_id = "game_05095066"
    invalid_id = "not-a-session"
    write_json(tmp_path / valid_id / "game_complete.json", sample_state(valid_id))
    write_json(tmp_path / invalid_id / "game_complete.json", sample_state(invalid_id))
    override_logs_root(tmp_path)

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert [item["session_id"] for item in response.json()["sessions"]] == [valid_id]


def test_get_game_detail_prefers_complete_over_partial(tmp_path: Path) -> None:
    session_id = "game_05095066"
    write_json(
        tmp_path / session_id / "game_complete.json",
        sample_state(session_id, winner="狼人阵营"),
    )
    write_json(
        tmp_path / session_id / "game_partial.json",
        sample_state(session_id, winner="", error="still running"),
    )
    override_logs_root(tmp_path)

    try:
        response = client.get(f"/api/v1/games/{session_id}")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json()["status"] == "complete"
    assert response.json()["state"]["winner"] == "狼人阵营"


def test_get_game_detail_returns_empty_logs_when_logs_file_is_missing(
    tmp_path: Path,
) -> None:
    session_id = "game_05095066"
    write_json(tmp_path / session_id / "game_complete.json", sample_state(session_id))
    override_logs_root(tmp_path)

    try:
        response = client.get(f"/api/v1/games/{session_id}")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json()["logs"] == []


def test_symlinked_session_directory_is_rejected(tmp_path: Path) -> None:
    logs_root = tmp_path / "logs"
    outside_root = tmp_path / "outside"
    session_id = "game_05095066"
    write_json(outside_root / "game_complete.json", sample_state(session_id))
    logs_root.mkdir()
    (logs_root / session_id).symlink_to(outside_root, target_is_directory=True)
    override_logs_root(logs_root)

    try:
        list_response = client.get("/api/v1/games")
        detail_response = client.get(f"/api/v1/games/{session_id}")
    finally:
        clear_overrides()

    assert list_response.status_code == 200
    assert list_response.json() == {"sessions": []}
    assert detail_response.status_code == 404
    assert detail_response.json()["detail"] == "Game session not found"


def test_symlinked_json_files_are_rejected(tmp_path: Path) -> None:
    logs_root = tmp_path / "logs"
    outside_root = tmp_path / "outside"
    session_id = "game_05095066"
    write_json(outside_root / "game_complete.json", sample_state(session_id))
    session_dir = logs_root / session_id
    session_dir.mkdir(parents=True)
    (session_dir / "game_complete.json").symlink_to(outside_root / "game_complete.json")
    override_logs_root(logs_root)

    try:
        list_response = client.get("/api/v1/games")
        detail_response = client.get(f"/api/v1/games/{session_id}")
    finally:
        clear_overrides()

    assert list_response.status_code == 200
    assert list_response.json() == {"sessions": []}
    assert detail_response.status_code == 404
    assert detail_response.json()["detail"] == "Game session not found"


def test_symlinked_complete_file_rejects_session_even_when_partial_exists(
    tmp_path: Path,
) -> None:
    logs_root = tmp_path / "logs"
    outside_root = tmp_path / "outside"
    session_id = "game_05095066"
    session_dir = logs_root / session_id
    write_json(outside_root / "game_complete.json", sample_state(session_id))
    write_json(
        session_dir / "game_partial.json",
        sample_state(session_id, winner="", error="still running"),
    )
    (session_dir / "game_complete.json").symlink_to(outside_root / "game_complete.json")
    override_logs_root(logs_root)

    try:
        list_response = client.get("/api/v1/games")
        detail_response = client.get(f"/api/v1/games/{session_id}")
    finally:
        clear_overrides()

    assert list_response.status_code == 200
    assert list_response.json() == {"sessions": []}
    assert detail_response.status_code == 404
    assert detail_response.json()["detail"] == "Game session not found"


def test_symlinked_logs_file_is_rejected(tmp_path: Path) -> None:
    logs_root = tmp_path / "logs"
    outside_root = tmp_path / "outside"
    session_id = "game_05095066"
    write_json(logs_root / session_id / "game_complete.json", sample_state(session_id))
    write_json(outside_root / "game_logs.json", sample_logs())
    (logs_root / session_id / "game_logs.json").symlink_to(
        outside_root / "game_logs.json"
    )
    override_logs_root(logs_root)

    try:
        response = client.get(f"/api/v1/games/{session_id}")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"] == "Game session not found"


def test_list_games_skips_corrupt_json_and_detail_returns_404(tmp_path: Path) -> None:
    valid_id = "game_05095066"
    corrupt_id = "game_0600abcd"
    write_json(tmp_path / valid_id / "game_complete.json", sample_state(valid_id))
    write_text(tmp_path / corrupt_id / "game_complete.json", "{")
    override_logs_root(tmp_path)

    try:
        list_response = client.get("/api/v1/games")
        detail_response = client.get(f"/api/v1/games/{corrupt_id}")
    finally:
        clear_overrides()

    assert list_response.status_code == 200
    assert [item["session_id"] for item in list_response.json()["sessions"]] == [valid_id]
    assert detail_response.status_code == 404
    assert detail_response.json()["detail"] == "Game session not found"


def test_get_game_detail_returns_404_for_corrupt_logs_json(tmp_path: Path) -> None:
    session_id = "game_05095066"
    write_json(tmp_path / session_id / "game_complete.json", sample_state(session_id))
    write_text(tmp_path / session_id / "game_logs.json", "{")
    override_logs_root(tmp_path)

    try:
        response = client.get(f"/api/v1/games/{session_id}")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"] == "Game session not found"


def test_list_games_skips_legacy_session_directories(tmp_path: Path) -> None:
    session_id = "session_20261340_250000_abcd1234"
    write_json(tmp_path / session_id / "game_complete.json", sample_state(session_id))
    override_logs_root(tmp_path)

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json() == {"sessions": []}


def test_list_games_skips_valid_json_malformed_state(tmp_path: Path) -> None:
    valid_id = "game_05095066"
    list_state_id = "game_0600abcd"
    null_rounds_id = "game_0700abcd"
    write_json(tmp_path / valid_id / "game_complete.json", sample_state(valid_id))
    write_json(tmp_path / list_state_id / "game_complete.json", [])
    write_json(tmp_path / null_rounds_id / "game_complete.json", {"rounds": None})
    override_logs_root(tmp_path)

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert [item["session_id"] for item in response.json()["sessions"]] == [valid_id]


def test_get_game_detail_returns_404_for_malformed_state(tmp_path: Path) -> None:
    list_state_id = "game_0600abcd"
    null_rounds_id = "game_0700abcd"
    write_json(tmp_path / list_state_id / "game_complete.json", [])
    write_json(tmp_path / null_rounds_id / "game_complete.json", {"rounds": None})
    override_logs_root(tmp_path)

    try:
        list_response = client.get(f"/api/v1/games/{list_state_id}")
        null_rounds_response = client.get(f"/api/v1/games/{null_rounds_id}")
    finally:
        clear_overrides()

    assert list_response.status_code == 404
    assert list_response.json()["detail"] == "Game session not found"
    assert null_rounds_response.status_code == 404
    assert null_rounds_response.json()["detail"] == "Game session not found"


def test_list_games_returns_empty_when_logs_root_is_file(tmp_path: Path) -> None:
    logs_root = tmp_path / "logs"
    logs_root.write_text("not a directory", encoding="utf-8")
    override_logs_root(logs_root)

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json() == {"sessions": []}


def test_list_games_returns_empty_when_logs_root_stat_raises(
    tmp_path: Path,
    monkeypatch,
) -> None:
    logs_root = tmp_path / "logs"
    original_exists = Path.exists

    def raising_exists(path: Path) -> bool:
        if path == logs_root:
            raise OSError("stat failed")
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", raising_exists)
    override_logs_root(logs_root)

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json() == {"sessions": []}


def test_list_games_skips_entry_when_symlink_stat_raises(
    tmp_path: Path,
    monkeypatch,
) -> None:
    valid_id = "game_05095066"
    bad_id = "game_0600abcd"
    bad_dir = tmp_path / bad_id
    write_json(tmp_path / valid_id / "game_complete.json", sample_state(valid_id))
    write_json(bad_dir / "game_complete.json", sample_state(bad_id))
    original_is_symlink = Path.is_symlink

    def raising_is_symlink(path: Path) -> bool:
        if path == bad_dir:
            raise OSError("lstat failed")
        return original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", raising_is_symlink)
    override_logs_root(tmp_path)

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert [item["session_id"] for item in response.json()["sessions"]] == [valid_id]


def test_list_games_skips_session_when_state_file_stat_raises(
    tmp_path: Path,
    monkeypatch,
) -> None:
    valid_id = "game_05095066"
    bad_id = "game_0600abcd"
    bad_state_path = tmp_path / bad_id / "game_complete.json"
    write_json(tmp_path / valid_id / "game_complete.json", sample_state(valid_id))
    write_json(bad_state_path, sample_state(bad_id))
    original_is_symlink = Path.is_symlink

    def raising_is_symlink(path: Path) -> bool:
        if path == bad_state_path:
            raise OSError("lstat failed")
        return original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", raising_is_symlink)
    override_logs_root(tmp_path)

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert [item["session_id"] for item in response.json()["sessions"]] == [valid_id]


def test_get_game_detail_returns_404_for_malformed_logs_schema(
    tmp_path: Path,
) -> None:
    session_id = "game_05095066"
    write_json(tmp_path / session_id / "game_complete.json", sample_state(session_id))
    write_json(tmp_path / session_id / "game_logs.json", {})
    override_logs_root(tmp_path)

    try:
        response = client.get(f"/api/v1/games/{session_id}")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"] == "Game session not found"


def test_get_game_detail_returns_404_when_session_resolve_raises(
    tmp_path: Path,
    monkeypatch,
) -> None:
    session_id = "game_05095066"
    session_dir = tmp_path / session_id
    write_json(session_dir / "game_complete.json", sample_state(session_id))
    original_resolve = Path.resolve

    def raising_resolve(path: Path, *args, **kwargs) -> Path:
        if path == session_dir:
            raise OSError("resolve failed")
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", raising_resolve)
    override_logs_root(tmp_path)

    try:
        response = client.get(f"/api/v1/games/{session_id}")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"] == "Game session not found"
