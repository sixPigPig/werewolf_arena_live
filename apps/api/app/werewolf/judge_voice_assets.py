from __future__ import annotations

import json
import re
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from app.werewolf.voice import (
    USED_STATIC_JUDGE_VOICE_ASSET_IDS,
    USED_STATIC_JUDGE_VOICE_ASSET_TEMPLATE_IDS,
    chunk_text_for_tts,
)
from app.werewolf.volcengine_tts import (
    TtsSubtitleTiming,
    TtsSynthesisItem,
    VolcengineTtsClient,
    VolcengineTtsConfig,
    mime_type_for_format,
)


class TtsClient(Protocol):
    async def synthesize(
        self,
        *,
        speaker: str,
        text_chunks: list[str],
    ) -> AsyncIterator[TtsSynthesisItem]:
        pass


@dataclass(frozen=True)
class JudgeVoiceLine:
    id: str
    text: str
    category: str
    tts_text: str | None = None
    template_id: str | None = None
    template_text: str | None = None
    seat_number: int | None = None

    @property
    def spoken_text(self) -> str:
        return self.tts_text or self.text


@dataclass(frozen=True)
class JudgeVoiceAsset:
    id: str
    text: str
    category: str
    filename: str
    public_url: str
    exists: bool
    byte_size: int | None
    template_id: str | None = None
    template_text: str | None = None
    seat_number: int | None = None
    subtitle_timings: list[dict[str, int | str]] = field(default_factory=list)


@dataclass(frozen=True)
class JudgeVoiceGenerationResult:
    lines: list[JudgeVoiceAsset]
    generated_ids: list[str]
    skipped_ids: list[str]
    manifest_path: str


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_JUDGE_VOICE_ASSET_DIR = (
    REPO_ROOT / "apps" / "api" / "resources" / "judge-voice-seed"
)
DEFAULT_PUBLIC_BASE_PATH = "/judge-voice"
PLAYER_SEAT_RANGE = range(1, 13)
PLACEHOLDER_PATTERN = re.compile(r"\{([^{}]+)\}")

