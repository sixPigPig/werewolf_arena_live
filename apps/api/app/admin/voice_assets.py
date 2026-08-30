from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.judge_voice_asset import JudgeVoiceAssetRecord
from app.shared.judge_voice_assets import (
    JudgeVoiceAsset,
    list_judge_voice_assets,
    list_judge_voice_line_definitions,
)
from app.shared.tts_text import is_static_judge_voice_asset_used


@dataclass(frozen=True)
class AdminJudgeVoiceAsset:
    id: str
    text: str
    category: str
    used: bool
    exists: bool
    byte_size: int | None
    template_id: str | None
    seat_number: int | None
    subtitle_cue_count: int


@dataclass(frozen=True)
class AdminJudgeVoiceAudio:
    content: bytes
    mime_type: str


@dataclass(frozen=True)
class AdminJudgeVoiceCategory:
    name: str
    total: int
    available: int
    missing: int


@dataclass(frozen=True)
class AdminJudgeVoiceListResult:
    records: list[AdminJudgeVoiceAsset]
    categories: list[AdminJudgeVoiceCategory]
    storage_mode: str
    page: int
    page_size: int
    total: int
    pages: int
    asset_total: int
    available_total: int
    missing_total: int
    byte_total: int


def list_admin_judge_voice_assets(
    db: Session,
    *,
    asset_dir: Path,
    audio_format: str,
    page: int,
    page_size: int,
    query_text: str | None,
    category: str | None,
    availability: str | None,
    sort: str,
) -> AdminJudgeVoiceListResult:
    database_count = int(db.scalar(select(func.count()).select_from(JudgeVoiceAssetRecord)) or 0)
    if database_count:
        assets = _database_assets(db)
        storage_mode = "database"
    else:
        assets = [
            _legacy_asset(asset)
            for asset in list_judge_voice_assets(
                asset_dir=asset_dir,
                audio_format=audio_format,
            )
        ]
        storage_mode = "legacy_static_directory"
    categories = _category_summaries(assets)
    normalized_query = _clean_filter(query_text)
    normalized_category = _clean_filter(category)
    filtered = [
        asset
        for asset in assets
        if _matches_asset(
            asset,
            query_text=normalized_query,
            category=normalized_category,
            availability=availability,
        )
    ]
    filtered.sort(key=_sort_key(sort), reverse=sort.startswith("-"))
    total = len(filtered)
    pages = (total + page_size - 1) // page_size if total else 0
    start = (page - 1) * page_size
    available_total = sum(1 for asset in assets if asset.exists)
    return AdminJudgeVoiceListResult(
        records=filtered[start : start + page_size],
        categories=categories,
        storage_mode=storage_mode,
        page=page,
        page_size=page_size,
        total=total,
        pages=pages,
        asset_total=len(assets),
        available_total=available_total,
        missing_total=len(assets) - available_total,
        byte_total=sum(max(0, asset.byte_size or 0) for asset in assets),
    )


def get_admin_judge_voice_audio(
    db: Session,
    *,
    asset_dir: Path,
    audio_format: str,
    line_id: str,
) -> AdminJudgeVoiceAudio | None:
    row = db.execute(
        select(JudgeVoiceAssetRecord.data, JudgeVoiceAssetRecord.mime_type).where(
            JudgeVoiceAssetRecord.id == line_id
        )
    ).one_or_none()
    if row is not None:
        return AdminJudgeVoiceAudio(content=bytes(row.data), mime_type=str(row.mime_type))
    try:
        assets = list_judge_voice_assets(
            asset_dir=asset_dir,
            audio_format=audio_format,
            line_ids=[line_id],
        )
    except ValueError:
        return None
    asset = assets[0] if assets else None
    if asset is None or not asset.exists:
        return None
    path = _asset_file_path(asset_dir, asset)
    if path is None or not path.is_file():
        return None
    return AdminJudgeVoiceAudio(content=path.read_bytes(), mime_type=_legacy_mime(audio_format))


