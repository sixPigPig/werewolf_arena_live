from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.live import (
    LiveEventRecord,
    LiveRunRecord,
    VoiceAudioChunkRecord,
    VoiceUtteranceRecord,
)
from app.werewolf.private_memory_cleanup import (
    REDACTED_PRIVATE_MEMORY_PAYLOAD,
    cleanup_private_round_memory,
)


def test_private_round_memory_cleanup_is_dry_run_transactional_and_reentrant() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    sentinel = "SENTINEL_WOLF_PRIVATE_PLAN_刀10号_嫁祸12号"
    now = datetime.now(UTC)

    with TestingSessionLocal() as db:
        db.add(
            LiveRunRecord(
                run_id="run_private_cleanup",
                session_id="game_private_cleanup",
                status="complete",
                villager_model="test-model",
                werewolf_model="test-model",
                seed=21,
                max_rounds=8,
                rule_set_id="starter_6",
                rule_set={"id": "starter_6"},
                player_configs=[],
                lineup_quality_warnings=[],
                created_at=now,
            )
        )
        db.add_all(
            [
                LiveEventRecord(
                    run_id="run_private_cleanup",
                    event_id=1,
                    session_id="game_private_cleanup",
                    type="model_response_delta",
                    round=4,
                    phase="summary",
                    actor="10号玩家",
                    action="summarize",
                    payload={"visible_text": sentinel, "is_public": True},
                    created_at=now,
                ),
                LiveEventRecord(
                    run_id="run_private_cleanup",
                    event_id=2,
                    session_id="game_private_cleanup",
                    type="state_updated",
                    round=4,
                    phase="summary",
                    actor=None,
                    action="summarize",
                    payload={"public_summary": "第4轮；1号玩家被放逐。"},
                    created_at=now,
                ),
                LiveEventRecord(
                    run_id="run_private_cleanup",
                    event_id=3,
                    session_id="game_private_cleanup",
                    type="model_response_delta",
                    round=4,
                    phase="day",
                    actor="5号玩家",
                    action="debate",
                    payload={"visible_text": "我认为10号可疑。"},
                    created_at=now,
                ),
            ]
        )
        db.add(
            VoiceUtteranceRecord(
                utterance_id="voice_private_cleanup",
                run_id="run_private_cleanup",
                session_id="game_private_cleanup",
                source_event_id=1,
                last_source_event_id=1,
                request_id="req-private-cleanup",
                speaker_kind="player",
                speaker_name="10号玩家",
                speaker="player",
                action="summarize",
                text=sentinel,
                text_hash="0" * 64,
                audio_format="pcm",
                sample_rate=24000,
                mime_type="audio/L16",
                status="complete",
                duration_ms=100,
                created_at=now,
                updated_at=now,
                completed_at=now,
            )
        )
        db.add(
            VoiceAudioChunkRecord(
                utterance_id="voice_private_cleanup",
                chunk_index=0,
                audio=b"secret-audio",
                byte_length=12,
                created_at=now,
            )
        )
        db.commit()

        dry_run = cleanup_private_round_memory(db)

        assert dry_run.applied is False
        assert dry_run.run_count == 1
        assert dry_run.event_count == 1
        assert dry_run.voice_count == 1
        assert dry_run.audio_chunk_count == 1
        assert dry_run.failure_count == 0
        assert db.get(LiveEventRecord, ("run_private_cleanup", 1)).payload == {
            "visible_text": sentinel,
            "is_public": True,
        }
        assert db.get(VoiceUtteranceRecord, "voice_private_cleanup") is not None

        applied = cleanup_private_round_memory(db, apply=True)
        db.commit()
        db.expire_all()

        assert applied == type(applied)(
            applied=True,
            run_count=1,
            event_count=1,
            voice_count=1,
            audio_chunk_count=1,
            failure_count=0,
        )
        assert db.get(LiveEventRecord, ("run_private_cleanup", 1)).payload == (
            REDACTED_PRIVATE_MEMORY_PAYLOAD
        )
        assert db.get(LiveEventRecord, ("run_private_cleanup", 2)).payload == {
            "public_summary": "第4轮；1号玩家被放逐。"
        }
        assert db.get(LiveEventRecord, ("run_private_cleanup", 3)).payload == {
            "visible_text": "我认为10号可疑。"
        }
        assert db.get(VoiceUtteranceRecord, "voice_private_cleanup") is None
        assert list(db.scalars(select(VoiceAudioChunkRecord))) == []

        repeated = cleanup_private_round_memory(db, apply=True)

        assert repeated.event_count == 0
        assert repeated.voice_count == 0
        assert repeated.audio_chunk_count == 0
        assert repeated.run_count == 0
