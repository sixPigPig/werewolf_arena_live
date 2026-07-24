from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import secrets
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.v2.ability_runtime import compile_ability_runtime_snapshot
from app.v2.models import (
    V2AbilityActivation,
    V2AbilityInstance,
    V2ActionWindow,
    V2EffectIntent,
    V2GameRecord,
    V2GameRecordEvent,
    V2GameRun,
    V2GodViewAccessGrant,
    V2LivePresentation,
    V2MatchState,
    V2KnowledgeFact,
    V2PlayerState,
    V2RoleAssignment,
    V2RoleAssignmentBatch,
    V2VoiceAsset,
)
from app.v2.god_view_access import (
    issue_god_view_access_token,
    verify_god_view_access_token,
)
from app.v2.role_assignment import assign_private_roles


class V2RecordNotFound(LookupError):
    pass


class V2VoiceAssetUnavailable(RuntimeError):
    pass


class V2RoleAssignmentStateError(RuntimeError):
    pass


class V2GodViewAccessDenied(PermissionError):
    pass


class V2GodViewUnavailable(RuntimeError):
    pass


def create_waiting_game(
    db: Session,
    *,
    title: str,
    rule_snapshot: dict[str, Any] | None = None,
    players_snapshot: list[dict[str, Any]] | None = None,
) -> tuple[V2GameRecord, V2GameRun, str]:
    game_id = f"v2_game_{uuid4().hex[:16]}"
    run_id = f"v2_run_{uuid4().hex[:16]}"
    god_view_token, god_view_token_hash = issue_god_view_access_token()
    assignment_id: str | None = None
    private_seed: str | None = None
    assignment_result = None
    ability_snapshot: dict[str, Any] = {}
    if rule_snapshot is not None or players_snapshot is not None:
        if rule_snapshot is None or players_snapshot is None:
            raise ValueError("rule and player snapshots must be provided together")
        assignment_id = f"v2_roles_{uuid4().hex[:16]}"
        private_seed = secrets.token_hex(32)
        assignment_result = assign_private_roles(
            players_snapshot=players_snapshot,
            rule_snapshot=rule_snapshot,
            seed_hex=private_seed,
        )
        ability_snapshot = compile_ability_runtime_snapshot(
            game_id=game_id,
            rule_snapshot=rule_snapshot,
            assignments=assignment_result.assignments,
        )
    initial_record_seq = 3 if assignment_result is not None else 1
    game = V2GameRecord(
        game_id=game_id,
        title=title.strip(),
        status="waiting_to_start",
        current_run_id=run_id,
        record_schema_version=1,
        last_record_seq=initial_record_seq,
        last_presentation_seq=0,
        phase_seq=1,
        phase_id="opening",
        phase_state="opening_ready",
        rule_snapshot=rule_snapshot or {},
        players_snapshot=players_snapshot or [],
        ability_snapshot=ability_snapshot,
        ability_snapshot_hash=(ability_snapshot or {}).get("snapshot_hash"),
    )
    run = V2GameRun(
        run_id=run_id,
        game_id=game_id,
        attempt_no=1,
        status="waiting_to_start",
        started_at=None,
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
    if assignment_result is not None:
        sheriff_enabled = bool((rule_snapshot or {}).get("rule_set", {}).get("sheriff_enabled"))
        db.add(
            V2MatchState(
                game_id=game_id,
                round_no=1,
                sheriff_badge_state="pending" if sheriff_enabled else "disabled",
            )
        )
    db.add(
        V2GodViewAccessGrant(
            game_id=game_id,
            token_sha256=god_view_token_hash,
        )
    )
    db.add(run)
    db.flush()
    db.add(created)
    if assignment_result is not None:
        assert assignment_id is not None
        assert private_seed is not None
        assignment_batch = V2RoleAssignmentBatch(
            assignment_id=assignment_id,
            game_id=game_id,
            seed_hex=private_seed,
            assignment_digest=assignment_result.digest,
            player_count=len(assignment_result.assignments),
        )
        db.add(assignment_batch)
        db.flush()
        db.add_all(
            [
                V2RoleAssignment(
                    game_id=game_id,
                    seat=item.seat,
                    assignment_id=assignment_id,
                    player_id=item.player_id,
                    role=item.role,
                    role_key=item.role_key,
                    team=item.team,
                )
                for item in assignment_result.assignments
            ]
        )
        db.add(
            V2GameRecordEvent(
                game_id=game_id,
                event_id=2,
                record_seq=2,
                run_id=run_id,
                event_type="roles_assigned",
                payload_schema_version=1,
                payload={
                    "assignment_id": assignment_id,
                    "assigned_count": len(assignment_result.assignments),
                    "visibility": "private_sealed",
                },
            )
        )
        db.add_all(
            [
                V2PlayerState(
                    game_id=game_id,
                    player_id=item.player_id,
                    seat=item.seat,
                    alive=True,
                    state={},
                )
                for item in assignment_result.assignments
            ]
        )
        db.add_all(
            [
                V2AbilityInstance(
                    ability_instance_id=item["ability_instance_id"],
                    game_id=game_id,
                    ability_id=item["ability_id"],
                    ability_version=item["ability_version"],
                    owner_scope=item["owner_scope"],
                    owner_id=item["owner_id"],
                    owner_role_key=item["owner_role_key"],
                    state=_initial_ability_state(item["ability_id"]),
                )
                for item in ability_snapshot["instances"]
            ]
        )
        db.add(
            V2GameRecordEvent(
                game_id=game_id,
                event_id=3,
                record_seq=3,
                run_id=run_id,
                event_type="ability_runtime_compiled",
                payload_schema_version=1,
                payload={
                    "ability_snapshot_hash": ability_snapshot["snapshot_hash"],
                    "registry_version": ability_snapshot["registry_version"],
                    "instance_count": len(ability_snapshot["instances"]),
                    "execution_enabled": ability_snapshot["execution_enabled"],
                },
            )
        )
    db.commit()
    db.refresh(game)
    db.refresh(run)
    return game, run, god_view_token


def get_game(db: Session, game_id: str) -> V2GameRecord:
    record = db.get(V2GameRecord, game_id)
    if record is None:
        raise V2RecordNotFound(game_id)
    return record


def get_match_state(db: Session, game_id: str) -> V2MatchState | None:
    get_game(db, game_id)
    return db.get(V2MatchState, game_id)


def current_presentation(
    db: Session,
    game_id: str,
    *,
    audience: str = "player_public",
) -> V2LivePresentation | None:
    get_game(db, game_id)
    allowed = (
        ("all", "god_view")
        if audience == "spectator_god_view"
        else ("all", "public")
    )
    return db.scalar(
        select(V2LivePresentation)
        .where(
            V2LivePresentation.game_id == game_id,
            V2LivePresentation.state == "active",
            V2LivePresentation.audience.in_(allowed),
        )
        .order_by(V2LivePresentation.presentation_seq.desc())
        .limit(1)
    )


def role_assignment_count(db: Session, game_id: str) -> int | None:
    expected_count = db.scalar(
        select(V2RoleAssignmentBatch.player_count).where(V2RoleAssignmentBatch.game_id == game_id)
    )
    if expected_count is None:
        return None
    actual_count = int(
        db.scalar(
            select(func.count())
            .select_from(V2RoleAssignment)
            .where(V2RoleAssignment.game_id == game_id)
        )
        or 0
    )
    if actual_count != expected_count:
        raise V2RoleAssignmentStateError("private role assignment batch is incomplete")
    return expected_count


def authorize_god_view(db: Session, *, game_id: str, token: str | None) -> None:
    grant = db.get(V2GodViewAccessGrant, game_id)
    if (
        grant is None
        or token is None
        or not verify_god_view_access_token(
            token=token,
            expected_sha256=grant.token_sha256,
        )
    ):
        raise V2GodViewAccessDenied(game_id)


def god_view_role_assignments(db: Session, game_id: str) -> list[V2RoleAssignment]:
    expected_count = role_assignment_count(db, game_id)
    if expected_count is None:
        raise V2GodViewUnavailable(game_id)
    assignments = list(
        db.scalars(
            select(V2RoleAssignment)
            .where(V2RoleAssignment.game_id == game_id)
            .order_by(V2RoleAssignment.seat.asc())
        )
    )
    if len(assignments) != expected_count:
        raise V2RoleAssignmentStateError("private role assignment batch is incomplete")
    return assignments


def player_state_map(db: Session, game_id: str) -> dict[str, V2PlayerState]:
    get_game(db, game_id)
    states = list(
        db.scalars(
            select(V2PlayerState).where(V2PlayerState.game_id == game_id)
        )
    )
    result = {item.player_id: item for item in states}
    if len(result) != len(states):
        raise V2RoleAssignmentStateError("duplicate V2 player state")
    return result


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
    list[V2PlayerState],
    list[V2ActionWindow],
    list[V2AbilityInstance],
    list[V2AbilityActivation],
    list[V2EffectIntent],
    list[V2KnowledgeFact],
    V2MatchState | None,
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
    player_states = list(
        db.scalars(
            select(V2PlayerState)
            .where(V2PlayerState.game_id == game_id)
            .order_by(V2PlayerState.seat.asc())
        )
    )
    action_windows = list(
        db.scalars(
            select(V2ActionWindow)
            .where(V2ActionWindow.game_id == game_id)
            .order_by(V2ActionWindow.window_seq.asc())
        )
    )
    ability_instances = list(
        db.scalars(
            select(V2AbilityInstance)
            .where(V2AbilityInstance.game_id == game_id)
            .order_by(V2AbilityInstance.ability_id.asc())
        )
    )
    ability_activations = list(
        db.scalars(
            select(V2AbilityActivation)
            .where(V2AbilityActivation.game_id == game_id)
            .order_by(V2AbilityActivation.opened_at.asc())
        )
    )
    effect_intents = list(
        db.scalars(
            select(V2EffectIntent)
            .where(V2EffectIntent.game_id == game_id)
            .order_by(V2EffectIntent.created_at.asc())
        )
    )
    knowledge_facts = list(
        db.scalars(
            select(V2KnowledgeFact)
            .where(V2KnowledgeFact.game_id == game_id)
            .order_by(V2KnowledgeFact.created_at.asc())
        )
    )
    match_state = db.get(V2MatchState, game_id)
    return (
        game,
        runs,
        events,
        presentations,
        voices,
        player_states,
        action_windows,
        ability_instances,
        ability_activations,
        effect_intents,
        knowledge_facts,
        match_state,
    )


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


def _initial_ability_state(ability_id: str) -> dict[str, Any]:
    if ability_id == "witch.heal":
        return {"available": True, "remaining": 1}
    if ability_id == "witch.poison":
        return {"available": True, "remaining": 1}
    if ability_id == "guard.protect":
        return {"previous_target_player_id": None}
    return {}
