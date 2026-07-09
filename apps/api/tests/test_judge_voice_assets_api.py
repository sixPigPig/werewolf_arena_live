from collections.abc import AsyncIterator, Generator
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.routes.judge_voice_assets import (
    get_judge_voice_asset_dir,
    get_judge_voice_client_factory,
    get_judge_voice_tts_config,
)
from app.main import app
from app.werewolf.volcengine_tts import VolcengineTtsConfig


BASE_CONFIG = VolcengineTtsConfig(
    enabled=True,
    api_key="ark-test-key",
    resource_id="seed-tts-2.0",
    ws_url="wss://example.test",
    player_speaker="player",
    judge_speaker="judge",
    audio_format="mp3",
    sample_rate=24000,
)


class RecordingTtsClient:
    def __init__(self, config: VolcengineTtsConfig) -> None:
        self.config = config

    async def synthesize(
        self,
        *,
        speaker: str,
        text_chunks: list[str],
    ) -> AsyncIterator[bytes]:
        yield f"{speaker}:{'|'.join(text_chunks)}".encode("utf-8")


@contextmanager
def client_with_judge_voice_overrides(
    tmp_path: Path,
    *,
    config: VolcengineTtsConfig = BASE_CONFIG,
) -> Generator[TestClient, None, None]:
    try:
        app.dependency_overrides[get_judge_voice_asset_dir] = lambda: tmp_path / "judge-voice"
        app.dependency_overrides[get_judge_voice_tts_config] = lambda: config
        app.dependency_overrides[get_judge_voice_client_factory] = lambda: RecordingTtsClient
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_list_judge_voice_lines_reports_static_asset_status(tmp_path: Path) -> None:
    asset_dir = tmp_path / "judge-voice"
    asset_dir.mkdir()
    (asset_dir / "night_start.mp3").write_bytes(b"audio")

    with client_with_judge_voice_overrides(tmp_path) as client:
        response = client.get("/api/v1/judge-voice-lines")

    assert response.status_code == 200
    body = response.json()
    night_start = next(line for line in body["lines"] if line["id"] == "night_start")
    assert body["audio_format"] == "mp3"
    assert night_start["text"] == "夜晚降临，所有玩家请闭眼。"
    assert night_start["exists"] is True
    assert night_start["public_url"] == "/judge-voice/night_start.mp3"


def test_generate_judge_voice_lines_writes_selected_static_assets(tmp_path: Path) -> None:
    with client_with_judge_voice_overrides(tmp_path) as client:
        response = client.post(
            "/api/v1/judge-voice-lines/generate",
            json={"line_ids": ["night_start"]},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["generated_ids"] == ["night_start"]
    assert body["skipped_ids"] == []
    assert body["lines"][0]["id"] == "night_start"
    assert (tmp_path / "judge-voice" / "night_start.mp3").exists()
    assert (tmp_path / "judge-voice" / "manifest.json").exists()


def test_generate_judge_voice_lines_returns_503_when_tts_disabled(tmp_path: Path) -> None:
    disabled_config = VolcengineTtsConfig(
        enabled=False,
        api_key="ark-test-key",
        resource_id="seed-tts-2.0",
        ws_url="wss://example.test",
        player_speaker="player",
        judge_speaker="judge",
        audio_format="mp3",
        sample_rate=24000,
    )

    with client_with_judge_voice_overrides(tmp_path, config=disabled_config) as client:
        response = client.post("/api/v1/judge-voice-lines/generate", json={})

    assert response.status_code == 503
    assert response.json()["detail"] == "语音服务未启用，请检查后端语音配置。"


def test_generate_judge_voice_lines_rejects_unknown_line_ids(tmp_path: Path) -> None:
    with client_with_judge_voice_overrides(tmp_path) as client:
        response = client.post(
            "/api/v1/judge-voice-lines/generate",
            json={"line_ids": ["missing_line"]},
        )

    assert response.status_code == 422
    assert "Unknown judge voice line id: missing_line" in response.json()["detail"]
