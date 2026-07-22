from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.v2.models import (
    V2GameRecord,
    V2GameRecordEvent,
    V2GameRun,
    V2LivePresentation,
    V2VoiceAsset,
)


class V2RepositoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class V2ActionClaim:
    game_id: str
    run_id: str
    action_id: str


@dataclass(frozen=True)
class V2PresentationIdentity:
    game_id: str
    run_id: str
    action_id: str
    presentation_seq: int
    presentation_id: str
    speech_id: str
    segment_index: int
    voice_asset_id: str
    storage_key: str
    subtitle_text: str


class V2ActionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def claim_action(
        self,
        *,
        game_id: str,
        action_id: str,
        context: dict[str, Any],
    ) -> V2ActionClaim | None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            if game.status != "ready":
                return None
            run = _run(db, game.current_run_id)
            game.status = "generating"
            run.status = "generating"
            _append_event(
                db,
                game=game,
                run_id=run.run_id,
                event_type="action_opened",
                payload={
                    "action_id": action_id,
                    "context": {**context, "run_id": run.run_id},
                },
            )
            return V2ActionClaim(game_id=game.game_id, run_id=run.run_id, action_id=action_id)

    def append_event(
        self,
        *,
        game_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            event = _append_event(
                db,
                game=game,
                run_id=game.current_run_id,
                event_type=event_type,
                payload=payload,
            )
            return event.record_seq

    def open_presentation(
        self,
        *,
        claim: V2ActionClaim,
        presentation_id: str,
        speech_id: str,
        voice_asset_id: str,
        subtitle_text: str,
        sample_rate: int,
    ) -> V2PresentationIdentity:
        storage_key = f"{claim.game_id}/{voice_asset_id}.wav"
        with self._session_factory.begin() as db:
            game = _locked_game(db, claim.game_id)
            if game.status != "generating":
                raise V2RepositoryError(f"cannot open presentation from {game.status}")
            presentation_seq = game.last_presentation_seq + 1
            _append_event(
                db,
                game=game,
                run_id=claim.run_id,
                event_type="speech_opened",
                payload={
                    "action_id": claim.action_id,
                    "presentation_id": presentation_id,
                    "presentation_seq": presentation_seq,
                    "speech_id": speech_id,
                },
            )
            committed = _append_event(
                db,
                game=game,
                run_id=claim.run_id,
                event_type="speech_segment_committed",
                payload={
                    "action_id": claim.action_id,
                    "presentation_id": presentation_id,
                    "presentation_seq": presentation_seq,
                    "speech_id": speech_id,
                    "segment_index": 0,
                    "text": subtitle_text,
                },
            )
            _append_event(
                db,
                game=game,
                run_id=claim.run_id,
                event_type="speech_sealed",
                payload={"action_id": claim.action_id, "speech_id": speech_id},
            )
            voice = V2VoiceAsset(
                voice_asset_id=voice_asset_id,
                game_id=claim.game_id,
                run_id=claim.run_id,
                action_id=claim.action_id,
                presentation_id=presentation_id,
                speech_id=speech_id,
                segment_index=0,
                state="writing",
                storage_key=storage_key,
                mime_type="audio/wav",
                sample_rate=sample_rate,
                channels=1,
            )
            db.add(voice)
            db.flush()
            presentation = V2LivePresentation(
                game_id=claim.game_id,
                presentation_seq=presentation_seq,
                presentation_id=presentation_id,
                action_id=claim.action_id,
                run_id=claim.run_id,
                phase_id="opening",
                actor_kind="judge",
                actor_id="judge",
                speech_id=speech_id,
                segment_index=0,
                source_event_id=committed.event_id,
                state="active",
                subtitle_text=subtitle_text,
                subtitle_timings=[],
                voice_asset_id=voice_asset_id,
                audio_asset_id=None,
                audio_mime_type=None,
                audio_duration_ms=None,
            )
            db.add(presentation)
            game.last_presentation_seq = presentation_seq
            game.status = "broadcasting"
            _run(db, claim.run_id).status = "broadcasting"
        return V2PresentationIdentity(
            game_id=claim.game_id,
            run_id=claim.run_id,
            action_id=claim.action_id,
            presentation_seq=presentation_seq,
            presentation_id=presentation_id,
            speech_id=speech_id,
            segment_index=0,
            voice_asset_id=voice_asset_id,
            storage_key=storage_key,
            subtitle_text=subtitle_text,
        )

    def mark_finalizing(self, *, game_id: str, tts_attempt_id: str, sample_count: int) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            game.status = "finalizing"
            _run(db, game.current_run_id).status = "finalizing"
            _append_event(
                db,
                game=game,
                run_id=game.current_run_id,
                event_type="tts_stream_completed",
                payload={"tts_attempt_id": tts_attempt_id, "sample_count": sample_count},
            )

    def mark_voice_ready(
        self,
        *,
        identity: V2PresentationIdentity,
        sample_count: int,
        duration_ms: int,
        pcm_sha256: str,
        size_bytes: int,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, identity.game_id)
            voice = db.get(V2VoiceAsset, identity.voice_asset_id)
            if voice is None or voice.state != "writing":
                raise V2RepositoryError("voice asset is not writable")
            voice.state = "ready"
            voice.sample_count = sample_count
            voice.duration_ms = duration_ms
            voice.pcm_sha256 = pcm_sha256
            voice.size_bytes = size_bytes
            voice.completed_at = _now()
            presentation = db.get(
                V2LivePresentation,
                (identity.game_id, identity.presentation_seq),
            )
            if presentation is None:
                raise V2RepositoryError("presentation disappeared")
            presentation.audio_asset_id = identity.voice_asset_id
            presentation.audio_mime_type = "audio/wav"
            presentation.audio_duration_ms = duration_ms
            _append_event(
                db,
                game=game,
                run_id=identity.run_id,
                event_type="voice_asset_saved",
                payload={
                    "action_id": identity.action_id,
                    "voice_asset_id": identity.voice_asset_id,
                    "sample_count": sample_count,
                    "duration_ms": duration_ms,
                    "pcm_sha256": pcm_sha256,
                    "size_bytes": size_bytes,
                },
            )

    def complete_action(
        self,
        *,
        identity: V2PresentationIdentity,
        final_chunk_index: int,
        final_sample_cursor: int,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, identity.game_id)
            presentation = db.get(
                V2LivePresentation,
                (identity.game_id, identity.presentation_seq),
            )
            voice = db.get(V2VoiceAsset, identity.voice_asset_id)
            if presentation is None or voice is None or voice.state != "ready":
                raise V2RepositoryError("action cannot complete without ready voice")
            presentation.state = "closed"
            presentation.closed_at = _now()
            game.status = "awaiting_observation"
            run = _run(db, identity.run_id)
            run.status = "awaiting_observation"
            _append_event(
                db,
                game=game,
                run_id=identity.run_id,
                event_type="audio_drained",
                payload={
                    "action_id": identity.action_id,
                    "presentation_id": identity.presentation_id,
                    "final_chunk_index": final_chunk_index,
                    "final_sample_cursor": final_sample_cursor,
                },
            )
            _append_event(
                db,
                game=game,
                run_id=identity.run_id,
                event_type="speech_closed",
                payload={
                    "action_id": identity.action_id,
                    "presentation_id": identity.presentation_id,
                    "speech_id": identity.speech_id,
                },
            )
            _append_event(
                db,
                game=game,
                run_id=identity.run_id,
                event_type="action_succeeded",
                payload={
                    "action_id": identity.action_id,
                    "voice_asset_id": identity.voice_asset_id,
                    "result": "audio_drained_and_voice_saved",
                },
            )

    def fail_action(
        self,
        *,
        claim: V2ActionClaim,
        failure_kind: str,
        failure_code: str,
        identity: V2PresentationIdentity | None,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, claim.game_id)
            game.status = "failed"
            run = _run(db, claim.run_id)
            run.status = "failed"
            run.completed_at = _now()
            if identity is not None:
                presentation = db.get(
                    V2LivePresentation,
                    (identity.game_id, identity.presentation_seq),
                )
                if presentation is not None and presentation.state == "active":
                    presentation.state = "failed"
                    presentation.closed_at = _now()
                voice = db.get(V2VoiceAsset, identity.voice_asset_id)
                if voice is not None and voice.state == "writing":
                    voice.state = "failed"
                    voice.completed_at = _now()
                    _append_event(
                        db,
                        game=game,
                        run_id=claim.run_id,
                        event_type="voice_recording_failed",
                        payload={
                            "action_id": claim.action_id,
                            "voice_asset_id": identity.voice_asset_id,
                            "failure_code": failure_code,
                        },
                    )
            _append_event(
                db,
                game=game,
                run_id=claim.run_id,
                event_type="action_failed",
                payload={
                    "action_id": claim.action_id,
                    "failure_kind": failure_kind,
                    "failure_code": failure_code,
                },
            )


def _locked_game(db: Session, game_id: str) -> V2GameRecord:
    game = db.scalar(
        select(V2GameRecord).where(V2GameRecord.game_id == game_id).with_for_update()
    )
    if game is None:
        raise V2RepositoryError(f"unknown game {game_id}")
    return game


def _run(db: Session, run_id: str) -> V2GameRun:
    run = db.get(V2GameRun, run_id)
    if run is None:
        raise V2RepositoryError(f"unknown run {run_id}")
    return run


def _append_event(
    db: Session,
    *,
    game: V2GameRecord,
    run_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> V2GameRecordEvent:
    next_seq = game.last_record_seq + 1
    event = V2GameRecordEvent(
        game_id=game.game_id,
        event_id=next_seq,
        record_seq=next_seq,
        run_id=run_id,
        event_type=event_type,
        payload_schema_version=1,
        payload=payload,
    )
    db.add(event)
    game.last_record_seq = next_seq
    return event


def _now() -> datetime:
    return datetime.now(tz=UTC)
