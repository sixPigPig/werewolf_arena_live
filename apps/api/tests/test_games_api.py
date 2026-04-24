import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.routes.games import get_live_registry, get_replay_store
from app.main import app
from app.werewolf.live import LiveRunRegistry
from app.werewolf.replay import ReplayStore


client = TestClient(app)


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
    ]
    assert payload["rule_sets"][0]["role_summary"] == "2 狼人 / 1 预言家 / 1 医生 / 4 村民"


def test_create_game_run_accepts_rule_set_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_list_games_includes_rule_set_summary(tmp_path: Path) -> None:
    session_id = "session_20260424_050950_66ea9f38"
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
    assert payload["session_id"].startswith("session_")
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


def test_game_run_events_replays_existing_events() -> None:
    registry = LiveRunRegistry()
    run = registry.create_run(
        session_id="session_20260424_120000_ab12cd34",
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


def test_list_games_returns_complete_and_partial_sessions(tmp_path: Path) -> None:
    complete_id = "session_20260424_050950_66ea9f38"
    partial_id = "session_20260424_060000_abcd1234"
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
    assert payload["sessions"][1]["created_at"] == "2026-04-24T05:09:50Z"


def test_get_game_detail_returns_state_and_logs(tmp_path: Path) -> None:
    session_id = "session_20260424_050950_66ea9f38"
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


def test_get_game_detail_returns_404_for_missing_valid_session(tmp_path: Path) -> None:
    override_logs_root(tmp_path)

    try:
        response = client.get("/api/v1/games/session_20260424_050950_missing")
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
    valid_id = "session_20260424_050950_66ea9f38"
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
    session_id = "session_20260424_050950_66ea9f38"
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
    session_id = "session_20260424_050950_66ea9f38"
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
    session_id = "session_20260424_050950_66ea9f38"
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
    session_id = "session_20260424_050950_66ea9f38"
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
    session_id = "session_20260424_050950_66ea9f38"
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
    session_id = "session_20260424_050950_66ea9f38"
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
    valid_id = "session_20260424_050950_66ea9f38"
    corrupt_id = "session_20260424_060000_abcd1234"
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
    session_id = "session_20260424_050950_66ea9f38"
    write_json(tmp_path / session_id / "game_complete.json", sample_state(session_id))
    write_text(tmp_path / session_id / "game_logs.json", "{")
    override_logs_root(tmp_path)

    try:
        response = client.get(f"/api/v1/games/{session_id}")
    finally:
        clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"] == "Game session not found"


def test_list_games_does_not_crash_on_invalid_timestamp(tmp_path: Path) -> None:
    session_id = "session_20261340_250000_abcd1234"
    write_json(tmp_path / session_id / "game_complete.json", sample_state(session_id))
    override_logs_root(tmp_path)

    try:
        response = client.get("/api/v1/games")
    finally:
        clear_overrides()

    assert response.status_code == 200
    assert response.json()["sessions"][0]["session_id"] == session_id
    assert response.json()["sessions"][0]["created_at"] is None


def test_list_games_skips_valid_json_malformed_state(tmp_path: Path) -> None:
    valid_id = "session_20260424_050950_66ea9f38"
    list_state_id = "session_20260424_060000_abcd1234"
    null_rounds_id = "session_20260424_070000_abcd1234"
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
    list_state_id = "session_20260424_060000_abcd1234"
    null_rounds_id = "session_20260424_070000_abcd1234"
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
    valid_id = "session_20260424_050950_66ea9f38"
    bad_id = "session_20260424_060000_abcd1234"
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
    valid_id = "session_20260424_050950_66ea9f38"
    bad_id = "session_20260424_060000_abcd1234"
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
    session_id = "session_20260424_050950_66ea9f38"
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
    session_id = "session_20260424_050950_66ea9f38"
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
