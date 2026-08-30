from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import secrets
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.match.ability_runtime import compile_ability_runtime_snapshot
from app.match.day_speech_pipeline_contract import (
    day_speech_pipeline_contract_summary,
    freeze_day_speech_pipeline_contract,
)
from app.match.event_contract import canonical_event_payload
from app.match.models import (
    AbilityActivation,
    AbilityInstance,
    ActionWindow,
    EffectIntent,
    GameRecord,
    GameRecordEvent,
    GameRun,
    GodViewAccessGrant,
    LivePresentation,
    MatchState,
    KnowledgeFact,
    PlayerState,
    RoleAssignment,
    RoleAssignmentBatch,
    VoiceAsset,
)
from app.match.god_view_access import (
    issue_god_view_access_token,
    verify_god_view_access_token,
)
from app.match.model_context_contract import freeze_model_context_contract
from app.match.model_generation_policy_contract import (
    freeze_model_generation_policy_contract,
)
from app.match.pre_exile_pipeline_contract import (
    freeze_pre_exile_pipeline_contract,
    pre_exile_pipeline_contract_summary,
)
from app.match.role_assignment import assign_private_roles


class RecordNotFound(LookupError):
    pass


class VoiceAssetUnavailable(RuntimeError):
    pass


class RoleAssignmentStateError(RuntimeError):
    pass


class GodViewAccessDenied(PermissionError):
    pass


class GodViewUnavailable(RuntimeError):
    pass