JUDGE_VOICE_LINES: tuple[JudgeVoiceLine, ...] = (
    JudgeVoiceLine("game_intro", "本局游戏开始，请所有玩家确认自己的身份牌。", "开局"),
    JudgeVoiceLine("game_resume", "本局游戏继续。", "开局"),
    JudgeVoiceLine("night_start", "夜晚降临，所有玩家请闭眼。", "夜晚"),
    JudgeVoiceLine("werewolves_wake", "狼人请睁眼，请互相确认队友。", "狼人"),
    JudgeVoiceLine("werewolves_choose", "狼人请选择今晚袭击的目标。", "狼人"),
    JudgeVoiceLine("werewolves_confirm", "狼人请统一意见，并向法官示意。", "狼人"),
    JudgeVoiceLine("werewolves_sleep", "狼人请闭眼。", "狼人"),
    JudgeVoiceLine("guard_wake", "守卫请睁眼。", "守卫"),
    JudgeVoiceLine("guard_choose", "请选择今晚守护的玩家。", "守卫"),
    JudgeVoiceLine("guard_sleep", "守卫请闭眼。", "守卫"),
    JudgeVoiceLine("seer_wake", "预言家请睁眼。", "预言家"),
    JudgeVoiceLine("seer_choose", "请选择今晚查验的玩家。", "预言家"),
    JudgeVoiceLine("seer_result_good", "法官示意，该玩家为好人。", "预言家"),
    JudgeVoiceLine("seer_result_wolf", "法官示意，该玩家为狼人。", "预言家"),
    JudgeVoiceLine("seer_sleep", "预言家请闭眼。", "预言家"),
    JudgeVoiceLine("witch_wake", "女巫请睁眼。", "女巫"),
    JudgeVoiceLine("witch_death", "今晚被狼人袭击的玩家是{玩家}。", "女巫"),
    JudgeVoiceLine("witch_save", "你是否使用解药？", "女巫"),
    JudgeVoiceLine("witch_poison", "你是否使用毒药？如果使用，请选择毒杀目标。", "女巫"),
    JudgeVoiceLine("witch_sleep", "女巫请闭眼。", "女巫"),
    JudgeVoiceLine("hunter_wake", "猎人请睁眼。", "猎人"),
    JudgeVoiceLine("hunter_status", "法官确认你的开枪状态。", "猎人"),
    JudgeVoiceLine("hunter_sleep", "猎人请闭眼。", "猎人"),
    JudgeVoiceLine("idiot_wake", "白痴请睁眼。", "白痴"),
    JudgeVoiceLine("idiot_status", "法官确认你的身份。", "白痴"),
    JudgeVoiceLine("idiot_sleep", "白痴请闭眼。", "白痴"),
    JudgeVoiceLine("dawn_start", "天亮了，所有玩家请睁眼。", "白天"),
    JudgeVoiceLine("sheriff_start", "现在进入警长竞选环节。", "警长"),
    JudgeVoiceLine("sheriff_raise_hands", "想要竞选警长的玩家请举手。", "警长"),
    JudgeVoiceLine("sheriff_speech_start", "从 {玩家} 开始，按 {方向} 发表竞选发言。", "警长"),
    JudgeVoiceLine("sheriff_speech_end", "竞选发言结束。", "警长"),
    JudgeVoiceLine("sheriff_candidates", "仍在警上的玩家为 {名单}。", "警长"),
    JudgeVoiceLine("sheriff_vote", "警下玩家开始投票。", "警长"),
    JudgeVoiceLine("vote_countdown", "三，二，一，请投票。", "投票"),
    JudgeVoiceLine("sheriff_result", "{玩家} 当选警长，获得警徽。", "警长"),
    JudgeVoiceLine("sheriff_tie", "出现平票，进入 PK 发言并再次投票。", "警长"),
    JudgeVoiceLine("sheriff_pk_start", "平票候选人依次进行 PK 发言。", "警长"),
    JudgeVoiceLine("sheriff_runoff_vote", "PK 发言结束，警下玩家开始二轮投票。", "警长"),
    JudgeVoiceLine("sheriff_no_voters", "本轮没有警下投票者，警徽流失。", "警长"),
    JudgeVoiceLine("sheriff_runoff_tied", "警长二轮投票仍未产生唯一领先者。", "警长"),
    JudgeVoiceLine("sheriff_no_badge", "再次平票，本局无警长。", "警长"),
    JudgeVoiceLine("dawn_deaths", "昨夜死亡的玩家是 {玩家列表}。", "白天"),
    JudgeVoiceLine("dawn_peaceful", "昨夜平安夜。", "白天"),
    JudgeVoiceLine("last_words", "请死亡玩家发表遗言。", "遗言"),
    JudgeVoiceLine("sheriff_choose_dead_side", "请警长选择从死左或死右开始发言。", "发言"),
    JudgeVoiceLine("sheriff_choose_badge_side", "请警长选择从警左或警右开始发言。", "发言"),
    JudgeVoiceLine("speech_start", "现在开始依次发言。", "发言"),
    JudgeVoiceLine("speech_prompt", "{玩家}请发言。", "发言"),
    JudgeVoiceLine("exile_vote_start", "发言结束，进入放逐投票。", "放逐"),
    JudgeVoiceLine("exile_vote_choose", "所有玩家请选择你要放逐的对象。", "放逐"),
    JudgeVoiceLine("exile_result", "{玩家} 得票最高，被放逐出局。", "放逐"),
    JudgeVoiceLine("exile_last_words", "请 {玩家} 发表遗言。", "遗言"),
    JudgeVoiceLine("next_night", "夜晚降临，所有玩家请闭眼。", "夜晚"),
    JudgeVoiceLine("werewolf_self_explosion", "{玩家} 发动狼人自爆。", "特殊事件"),
    JudgeVoiceLine("self_explosion_skip", "该玩家立即出局，本轮发言和投票终止，直接进入夜晚。", "特殊事件"),
    JudgeVoiceLine("hunter_shot_start", "猎人发动技能。", "特殊事件"),
    JudgeVoiceLine("hunter_shot_choose", "请猎人选择要带走的玩家。", "特殊事件"),
    JudgeVoiceLine("hunter_shot_result", "{玩家} 被猎人带走，出局。", "特殊事件"),
    JudgeVoiceLine("hunter_shot_skipped", "猎人选择不发动技能。", "特殊事件"),
    JudgeVoiceLine("idiot_reveal", "{玩家} 翻牌为白痴。", "特殊事件"),
    JudgeVoiceLine("idiot_stays", "该玩家免于本次放逐，之后按本局规则保留或失去投票权。", "特殊事件"),
    JudgeVoiceLine("badge_owner_out", "警长出局，请选择移交警徽或撕毁警徽。", "警徽"),
    JudgeVoiceLine("badge_transfer", "警徽移交给 {玩家}。", "警徽"),
    JudgeVoiceLine("badge_destroyed", "警徽被撕毁。", "警徽"),
    JudgeVoiceLine("game_over_villagers", "游戏结束，好人阵营获胜。", "结局"),
    JudgeVoiceLine("game_over_wolves", "游戏结束，狼人阵营获胜。", "结局"),
    JudgeVoiceLine("game_over_third_party", "游戏结束，第三方阵营获胜。", "结局"),
)


