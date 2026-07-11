from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.werewolf.judge_voice_assets import JudgeVoiceAsset, list_judge_voice_assets


@dataclass(frozen=True)
class AdminJudgeVoiceCategory:
    name: str
    total: int
    available: int
    missing: int


@dataclass(frozen=True)
class AdminJudgeVoiceListResult:
    records: list[JudgeVoiceAsset]
    categories: list[AdminJudgeVoiceCategory]
    page: int
    page_size: int
    total: int
    pages: int
    asset_total: int
    available_total: int
    missing_total: int
    byte_total: int


def list_admin_judge_voice_assets(
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
    assets = list_judge_voice_assets(
        asset_dir=asset_dir,
        audio_format=audio_format,
    )
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
    records = filtered[start : start + page_size]
    available_total = sum(1 for asset in assets if asset.exists)
    return AdminJudgeVoiceListResult(
        records=records,
        categories=categories,
        page=page,
        page_size=page_size,
        total=total,
        pages=pages,
        asset_total=len(assets),
        available_total=available_total,
        missing_total=len(assets) - available_total,
        byte_total=sum(max(0, asset.byte_size or 0) for asset in assets),
    )


def get_admin_judge_voice_asset(
    *,
    asset_dir: Path,
    audio_format: str,
    line_id: str,
) -> JudgeVoiceAsset | None:
    try:
        assets = list_judge_voice_assets(
            asset_dir=asset_dir,
            audio_format=audio_format,
            line_ids=[line_id],
        )
    except ValueError:
        return None
    return assets[0] if assets else None


def asset_file_path(asset_dir: Path, asset: JudgeVoiceAsset) -> Path | None:
    root = asset_dir.resolve()
    path = (root / asset.filename).resolve()
    if not path.is_relative_to(root):
        return None
    return path


def _category_summaries(
    assets: list[JudgeVoiceAsset],
) -> list[AdminJudgeVoiceCategory]:
    grouped: dict[str, list[JudgeVoiceAsset]] = {}
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
    asset: JudgeVoiceAsset,
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
    return lambda asset: (asset.category, asset.template_id or asset.id, asset.seat_number or 0, asset.id)


def _clean_filter(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None