def create_waiting_game(
    db: Session,
    *,
    title: str,
    delivery_snapshot: dict[str, Any],
    rule_snapshot: dict[str, Any] | None = None,
    players_snapshot: list[dict[str, Any]] | None = None,
    judge_voice_snapshot: dict[str, Any] | None = None,
) -> tuple[GameRecord, GameRun, str]:
    created_from_lobby = rule_snapshot is not None
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
    frozen_rule_snapshot = freeze_pre_exile_pipeline_contract(
        freeze_day_speech_pipeline_contract(
            freeze_model_generation_policy_contract(freeze_model_context_contract(rule_snapshot))
        )
    )
    if created_from_lobby:
        assert players_snapshot is not None
        assignment_id = f"v2_roles_{uuid4().hex[:16]}"
        private_seed = secrets.token_hex(32)
        assignment_result = assign_private_roles(
            players_snapshot=players_snapshot,
            rule_snapshot=frozen_rule_snapshot,
            seed_hex=private_seed,
        )
        ability_snapshot = compile_ability_runtime_snapshot(
            game_id=game_id,
            rule_snapshot=frozen_rule_snapshot,
            assignments=assignment_result.assignments,
        )
    initial_record_seq = 3 if assignment_result is not None else 1
    game = GameRecord(
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
        rule_snapshot=frozen_rule_snapshot,
        players_snapshot=players_snapshot or [],
        judge_voice_snapshot=judge_voice_snapshot or {},
        delivery_snapshot=delivery_snapshot,
        ability_snapshot=ability_snapshot,
        ability_snapshot_hash=(ability_snapshot or {}).get("snapshot_hash"),
    )
    run = GameRun(
        run_id=run_id,
        game_id=game_id,
        attempt_no=1,
        status="waiting_to_start",
        started_at=None,
    )
    created = GameRecordEvent(
        game_id=game_id,
        event_id=1,
        record_seq=1,
        run_id=run_id,
        event_type="game_created",
        payload_schema_version=1,
        payload=canonical_event_payload(
            {
                "title": game.title,
                "start_mode": "first_ready_viewer",
                "creation_source": ("existing_mobile_lobby" if created_from_lobby else "direct_v2"),
                "rule_set_id": frozen_rule_snapshot.get("rule_set", {}).get("id"),
                "player_count": len(players_snapshot or []),
                "judge_voice": judge_voice_snapshot or {},
                "delivery_snapshot": delivery_snapshot,
                "model_context_contract": frozen_rule_snapshot["model_context_contract"],
                "model_generation_policy_contract": {
                    key: frozen_rule_snapshot["model_generation_policy_contract"][key]
                    for key in (
                        "schema_version",
                        "classification_version",
                        "enforcement",
                    )
                },
                "day_speech_pipeline_contract": day_speech_pipeline_contract_summary(
                    frozen_rule_snapshot
                ),
                "pre_exile_pipeline_contract": pre_exile_pipeline_contract_summary(
                    frozen_rule_snapshot
                ),
            },
            audience="all",
        ),
    )
    db.add(game)
    db.flush()
    if assignment_result is not None:
        sheriff_enabled = bool(frozen_rule_snapshot.get("rule_set", {}).get("sheriff_enabled"))
        db.add(
            MatchState(
                game_id=game_id,
                round_no=1,
                sheriff_badge_state="pending" if sheriff_enabled else "disabled",
            )
        )
    db.add(
        GodViewAccessGrant(
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
        assignment_batch = RoleAssignmentBatch(
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
                RoleAssignment(
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
            GameRecordEvent(
                game_id=game_id,
                event_id=2,
                record_seq=2,
                run_id=run_id,
                event_type="roles_assigned",
                payload_schema_version=1,
                payload=canonical_event_payload(
                    {
                        "assignment_id": assignment_id,
                        "assigned_count": len(assignment_result.assignments),
                        "visibility": "private_sealed",
                    },
                    audience="god_view",
                ),
            )
        )
        db.add_all(
            [
                PlayerState(
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
                AbilityInstance(
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
            GameRecordEvent(
                game_id=game_id,
                event_id=3,
                record_seq=3,
                run_id=run_id,
                event_type="ability_runtime_compiled",
                payload_schema_version=1,
                payload=canonical_event_payload(
                    {
                        "ability_snapshot_hash": ability_snapshot["snapshot_hash"],
                        "registry_version": ability_snapshot["registry_version"],
                        "instance_count": len(ability_snapshot["instances"]),
                        "execution_enabled": ability_snapshot["execution_enabled"],
                    },
                    audience="god_view",
                ),
            )
        )
    db.commit()
    db.refresh(game)
    db.refresh(run)
    return game, run, god_view_token


def get_game(db: Session, game_id: str) -> GameRecord:
    record = db.get(GameRecord, game_id)
    if record is None:
        raise RecordNotFound(game_id)
    return record


def get_match_state(db: Session, game_id: str) -> MatchState | None:
    get_game(db, game_id)
    return db.get(MatchState, game_id)


def current_presentation(
    db: Session,
    game_id: str,
    *,
    audience: str = "player_public",
) -> LivePresentation | None:
    get_game(db, game_id)
    if audience == "spectator_directed":
        allowed = ("all", "public", "god_view")
    elif audience == "spectator_god_view":
        allowed = ("all", "god_view")
    else:
        allowed = ("all", "public")
    return db.scalar(
        select(LivePresentation)
        .where(
            LivePresentation.game_id == game_id,
            LivePresentation.state == "active",
            LivePresentation.audience.in_(allowed),
        )
        .order_by(LivePresentation.presentation_seq.desc())
        .limit(1)
    )


def current_action_context(db: Session, game_id: str) -> dict[str, Any] | None:
    game = get_game(db, game_id)
    if game.status not in {"generating", "broadcasting", "finalizing"}:
        return None
    events = db.scalars(
        select(GameRecordEvent)
        .where(
            GameRecordEvent.game_id == game_id,
            GameRecordEvent.run_id == game.current_run_id,
            GameRecordEvent.event_type == "action_opened",
        )
        .order_by(GameRecordEvent.record_seq.desc())
    )
    for event in events:
        if not isinstance(event.payload, dict):
            continue
        context = event.payload.get("context")
        if not isinstance(context, dict):
            continue
        pipeline = context.get("pipeline")
        if type(pipeline) is dict and pipeline.get("stage") == "generation":
            continue
        return context
    return None


def role_assignment_count(db: Session, game_id: str) -> int | None:
    expected_count = db.scalar(
        select(RoleAssignmentBatch.player_count).where(RoleAssignmentBatch.game_id == game_id)
    )
    if expected_count is None:
        return None
    actual_count = int(
        db.scalar(
            select(func.count())
            .select_from(RoleAssignment)
            .where(RoleAssignment.game_id == game_id)
        )
        or 0
    )
    if actual_count != expected_count:
        raise RoleAssignmentStateError("private role assignment batch is incomplete")
    return expected_count


def authorize_god_view(db: Session, *, game_id: str, token: str | None) -> None:
    grant = db.get(GodViewAccessGrant, game_id)
    if (
        grant is None
        or token is None
        or not verify_god_view_access_token(
            token=token,
            expected_sha256=grant.token_sha256,
        )
    ):
        raise GodViewAccessDenied(game_id)


def god_view_role_assignments(db: Session, game_id: str) -> list[RoleAssignment]:
    expected_count = role_assignment_count(db, game_id)
    if expected_count is None:
        raise GodViewUnavailable(game_id)
    assignments = list(
        db.scalars(
            select(RoleAssignment)
            .where(RoleAssignment.game_id == game_id)
            .order_by(RoleAssignment.seat.asc())
        )
    )
    if len(assignments) != expected_count:
        raise RoleAssignmentStateError("private role assignment batch is incomplete")
    return assignments


def player_state_map(db: Session, game_id: str) -> dict[str, PlayerState]:
    get_game(db, game_id)
    states = list(db.scalars(select(PlayerState).where(PlayerState.game_id == game_id)))
    result = {item.player_id: item for item in states}
    if len(result) != len(states):
        raise RoleAssignmentStateError("duplicate V2 player state")
    return result


def get_voice_asset(db: Session, *, game_id: str, voice_asset_id: str) -> VoiceAsset:
    asset = db.get(VoiceAsset, voice_asset_id)
    if asset is None or asset.game_id != game_id:
        raise RecordNotFound(f"{game_id}:{voice_asset_id}")
    return asset


def list_games(
    db: Session,
    *,
    page: int,
    page_size: int,
) -> tuple[list[GameRecord], int]:
    total = int(db.scalar(select(func.count()).select_from(GameRecord)) or 0)
    records = list(
        db.scalars(
            select(GameRecord)
            .order_by(GameRecord.created_at.desc(), GameRecord.game_id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return records, total


def game_summary(
    db: Session,
    game_id: str,
) -> tuple[
    GameRecord,
    list[GameRun],
    list[LivePresentation],
    list[VoiceAsset],
    list[RoleAssignment],
    list[PlayerState],
    list[ActionWindow],
    list[AbilityInstance],
    list[AbilityActivation],
    list[EffectIntent],
    list[KnowledgeFact],
    MatchState | None,
]:
    game = get_game(db, game_id)
    runs = list(
        db.scalars(
            select(GameRun)
            .where(GameRun.game_id == game_id)
            .order_by(GameRun.attempt_no.asc())
        )
    )
    presentations = list(
        db.scalars(
            select(LivePresentation)
            .where(LivePresentation.game_id == game_id)
            .order_by(LivePresentation.presentation_seq.asc())
        )
    )
    voices = list(
        db.scalars(
            select(VoiceAsset)
            .where(VoiceAsset.game_id == game_id)
            .order_by(VoiceAsset.created_at.asc(), VoiceAsset.voice_asset_id.asc())
        )
    )
    role_assignments = list(
        db.scalars(
            select(RoleAssignment)
            .where(RoleAssignment.game_id == game_id)
            .order_by(RoleAssignment.seat.asc())
        )
    )
    player_states = list(
        db.scalars(
            select(PlayerState)
            .where(PlayerState.game_id == game_id)
            .order_by(PlayerState.seat.asc())
        )
    )
    action_windows = list(
        db.scalars(
            select(ActionWindow)
            .where(ActionWindow.game_id == game_id)
            .order_by(ActionWindow.window_seq.asc())
        )
    )
    ability_instances = list(
        db.scalars(
            select(AbilityInstance)
            .where(AbilityInstance.game_id == game_id)
            .order_by(AbilityInstance.ability_id.asc())
        )
    )
    ability_activations = list(
        db.scalars(
            select(AbilityActivation)
            .where(AbilityActivation.game_id == game_id)
            .order_by(AbilityActivation.opened_at.asc())
        )
    )
    effect_intents = list(
        db.scalars(
            select(EffectIntent)
            .where(EffectIntent.game_id == game_id)
            .order_by(EffectIntent.created_at.asc())
        )
    )
    knowledge_facts = list(
        db.scalars(
            select(KnowledgeFact)
            .where(KnowledgeFact.game_id == game_id)
            .order_by(KnowledgeFact.created_at.asc())
        )
    )
    match_state = db.get(MatchState, game_id)
    return (
        game,
        runs,
        presentations,
        voices,
        role_assignments,
        player_states,
        action_windows,
        ability_instances,
        ability_activations,
        effect_intents,
        knowledge_facts,
        match_state,
    )


def list_game_events(
    db: Session,
    game_id: str,
    *,
    after_record_seq: int,
    page_size: int,
) -> tuple[list[GameRecordEvent], bool]:
    get_game(db, game_id)
    rows = list(
        db.scalars(
            select(GameRecordEvent)
            .where(
                GameRecordEvent.game_id == game_id,
                GameRecordEvent.record_seq > after_record_seq,
            )
            .order_by(GameRecordEvent.record_seq.asc())
            .limit(page_size + 1)
        )
    )
    return rows[:page_size], len(rows) > page_size


def all_game_events(db: Session, game_id: str) -> list[GameRecordEvent]:
    get_game(db, game_id)
    return list(
        db.scalars(
            select(GameRecordEvent)
            .where(GameRecordEvent.game_id == game_id)
            .order_by(GameRecordEvent.record_seq.asc())
        )
    )


def list_game_presentations(
    db: Session,
    game_id: str,
) -> list[LivePresentation]:
    get_game(db, game_id)
    return list(
        db.scalars(
            select(LivePresentation)
            .where(LivePresentation.game_id == game_id)
            .order_by(LivePresentation.presentation_seq.asc())
        )
    )


def get_game_event(
    db: Session,
    *,
    game_id: str,
    event_id: int,
) -> GameRecordEvent:
    get_game(db, game_id)
    event = db.get(GameRecordEvent, (game_id, event_id))
    if event is None:
        raise RecordNotFound(f"{game_id}:{event_id}")
    return event


def voice_asset_path(*, root: Path, asset: VoiceAsset) -> Path:
    if asset.state != "ready":
        raise VoiceAssetUnavailable(asset.voice_asset_id)
    safe_root = root.resolve()
    path = (safe_root / asset.storage_key).resolve()
    if safe_root not in path.parents or not path.is_file():
        raise VoiceAssetUnavailable(asset.voice_asset_id)
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
