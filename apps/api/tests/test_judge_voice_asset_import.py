from __future__ import annotations

import hashlib
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

from app.admin.voice_assets import get_admin_judge_voice_audio, list_admin_judge_voice_assets
from app.db.base import Base
from app.judge_voice_asset_import import import_judge_voice_assets
from app.models.judge_voice_asset import JudgeVoiceAssetRecord
from app.models.judge_voice_asset import JudgeVoiceGenerationJob
from app.admin.voice_jobs import create_voice_generation_job, run_next_voice_generation_job
from app.shared.judge_voice_assets import list_judge_voice_line_definitions
from app.core.config import settings


def test_import_judge_voice_assets_is_idempotent_and_updates_changed_audio(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    asset_dir = tmp_path / "judge-voice"
    asset_dir.mkdir()
    audio_path = asset_dir / "game_intro.mp3"
    audio_path.write_bytes(b"first-audio")
    (asset_dir / "manifest.json").write_text(
        json.dumps(
            {
                "lines": [
                    {
                        "id": "game_intro",
                        "subtitle_timings": [
                            {"text": "本局", "start_ms": 0, "end_ms": 300}
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with Session(engine) as db:
        first = import_judge_voice_assets(
            asset_dir=asset_dir,
            audio_format="mp3",
            sample_rate=24000,
            db=db,
        )
        second = import_judge_voice_assets(
            asset_dir=asset_dir,
            audio_format="mp3",
            sample_rate=24000,
            db=db,
        )
        audio_path.write_bytes(b"second-audio")
        third = import_judge_voice_assets(
            asset_dir=asset_dir,
            audio_format="mp3",
            sample_rate=24000,
            db=db,
        )
        record = db.get(JudgeVoiceAssetRecord, "game_intro")

    assert first.imported_count == 1
    assert first.missing_count == first.scanned_count - 1
    assert second.reused_count == 1
    assert second.imported_count == 0
    assert third.updated_count == 1
    assert record is not None
    assert record.data == b"second-audio"
    assert record.size_bytes == len(b"second-audio")
    assert record.sha256 == hashlib.sha256(b"second-audio").hexdigest()
    assert record.subtitle_timings == [{"text": "本局", "start_ms": 0, "end_ms": 300}]
    engine.dispose()


def test_persistent_voice_worker_completes_empty_missing_job_and_fails_disabled_tts(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "ark_tts_enabled", False)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        for index, line in enumerate(list_judge_voice_line_definitions()):
            db.add(JudgeVoiceAssetRecord(
                id=line.id, text=line.text, category=line.category,
                template_id=line.template_id, seat_number=line.seat_number,
                audio_format="mp3", sample_rate=24000, mime_type="audio/mpeg",
                data=f"audio-{index}".encode(), sha256=f"{index:064x}",
                size_bytes=len(f"audio-{index}"), subtitle_timings=[], source="test",
            ))
        missing, _ = create_voice_generation_job(
            db, actor_user_id=1, mode="missing", line_ids=None,
            idempotency_key="worker-missing-001",
        )
        all_job, _ = create_voice_generation_job(
            db, actor_user_id=1, mode="all", line_ids=["game_intro"],
            idempotency_key="worker-all-001",
        )
        db.commit()
        missing_id, all_id = missing.id, all_job.id
    first_id = run_next_voice_generation_job(factory)
    second_id = run_next_voice_generation_job(factory)
    with factory() as db:
        missing = db.get(JudgeVoiceGenerationJob, missing_id)
        all_job = db.get(JudgeVoiceGenerationJob, all_id)
    assert {first_id, second_id} == {missing_id, all_id}
    assert missing is not None and missing.status == "completed"
    assert missing.total_count == 0
    assert all_job is not None and all_job.status == "failed"
    assert all_job.error_code == "tts_disabled"
    engine.dispose()


def test_admin_voice_inventory_switches_to_database_without_loading_audio_in_list(
    tmp_path,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    asset_dir = tmp_path / "judge-voice"
    asset_dir.mkdir()
    legacy_audio = b"legacy-audio"
    (asset_dir / "game_intro.mp3").write_bytes(legacy_audio)

    with Session(engine) as db:
        db.add(
            JudgeVoiceAssetRecord(
                id="game_intro",
                text="本局游戏开始，请所有玩家确认自己的身份牌。",
                category="开局",
                template_id=None,
                seat_number=None,
                audio_format="mp3",
                sample_rate=24000,
                mime_type="audio/mpeg",
                data=b"database-audio",
                sha256=hashlib.sha256(b"database-audio").hexdigest(),
                size_bytes=len(b"database-audio"),
                subtitle_timings=[],
                source="migrated",
            )
        )
        db.commit()
        result = list_admin_judge_voice_assets(
            db,
            asset_dir=asset_dir,
            audio_format="mp3",
            page=1,
            page_size=20,
            query_text="game_intro",
            category=None,
            availability=None,
            sort="category",
        )
        audio = get_admin_judge_voice_audio(
            db,
            asset_dir=asset_dir,
            audio_format="mp3",
            line_id="game_intro",
        )

    assert result.storage_mode == "database"
    assert result.available_total == 1
    assert result.missing_total == result.asset_total - 1
    assert result.records[0].byte_size == len(b"database-audio")
    assert audio is not None
    assert audio.content == b"database-audio"
    engine.dispose()