def _database_assets(db: Session) -> list[AdminJudgeVoiceAsset]:
    rows = db.execute(
        select(
            JudgeVoiceAssetRecord.id,
            JudgeVoiceAssetRecord.text,
            JudgeVoiceAssetRecord.category,
            JudgeVoiceAssetRecord.size_bytes,
            JudgeVoiceAssetRecord.template_id,
            JudgeVoiceAssetRecord.seat_number,
            JudgeVoiceAssetRecord.subtitle_timings,
        )
    )
    records = {
        str(row.id): AdminJudgeVoiceAsset(
            id=str(row.id),
            text=str(row.text),
            category=str(row.category),
            used=is_static_judge_voice_asset_used(
                str(row.id),
                template_id=str(row.template_id) if row.template_id is not None else None,
            ),
            exists=True,
            byte_size=max(0, int(row.size_bytes)),
            template_id=str(row.template_id) if row.template_id is not None else None,
            seat_number=int(row.seat_number) if row.seat_number is not None else None,
            subtitle_cue_count=len(row.subtitle_timings) if isinstance(row.subtitle_timings, list) else 0,
        )
        for row in rows
    }
    return [
        records.get(
            line.id,
            AdminJudgeVoiceAsset(
                id=line.id,
                text=line.text,
                category=line.category,
                used=is_static_judge_voice_asset_used(
                    line.id,
                    template_id=line.template_id,
                ),
                exists=False,
                byte_size=None,
                template_id=line.template_id,
                seat_number=line.seat_number,
                subtitle_cue_count=0,
            ),
        )
        for line in list_judge_voice_line_definitions()
    ]


def _legacy_asset(asset: JudgeVoiceAsset) -> AdminJudgeVoiceAsset:
    return AdminJudgeVoiceAsset(
        id=asset.id,
        text=asset.text,
        category=asset.category,
        used=is_static_judge_voice_asset_used(
            asset.id,
            template_id=asset.template_id,
        ),
        exists=asset.exists,
        byte_size=asset.byte_size,
        template_id=asset.template_id,
        seat_number=asset.seat_number,
        subtitle_cue_count=len(asset.subtitle_timings),
    )


def _asset_file_path(asset_dir: Path, asset: JudgeVoiceAsset) -> Path | None:
    root = asset_dir.resolve()
    path = (root / asset.filename).resolve()
    return path if path.is_relative_to(root) else None


def _legacy_mime(audio_format: str) -> str:
    return {"mp3": "audio/mpeg", "wav": "audio/wav", "pcm": "audio/L16"}.get(
        audio_format.lower(), "application/octet-stream"
    )


def _category_summaries(assets: list[AdminJudgeVoiceAsset]) -> list[AdminJudgeVoiceCategory]:
    grouped: dict[str, list[AdminJudgeVoiceAsset]] = {}
    for asset in assets:
        grouped.setdefault(asset.category, []).append(asset)
    return [
        AdminJudgeVoiceCategory(
            name=name,
            total=len(records),
            available=sum(1 for record in records if record.exists),
            missing=sum(1 for record in records if not record.exists),
        )
        for name, records in sorted(grouped.items())
    ]


def _matches_asset(
    asset: AdminJudgeVoiceAsset,
    *,
    query_text: str | None,
    category: str | None,
    availability: str | None,
) -> bool:
    if category is not None and asset.category != category:
        return False
    if availability == "available" and not asset.exists:
        return False
    if availability == "missing" and asset.exists:
        return False
    if query_text is None:
        return True
    needle = query_text.casefold()
    return needle in asset.id.casefold() or needle in asset.text.casefold()


def _sort_key(sort: str):
    field = sort.removeprefix("-")
    if field == "id":
        return lambda asset: (asset.id,)
    if field == "byte_size":
        return lambda asset: (asset.byte_size or -1, asset.id)
    return lambda asset: (
        asset.category,
        asset.template_id or asset.id,
        asset.seat_number or 0,
        asset.id,
    )


def _clean_filter(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
