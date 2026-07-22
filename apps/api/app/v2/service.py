from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.v2.models import (
    V2GameRecord,
    V2GameRecordEvent,
    V2GameRun,
    V2LivePresentation,
    V2VoiceAsset,
)


class V2RecordNotFound(LookupError):
    pass


class V2VoiceAssetUnavailable(RuntimeError):
    pass


def create_ready_game(
    db: Session,
    *,
    title: str,
    rule_snapshot: dict[str, Any] | None = None,
    players_snapshot: list[dict[str, Any]] | None = None,
) -> tuple[V2GameRecord, V2GameRun]:
    game_id = f"v2_game_{uuid4().hex[:16]}"
    run_id = f"v2_run_{uuid4().hex[:16]}"
    game = V2GameRecord(
        game_id=game_id,
        title=title.strip(),
        status="ready",
        current_run_id=run_id,
        record_schema_version=1,
        last_record_seq=1,
        last_presentation_seq=0,
        rule_snapshot=rule_snapshot or {},
        players_snapshot=players_snapshot or [],
    )
    run = V2GameRun(
        run_id=run_id,
        game_id=game_id,
        attempt_no=1,
        status="ready",
    )
    created = V2GameRecordEvent(
        game_id=game_id,
        event_id=1,
        record_seq=1,
        run_id=run_id,
        event_type="game_created",
        payload_schema_version=1,
        payload={
            "title": game.title,
            "start_mode": "first_ready_viewer",
            "creation_source": (
                "existing_mobile_lobby" if rule_snapshot is not None else "direct_v2"
            ),
            "rule_set_id": (rule_snapshot or {}).get("rule_set", {}).get("id"),
            "player_count": len(players_snapshot or []),
        },
    )
    db.add(game)
    db.flush()
    db.add(run)
    db.flush()
    db.add(created)
    db.commit()
    db.refresh(game)
    db.refresh(run)
    return game, run


def get_game(db: Session, game_id: str) -> V2GameRecord:
    record = db.get(V2GameRecord, game_id)
    if record is None:
        raise V2RecordNotFound(game_id)
    return record


def current_presentation(db: Session, game_id: str) -> V2LivePresentation | None:
    get_game(db, game_id)
    return db.scalar(
        select(V2LivePresentation)
        .where(
            V2LivePresentation.game_id == game_id,
            V2LivePresentation.state == "active",
        )
        .order_by(V2LivePresentation.presentation_seq.desc())
        .limit(1)
    )


def get_voice_asset(db: Session, *, game_id: str, voice_asset_id: str) -> V2VoiceAsset:
    asset = db.get(V2VoiceAsset, voice_asset_id)
    if asset is None or asset.game_id != game_id:
        raise V2RecordNotFound(f"{game_id}:{voice_asset_id}")
    return asset


def list_games(
    db: Session,
    *,
    page: int,
    page_size: int,
) -> tuple[list[V2GameRecord], int]:
    total = int(db.scalar(select(func.count()).select_from(V2GameRecord)) or 0)
    records = list(
        db.scalars(
            select(V2GameRecord)
            .order_by(V2GameRecord.created_at.desc(), V2GameRecord.game_id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return records, total


def game_detail(
    db: Session,
    game_id: str,
) -> tuple[
    V2GameRecord,
    list[V2GameRun],
    list[V2GameRecordEvent],
    list[V2LivePresentation],
    list[V2VoiceAsset],
]:
    game = get_game(db, game_id)
    runs = list(
        db.scalars(
            select(V2GameRun)
            .where(V2GameRun.game_id == game_id)
            .order_by(V2GameRun.attempt_no.asc())
        )
    )
    events = list(
        db.scalars(
            select(V2GameRecordEvent)
            .where(V2GameRecordEvent.game_id == game_id)
            .order_by(V2GameRecordEvent.record_seq.asc())
        )
    )
    presentations = list(
        db.scalars(
            select(V2LivePresentation)
            .where(V2LivePresentation.game_id == game_id)
            .order_by(V2LivePresentation.presentation_seq.asc())
        )
    )
    voices = list(
        db.scalars(
            select(V2VoiceAsset)
            .where(V2VoiceAsset.game_id == game_id)
            .order_by(V2VoiceAsset.created_at.asc(), V2VoiceAsset.voice_asset_id.asc())
        )
    )
    return game, runs, events, presentations, voices


def voice_asset_path(*, root: Path, asset: V2VoiceAsset) -> Path:
    if asset.state != "ready":
        raise V2VoiceAssetUnavailable(asset.voice_asset_id)
    safe_root = root.resolve()
    path = (safe_root / asset.storage_key).resolve()
    if safe_root not in path.parents or not path.is_file():
        raise V2VoiceAssetUnavailable(asset.voice_asset_id)
    return path


def server_now() -> datetime:
    return datetime.now(tz=UTC)