def list_judge_voice_assets(
    *,
    asset_dir: Path = DEFAULT_JUDGE_VOICE_ASSET_DIR,
    audio_format: str,
    public_base_path: str = DEFAULT_PUBLIC_BASE_PATH,
    line_ids: list[str] | None = None,
) -> list[JudgeVoiceAsset]:
    selected_lines = _select_lines(line_ids)
    subtitle_timings_by_id = _subtitle_timings_by_line_id(asset_dir / "manifest.json")
    return [
        _asset_for_line(
            line,
            asset_dir=asset_dir,
            audio_format=audio_format,
            public_base_path=public_base_path,
            subtitle_timings=subtitle_timings_by_id.get(line.id, []),
        )
        for line in selected_lines
    ]


def list_judge_voice_line_definitions() -> list[JudgeVoiceLine]:
    return _expanded_voice_lines()


def validate_used_judge_voice_assets(
    *,
    asset_dir: Path = DEFAULT_JUDGE_VOICE_ASSET_DIR,
    audio_format: str = "mp3",
) -> None:
    assets = list_judge_voice_assets(asset_dir=asset_dir, audio_format=audio_format)
    assets_by_id = {asset.id: asset for asset in assets}
    required_ids = set(USED_STATIC_JUDGE_VOICE_ASSET_IDS)
    for template_id in USED_STATIC_JUDGE_VOICE_ASSET_TEMPLATE_IDS:
        required_ids.update(
            asset.id for asset in assets if asset.template_id == template_id
        )
    missing = sorted(
        asset_id
        for asset_id in required_ids
        if asset_id not in assets_by_id
        or not assets_by_id[asset_id].exists
        or not assets_by_id[asset_id].subtitle_timings
    )
    if missing:
        raise RuntimeError(f"Judge voice asset gate failed: {', '.join(missing)}")


