import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

from app.shared.judge_voice_assets import (
    DEFAULT_JUDGE_VOICE_ASSET_DIR,
    JUDGE_VOICE_LINES,
    generate_judge_voice_assets,
    list_judge_voice_assets,
    validate_used_judge_voice_assets,
)
from app.shared.volcengine_tts import VolcengineTtsConfig
from app.shared.volcengine_tts import TtsSubtitleCue, TtsSubtitleTiming


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
    instances: list["RecordingTtsClient"] = []

    def __init__(self, config: VolcengineTtsConfig) -> None:
        self.config = config
        self.calls: list[dict] = []
        RecordingTtsClient.instances.append(self)

    async def synthesize(
        self,
        *,
        speaker: str,
        text_chunks: list[str],
    ) -> AsyncIterator[bytes | TtsSubtitleTiming]:
        self.calls.append({"speaker": speaker, "text_chunks": text_chunks})
        yield TtsSubtitleTiming(
            cues=(
                TtsSubtitleCue(text=text_chunks[0], start_ms=0, end_ms=320),
                TtsSubtitleCue(text=text_chunks[-1], start_ms=320, end_ms=880),
            )
        )
        yield b"audio-"
        yield "|".join(text_chunks).encode("utf-8")


def test_catalog_contains_standard_werewolf_judge_lines() -> None:
    lines_by_id = {line.id: line for line in JUDGE_VOICE_LINES}

    assert lines_by_id["night_start"].text == "夜晚降临，所有玩家请闭眼。"
    assert lines_by_id["werewolves_wake"].text == "狼人请睁眼，请互相确认队友。"
    assert lines_by_id["witch_death"].text == "今晚被狼人袭击的玩家是{玩家}。"
    assert lines_by_id["dawn_peaceful"].text == "昨夜平安夜。"
    assert lines_by_id["speech_prompt"].text == "{玩家}请发言。"
    assert lines_by_id["exile_result"].text == "{玩家} 得票最高，被放逐出局。"
    assert lines_by_id["game_over_wolves"].text == "游戏结束，狼人阵营获胜。"
    assert lines_by_id["sheriff_no_voters"].text == "本轮没有警下投票者，警徽流失。"
    assert lines_by_id["hunter_shot_skipped"].text == "猎人选择不发动技能。"


def test_used_static_judge_voice_assets_have_audio_and_subtitle_timings() -> None:
    validate_used_judge_voice_assets(asset_dir=DEFAULT_JUDGE_VOICE_ASSET_DIR)


def test_list_judge_voice_assets_marks_existing_files(tmp_path: Path) -> None:
    asset_dir = tmp_path / "judge-voice"
    asset_dir.mkdir()
    (asset_dir / "night_start.mp3").write_bytes(b"audio")

    assets = list_judge_voice_assets(asset_dir=asset_dir, audio_format="mp3")
    night_start = next(asset for asset in assets if asset.id == "night_start")
    dawn_peaceful = next(asset for asset in assets if asset.id == "dawn_peaceful")

    assert night_start.exists is True
    assert night_start.byte_size == 5
    assert night_start.filename == "night_start.mp3"
    assert night_start.public_url == "/judge-voice/night_start.mp3"
    assert dawn_peaceful.exists is False
    assert dawn_peaceful.byte_size is None


def test_list_judge_voice_assets_expands_player_templates_to_seat_variants() -> None:
    assets = list_judge_voice_assets(audio_format="mp3")
    speech_variants = [
        asset for asset in assets if asset.template_id == "speech_prompt"
    ]
    speech_seat_10 = next(asset for asset in assets if asset.id == "speech_prompt_seat_10")

    assert len(speech_variants) == 12
    assert not any(asset.id == "speech_prompt" for asset in assets)
    assert speech_seat_10.text == "10号玩家请发言。"
    assert speech_seat_10.template_text == "{玩家}请发言。"
    assert speech_seat_10.seat_number == 10
    assert speech_seat_10.filename == "speech_prompt_seat_10.mp3"


