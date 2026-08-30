from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.judge_voice_asset import JudgeVoiceAssetRecord
from app.shared.judge_voice_assets import list_judge_voice_assets
from app.shared.volcengine_tts import mime_type_for_format


class JudgeVoiceAssetImportError(RuntimeError):
    pass


@dataclass(frozen=True)
class JudgeVoiceAssetImportResult:
    scanned_count: int
    imported_count: int
    updated_count: int
    reused_count: int
    missing_count: int
    byte_count: int


def import_judge_voice_assets(
    *,
    asset_dir: Path,
    audio_format: str,
    sample_rate: int,
    db: Session,
) -> JudgeVoiceAssetImportResult:
    scanned = imported = updated = reused = missing = byte_count = 0
    root = asset_dir.resolve()
    try:
        for asset in list_judge_voice_assets(
            asset_dir=asset_dir,
            audio_format=audio_format,
        ):
            scanned += 1
            path = (root / asset.filename).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                missing += 1
                continue
            data = path.read_bytes()
            checksum = hashlib.sha256(data).hexdigest()
            byte_count += len(data)
            record = db.get(JudgeVoiceAssetRecord, asset.id)
            values = {
                "text": asset.text,
                "category": asset.category,
                "template_id": asset.template_id,
                "seat_number": asset.seat_number,
                "audio_format": audio_format,
                "sample_rate": sample_rate,
                "mime_type": mime_type_for_format(audio_format),
                "data": data,
                "sha256": checksum,
                "size_bytes": len(data),
                "subtitle_timings": asset.subtitle_timings,
                "source": "migrated",
            }
            if record is None:
                db.add(JudgeVoiceAssetRecord(id=asset.id, **values))
                imported += 1
                continue
            if _record_matches(record, values):
                reused += 1
                continue
            for key, value in values.items():
                setattr(record, key, value)
            updated += 1
        db.commit()
    except (OSError, SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise JudgeVoiceAssetImportError("迁移法官语音资产失败") from exc
    return JudgeVoiceAssetImportResult(
        scanned_count=scanned,
        imported_count=imported,
        updated_count=updated,
        reused_count=reused,
        missing_count=missing,
        byte_count=byte_count,
    )


def _record_matches(record: JudgeVoiceAssetRecord, values: dict[str, object]) -> bool:
    return all(getattr(record, key) == value for key, value in values.items())