async def generate_judge_voice_assets(
    *,
    config: VolcengineTtsConfig,
    asset_dir: Path = DEFAULT_JUDGE_VOICE_ASSET_DIR,
    line_ids: list[str] | None = None,
    force: bool = False,
    public_base_path: str = DEFAULT_PUBLIC_BASE_PATH,
    client_factory: Callable[[VolcengineTtsConfig], TtsClient] = VolcengineTtsClient,
) -> JudgeVoiceGenerationResult:
    selected_lines = _select_lines(line_ids)
    asset_dir.mkdir(parents=True, exist_ok=True)
    generated_ids: list[str] = []
    skipped_ids: list[str] = []
    subtitle_timings_by_id = _subtitle_timings_by_line_id(asset_dir / "manifest.json")

    for line in selected_lines:
        audio_path = asset_dir / _filename_for_line(line, config.audio_format)
        if audio_path.exists() and not force:
            skipped_ids.append(line.id)
            continue

        text_chunks = chunk_text_for_tts(line.spoken_text)
        client = client_factory(config)
        audio = bytearray()
        async for chunk in client.synthesize(
            speaker=config.judge_speaker,
            text_chunks=text_chunks,
        ):
            if isinstance(chunk, TtsSubtitleTiming):
                subtitle_timings_by_id[line.id] = _subtitle_timings_from_tts(chunk)
                continue
            audio.extend(chunk)
        _write_bytes_atomically(audio_path, bytes(audio))
        generated_ids.append(line.id)

    assets = [
        _asset_for_line(
            line,
            asset_dir=asset_dir,
            audio_format=config.audio_format,
            public_base_path=public_base_path,
            subtitle_timings=subtitle_timings_by_id.get(line.id, []),
        )
        for line in selected_lines
    ]
    manifest_path = asset_dir / "manifest.json"
    _write_manifest(
        manifest_path,
        assets=assets,
        audio_format=config.audio_format,
        sample_rate=config.sample_rate,
        mime_type=mime_type_for_format(config.audio_format),
    )
    return JudgeVoiceGenerationResult(
        lines=assets,
        generated_ids=generated_ids,
        skipped_ids=skipped_ids,
        manifest_path=str(manifest_path),
    )


def _select_lines(line_ids: list[str] | None) -> list[JudgeVoiceLine]:
    expanded_lines = _expanded_voice_lines()
    if line_ids is None:
        return expanded_lines

    expanded_lines_by_id = {line.id: line for line in expanded_lines}
    lines_by_id = {line.id: line for line in JUDGE_VOICE_LINES}
    selected: list[JudgeVoiceLine] = []
    for line_id in line_ids:
        expanded_line = expanded_lines_by_id.get(line_id)
        if expanded_line is not None:
            selected.append(expanded_line)
            continue

        template_line = lines_by_id.get(line_id)
        if template_line is not None and _is_player_seat_template(template_line):
            selected.extend(
                line for line in expanded_lines if line.template_id == template_line.id
            )
            continue

        if template_line is not None:
            selected.append(template_line)
            continue

        if expanded_line is None:
            raise ValueError(f"Unknown judge voice line id: {line_id}")
    return selected


def _expanded_voice_lines() -> list[JudgeVoiceLine]:
    expanded: list[JudgeVoiceLine] = []
    for line in JUDGE_VOICE_LINES:
        if _is_player_seat_template(line):
            expanded.extend(_seat_variants_for_line(line))
            continue
        expanded.append(line)
    return expanded


def _is_player_seat_template(line: JudgeVoiceLine) -> bool:
    return PLACEHOLDER_PATTERN.findall(line.text) == ["玩家"]


def _seat_variants_for_line(line: JudgeVoiceLine) -> list[JudgeVoiceLine]:
    return [
        JudgeVoiceLine(
            id=f"{line.id}_seat_{seat_number:02d}",
            text=_replace_player_placeholder(line.text, seat_number),
            category=line.category,
            tts_text=(
                _replace_player_placeholder(line.tts_text, seat_number)
                if line.tts_text
                else None
            ),
            template_id=line.id,
            template_text=line.text,
            seat_number=seat_number,
        )
        for seat_number in PLAYER_SEAT_RANGE
    ]