def test_generate_judge_voice_assets_writes_audio_and_manifest(tmp_path: Path) -> None:
    RecordingTtsClient.instances.clear()
    asset_dir = tmp_path / "judge-voice"

    result = asyncio.run(
        generate_judge_voice_assets(
            config=BASE_CONFIG,
            asset_dir=asset_dir,
            line_ids=["night_start", "dawn_deaths"],
            client_factory=RecordingTtsClient,
        )
    )

    assert result.generated_ids == ["night_start", "dawn_deaths"]
    assert result.skipped_ids == []
    assert (asset_dir / "night_start.mp3").read_bytes().startswith(b"audio-")
    assert (asset_dir / "dawn_deaths.mp3").exists()
    assert RecordingTtsClient.instances[0].calls[0]["speaker"] == "judge"
    assert "夜晚降临" in "".join(RecordingTtsClient.instances[0].calls[0]["text_chunks"])

    manifest = json.loads((asset_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["audio_format"] == "mp3"
    assert manifest["sample_rate"] == 24000
    assert manifest["mime_type"] == "audio/mpeg"
    assert [line["id"] for line in manifest["lines"]] == ["night_start", "dawn_deaths"]
    assert manifest["lines"][0]["public_url"] == "/judge-voice/night_start.mp3"
    assert manifest["lines"][0]["subtitle_timings"] == [
        {"text": "夜晚降临，", "start_ms": 0, "end_ms": 320},
        {"text": "所有玩家请闭眼。", "start_ms": 320, "end_ms": 880},
    ]


def test_generate_judge_voice_assets_expands_template_ids(tmp_path: Path) -> None:
    RecordingTtsClient.instances.clear()
    asset_dir = tmp_path / "judge-voice"

    result = asyncio.run(
        generate_judge_voice_assets(
            config=BASE_CONFIG,
            asset_dir=asset_dir,
            line_ids=["speech_prompt"],
            client_factory=RecordingTtsClient,
        )
    )

    assert len(result.generated_ids) == 12
    assert result.generated_ids[0] == "speech_prompt_seat_01"
    assert result.generated_ids[-1] == "speech_prompt_seat_12"
    assert (asset_dir / "speech_prompt_seat_10.mp3").exists()
    assert "10号玩家" in "".join(RecordingTtsClient.instances[9].calls[0]["text_chunks"])


def test_selective_generation_preserves_other_manifest_lines(tmp_path: Path) -> None:
    RecordingTtsClient.instances.clear()
    asset_dir = tmp_path / "judge-voice"

    asyncio.run(
        generate_judge_voice_assets(
            config=BASE_CONFIG,
            asset_dir=asset_dir,
            line_ids=["night_start"],
            client_factory=RecordingTtsClient,
        )
    )
    asyncio.run(
        generate_judge_voice_assets(
            config=BASE_CONFIG,
            asset_dir=asset_dir,
            line_ids=["witch_death"],
            force=True,
            client_factory=RecordingTtsClient,
        )
    )

    manifest = json.loads((asset_dir / "manifest.json").read_text(encoding="utf-8"))
    line_ids = [line["id"] for line in manifest["lines"]]
    assert line_ids[0] == "night_start"
    assert line_ids[1:] == [f"witch_death_seat_{seat:02d}" for seat in range(1, 13)]
    witch_line = next(line for line in manifest["lines"] if line["id"] == "witch_death_seat_08")
    assert witch_line["text"] == "今晚被狼人袭击的玩家是8号玩家。"


def test_generate_judge_voice_assets_skips_existing_without_force(tmp_path: Path) -> None:
    RecordingTtsClient.instances.clear()
    asset_dir = tmp_path / "judge-voice"
    asset_dir.mkdir()
    (asset_dir / "night_start.mp3").write_bytes(b"old-audio")

    result = asyncio.run(
        generate_judge_voice_assets(
            config=BASE_CONFIG,
            asset_dir=asset_dir,
            line_ids=["night_start"],
            client_factory=RecordingTtsClient,
        )
    )

    assert result.generated_ids == []
    assert result.skipped_ids == ["night_start"]
    assert (asset_dir / "night_start.mp3").read_bytes() == b"old-audio"
    assert RecordingTtsClient.instances == []