def _replace_player_placeholder(text: str, seat_number: int) -> str:
    replaced = text.replace("{玩家}", f"{seat_number}号玩家")
    return re.sub(r"\s*(\d+号玩家)\s*", r"\1", replaced)


def _asset_for_line(
    line: JudgeVoiceLine,
    *,
    asset_dir: Path,
    audio_format: str,
    public_base_path: str,
    subtitle_timings: list[dict[str, int | str]],
) -> JudgeVoiceAsset:
    filename = _filename_for_line(line, audio_format)
    audio_path = asset_dir / filename
    return JudgeVoiceAsset(
        id=line.id,
        text=line.text,
        category=line.category,
        filename=filename,
        public_url=f"{public_base_path.rstrip('/')}/{filename}",
        exists=audio_path.exists(),
        byte_size=audio_path.stat().st_size if audio_path.exists() else None,
        template_id=line.template_id,
        template_text=line.template_text,
        seat_number=line.seat_number,
        subtitle_timings=subtitle_timings,
    )


def _filename_for_line(line: JudgeVoiceLine, audio_format: str) -> str:
    return f"{line.id}.{audio_format.lower()}"


def _write_bytes_atomically(path: Path, data: bytes) -> None:
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_bytes(data)
    temporary_path.replace(path)


def _write_manifest(
    path: Path,
    *,
    assets: list[JudgeVoiceAsset],
    audio_format: str,
    sample_rate: int,
    mime_type: str,
) -> None:
    generated_lines = {asset.id: asdict(asset) for asset in assets}
    lines = _merged_manifest_lines(path, generated_lines)
    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "audio_format": audio_format,
        "sample_rate": sample_rate,
        "mime_type": mime_type,
        "lines": lines,
    }
    temporary_path = path.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _merged_manifest_lines(
    path: Path,
    generated_lines: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    existing_lines: list[dict[str, object]] = []
    try:
        existing_manifest = json.loads(path.read_text(encoding="utf-8"))
        raw_lines = existing_manifest.get("lines")
        if isinstance(raw_lines, list):
            existing_lines = [line for line in raw_lines if isinstance(line, dict)]
    except Exception:
        pass

    merged: list[dict[str, object]] = []
    replaced_ids: set[str] = set()
    for existing_line in existing_lines:
        line_id = existing_line.get("id")
        if isinstance(line_id, str) and line_id in generated_lines:
            merged.append(generated_lines[line_id])
            replaced_ids.add(line_id)
        else:
            merged.append(existing_line)
    merged.extend(
        line
        for line_id, line in generated_lines.items()
        if line_id not in replaced_ids
    )
    return merged


def _subtitle_timings_by_line_id(path: Path) -> dict[str, list[dict[str, int | str]]]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    lines = manifest.get("lines")
    if not isinstance(lines, list):
        return {}

    timings_by_id: dict[str, list[dict[str, int | str]]] = {}
    for line in lines:
        if not isinstance(line, dict):
            continue
        line_id = line.get("id")
        if not isinstance(line_id, str):
            continue
        timings = _normalize_subtitle_timings(line.get("subtitle_timings"))
        if timings:
            timings_by_id[line_id] = timings
    return timings_by_id


def _subtitle_timings_from_tts(timing: TtsSubtitleTiming) -> list[dict[str, int | str]]:
    return [
        {"text": cue.text, "start_ms": cue.start_ms, "end_ms": cue.end_ms}
        for cue in timing.cues
    ]


def _normalize_subtitle_timings(value: object) -> list[dict[str, int | str]]:
    if not isinstance(value, list):
        return []
    timings: list[dict[str, int | str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        start_ms = item.get("start_ms")
        end_ms = item.get("end_ms")
        if (
            isinstance(text, str)
            and isinstance(start_ms, int)
            and isinstance(end_ms, int)
            and end_ms > start_ms
        ):
            timings.append({"text": text, "start_ms": start_ms, "end_ms": end_ms})
    return timings
