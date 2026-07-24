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
    V2KnowledgeFact,
    V2MatchState,
    V2PlayerState,
    V2RoleAssignment,
)
from app.v2.repository import V2PhaseTransition, V2RepositoryError


@dataclass(frozen=True)
class V2MatchPlayer:
    player_id: str
    seat: int
    display_name: str
    role_key: str
    team: str
    alive: bool
    tts_speaker: str | None
    model_id: str | None
    persona: dict[str, Any]
    state: dict[str, Any]


@dataclass(frozen=True)
class V2MatchSnapshot:
    game_id: str
    run_id: str
    phase_id: str
    phase_state: str
    round_no: int
    sheriff_player_id: str | None
    sheriff_badge_state: str
    pre_sheriff_explosion_count: int
    rule: dict[str, Any]
    max_rounds: int
    players: tuple[V2MatchPlayer, ...]
    public_history: tuple[dict[str, Any], ...]

    def player(self, player_id: str) -> V2MatchPlayer:
        for player in self.players:
            if player.player_id == player_id:
                return player
        raise V2RepositoryError(f"unknown V2 player {player_id}")


@dataclass(frozen=True)
class V2ExileResult:
    player_id: str
    outcome: str
    winner_after_exile: str | None


class V2MatchRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def snapshot(self, game_id: str) -> V2MatchSnapshot:
        self._ensure_state(game_id)
        with self._session_factory() as db:
            game = db.get(V2GameRecord, game_id)
            match = db.get(V2MatchState, game_id)
            if game is None or match is None:
                raise V2RepositoryError(f"unknown game {game_id}")
            rule = game.rule_snapshot.get("rule_set")
            if not isinstance(rule, dict):
                raise V2RepositoryError("V2 match has no frozen rule")
            compiled_rule = dict(rule)
            compiled_rule["day_actions"] = list(game.ability_snapshot.get("day_actions") or [])
            for key, value in dict(game.ability_snapshot.get("day_policies") or {}).items():
                compiled_rule.setdefault(key, value)
            return V2MatchSnapshot(
                game_id=game.game_id,
                run_id=game.current_run_id,
                phase_id=game.phase_id,
                phase_state=game.phase_state,
                round_no=match.round_no,
                sheriff_player_id=match.sheriff_player_id,
                sheriff_badge_state=match.sheriff_badge_state,
                pre_sheriff_explosion_count=match.pre_sheriff_explosion_count,
                rule=compiled_rule,
                max_rounds=int(game.rule_snapshot.get("max_rounds") or 8),
                players=_players(db, game),
                public_history=_public_history(db, game_id),
            )

    def private_knowledge(self, *, game_id: str, player_id: str) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            rows = list(
                db.scalars(
                    select(V2KnowledgeFact)
                    .where(
                        V2KnowledgeFact.game_id == game_id,
                        V2KnowledgeFact.owner_scope == "player",
                        V2KnowledgeFact.owner_id == player_id,
                    )
                    .order_by(V2KnowledgeFact.created_at)
                )
            )
            return [
                {"fact_type": row.fact_type, "payload": dict(row.payload or {})}
                for row in rows
                if row.fact_type != "action_context_projection"
            ]

    def append_event(
        self,
        *,
        game_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            _append_event(db, game=game, event_type=event_type, payload=payload)

    def record_phase_state(self, *, game_id: str, previous_phase_state: str) -> V2PhaseTransition:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            transition = V2PhaseTransition(
                game_id=game.game_id,
                run_id=game.current_run_id,
                phase_seq=game.phase_seq,
                previous_phase_id=game.phase_id,
                phase_id=game.phase_id,
                phase_state=game.phase_state,
            )
            _append_event(
                db,
                game=game,
                event_type="game_phase_changed",
                payload={
                    "phase_seq": game.phase_seq,
                    "previous_phase_id": game.phase_id,
                    "previous_phase_state": previous_phase_state,
                    "phase_id": game.phase_id,
                    "phase_state": game.phase_state,
                },
            )
            return transition

    def set_sheriff(
        self,
        *,
        game_id: str,
        player_id: str | None,
        reason: str,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            match = _match(db, game)
            if player_id is not None:
                target = db.get(V2PlayerState, (game_id, player_id))
                if target is None or not target.alive:
                    raise V2RepositoryError("sheriff target must be alive")
                previous_sheriff_id = match.sheriff_player_id
                match.sheriff_player_id = player_id
                match.sheriff_badge_state = "held"
                event_type = (
                    "sheriff_badge_transferred"
                    if previous_sheriff_id is not None and previous_sheriff_id != player_id
                    else "sheriff_elected"
                )
            else:
                previous_sheriff_id = match.sheriff_player_id
                match.sheriff_player_id = None
                match.sheriff_badge_state = "destroyed"
                event_type = "sheriff_badge_destroyed"
            _append_event(
                db,
                game=game,
                event_type=event_type,
                payload={
                    "player_id": player_id,
                    "from_player_id": previous_sheriff_id,
                    "reason": reason,
                },
            )

    def record_pre_sheriff_explosion(self, *, game_id: str, player_id: str) -> str:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            match = _match(db, game)
            _kill(db, game=game, player_id=player_id, cause="werewolf_self_explosion")
            match.pre_sheriff_explosion_count += 1
            policy = str(
                game.ability_snapshot.get("day_policies", {}).get(
                    "sheriff_badge_bomb_policy", "none"
                )
            )
            if policy == "double" and match.pre_sheriff_explosion_count >= 2:
                match.sheriff_badge_state = "destroyed"
                outcome = "badge_destroyed"
            else:
                match.sheriff_badge_state = "pending"
                outcome = "election_interrupted"
            _append_event(
                db,
                game=game,
                event_type="werewolf_self_exploded",
                payload={
                    "player_id": player_id,
                    "stage": "pre_sheriff_election",
                    "count": match.pre_sheriff_explosion_count,
                    "outcome": outcome,
                },
            )
            return outcome

    def record_day_explosion(self, *, game_id: str, player_id: str, stage: str) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            _kill(db, game=game, player_id=player_id, cause="werewolf_self_explosion")
            _append_event(
                db,
                game=game,
                event_type="werewolf_self_exploded",
                payload={"player_id": player_id, "stage": stage, "outcome": "day_ended"},
            )

    def resolve_exile(self, *, game_id: str, player_id: str) -> V2ExileResult:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            assignment = db.scalar(
                select(V2RoleAssignment).where(
                    V2RoleAssignment.game_id == game_id,
                    V2RoleAssignment.player_id == player_id,
                )
            )
            state = db.get(V2PlayerState, (game_id, player_id))
            if assignment is None or state is None or not state.alive:
                raise V2RepositoryError("exile target must be alive")
            player_state = dict(state.state or {})
            if assignment.role_key == "idiot" and not player_state.get("idiot_revealed"):
                player_state["idiot_revealed"] = True
                player_state["can_vote"] = False
                state.state = player_state
                outcome = "idiot_revealed"
                _append_event(
                    db,
                    game=game,
                    event_type="idiot_revealed",
                    payload={"player_id": player_id, "survived": True},
                )
            else:
                _kill(db, game=game, player_id=player_id, cause="exile")
                outcome = "eliminated"
                _append_event(
                    db,
                    game=game,
                    event_type="player_exiled",
                    payload={"player_id": player_id},
                )
            return V2ExileResult(
                player_id=player_id,
                outcome=outcome,
                winner_after_exile=_winner(db, game),
            )

    def apply_hunter_shot(
        self,
        *,
        game_id: str,
        hunter_id: str,
        target_player_id: str | None,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            hunter = db.get(V2PlayerState, (game_id, hunter_id))
            if hunter is None or hunter.alive or hunter.death_cause == "witch_poison":
                raise V2RepositoryError("hunter response is not eligible")
            hunter_state = dict(hunter.state or {})
            if hunter_state.get("hunter_response_resolved"):
                raise V2RepositoryError("hunter response already resolved")
            hunter_state["hunter_response_resolved"] = True
            hunter.state = hunter_state
            if target_player_id is not None:
                _kill(db, game=game, player_id=target_player_id, cause="hunter_shot")
            _append_event(
                db,
                game=game,
                event_type="hunter_response_resolved",
                payload={
                    "hunter_player_id": hunter_id,
                    "target_player_id": target_player_id,
                },
            )

    def pending_hunters(self, game_id: str) -> tuple[str, ...]:
        with self._session_factory() as db:
            rows = list(
                db.execute(
                    select(V2RoleAssignment.player_id, V2PlayerState.death_cause, V2PlayerState.state)
                    .join(
                        V2PlayerState,
                        (V2PlayerState.game_id == V2RoleAssignment.game_id)
                        & (V2PlayerState.player_id == V2RoleAssignment.player_id),
                    )
                    .where(
                        V2RoleAssignment.game_id == game_id,
                        V2RoleAssignment.role_key == "hunter",
                        V2PlayerState.alive.is_(False),
                        V2PlayerState.death_cause != "witch_poison",
                    )
                    .order_by(V2RoleAssignment.seat)
                )
            )
            return tuple(
                player_id
                for player_id, _cause, state in rows
                if not (state or {}).get("hunter_response_resolved")
            )

    def finish_day(self, *, game_id: str, reason: str) -> V2PhaseTransition:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            match = _match(db, game)
            winner = _winner(db, game)
            previous_phase_id = game.phase_id
            game.phase_seq += 1
            if winner is not None:
                match.winner = winner
                match.completion_reason = "deterministic_win_condition"
                game.phase_state = "game_completed"
                game.status = "awaiting_observation"
                run = _run(db, game.current_run_id)
                run.status = "awaiting_observation"
                run.completed_at = _now()
                _append_event(
                    db,
                    game=game,
                    event_type="game_completed",
                    payload={
                        "winner": winner,
                        "reason": "deterministic_win_condition",
                        "round_no": match.round_no,
                    },
                )
            elif match.round_no >= int(game.rule_snapshot.get("max_rounds") or 8):
                match.completion_reason = "max_rounds_exceeded"
                game.phase_state = "failed"
                game.status = "failed"
                run = _run(db, game.current_run_id)
                run.status = "failed"
                run.completed_at = _now()
                _append_event(
                    db,
                    game=game,
                    event_type="match_runtime_failed",
                    payload={"reason": "max_rounds_exceeded", "round_no": match.round_no},
                )
            else:
                match.round_no += 1
                game.phase_id = f"night_{match.round_no}"
                game.phase_state = "nightfall_ready"
                game.status = "ready"
                _run(db, game.current_run_id).status = "ready"
            transition = V2PhaseTransition(
                game_id=game.game_id,
                run_id=game.current_run_id,
                phase_seq=game.phase_seq,
                previous_phase_id=previous_phase_id,
                phase_id=game.phase_id,
                phase_state=game.phase_state,
            )
            _append_event(
                db,
                game=game,
                event_type="game_phase_changed",
                payload={
                    "phase_seq": transition.phase_seq,
                    "previous_phase_id": transition.previous_phase_id,
                    "phase_id": transition.phase_id,
                    "phase_state": transition.phase_state,
                    "reason": reason,
                },
            )
            return transition

    def current_winner(self, game_id: str) -> str | None:
        with self._session_factory() as db:
            game = db.get(V2GameRecord, game_id)
            if game is None:
                raise V2RepositoryError(f"unknown game {game_id}")
            return _winner(db, game)

    def fail_runtime(self, *, game_id: str, failure_code: str) -> str:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            game.status = "failed"
            game.phase_state = "failed"
            run = _run(db, game.current_run_id)
            run.status = "failed"
            run.completed_at = _now()
            match = db.get(V2MatchState, game_id)
            if match is not None:
                match.completion_reason = failure_code
            _append_event(
                db,
                game=game,
                event_type="day_runtime_failed",
                payload={"failure_code": failure_code},
            )
            return run.run_id

    def _ensure_state(self, game_id: str) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            if db.get(V2MatchState, game_id) is not None:
                return
            rule = game.rule_snapshot.get("rule_set")
            if not isinstance(rule, dict):
                raise V2RepositoryError("V2 match has no frozen rule")
            db.add(
                V2MatchState(
                    game_id=game_id,
                    round_no=_round_no(game.phase_id),
                    sheriff_badge_state=(
                        "pending" if bool(rule.get("sheriff_enabled")) else "disabled"
                    ),
                )
            )


def _players(db: Session, game: V2GameRecord) -> tuple[V2MatchPlayer, ...]:
    assignments = list(
        db.scalars(
            select(V2RoleAssignment)
            .where(V2RoleAssignment.game_id == game.game_id)
            .order_by(V2RoleAssignment.seat)
        )
    )
    profiles = {
        str(item["profile_id"]): item
        for item in game.players_snapshot
        if isinstance(item, dict) and item.get("profile_id")
    }
    players: list[V2MatchPlayer] = []
    for assignment in assignments:
        state = db.get(V2PlayerState, (game.game_id, assignment.player_id))
        if state is None:
            raise V2RepositoryError("player state is incomplete")
        profile = profiles.get(assignment.player_id, {})
        players.append(
            V2MatchPlayer(
                player_id=assignment.player_id,
                seat=assignment.seat,
                display_name=str(profile.get("name") or f"{assignment.seat}号玩家"),
                role_key=assignment.role_key,
                team="werewolves" if assignment.role_key == "werewolf" else "villagers",
                alive=state.alive,
                tts_speaker=(str(profile["tts_speaker"]) if profile.get("tts_speaker") else None),
                model_id=(str(profile["model"]) if profile.get("model") else None),
                persona={
                    key: profile[key]
                    for key in (
                        "name",
                        "personality",
                        "catchphrases",
                        "strategy_profile",
                        "base_delivery_mood",
                        "base_delivery_intensity",
                        "base_delivery_pace",
                        "base_delivery_instruction",
                    )
                    if profile.get(key) is not None
                },
                state=dict(state.state or {}),
            )
        )
    return tuple(players)


_PUBLIC_HISTORY_TYPES = {
    "day_speech_committed",
    "day_vote_committed",
    "day_vote_resolved",
    "player_exiled",
    "idiot_revealed",
    "werewolf_self_exploded",
    "sheriff_elected",
    "sheriff_badge_destroyed",
    "sheriff_badge_transferred",
    "hunter_response_resolved",
    "dawn_public_result",
}


def _public_history(db: Session, game_id: str) -> tuple[dict[str, Any], ...]:
    rows = list(
        db.scalars(
            select(V2GameRecordEvent)
            .where(
                V2GameRecordEvent.game_id == game_id,
                V2GameRecordEvent.event_type.in_(_PUBLIC_HISTORY_TYPES),
            )
            .order_by(V2GameRecordEvent.record_seq.desc())
            .limit(80)
        )
    )
    rows.reverse()
    return tuple(
        {"event_type": row.event_type, "payload": dict(row.payload or {})} for row in rows
    )


def _winner(db: Session, game: V2GameRecord) -> str | None:
    rows = list(
        db.execute(
            select(V2RoleAssignment.role_key, V2PlayerState.alive)
            .join(
                V2PlayerState,
                (V2PlayerState.game_id == V2RoleAssignment.game_id)
                & (V2PlayerState.player_id == V2RoleAssignment.player_id),
            )
            .where(V2RoleAssignment.game_id == game.game_id)
        )
    )
    alive_roles = [role_key for role_key, alive in rows if alive]
    wolves = sum(role == "werewolf" for role in alive_roles)
    others = len(alive_roles) - wolves
    if wolves == 0:
        return "villagers"
    win_condition = str(game.ability_snapshot.get("win_condition") or "wolves_gte_others")
    if win_condition == "slaughter_side":
        villagers = sum(role == "villager" for role in alive_roles)
        gods = sum(role not in {"werewolf", "villager"} for role in alive_roles)
        return "werewolves" if villagers == 0 or gods == 0 else None
    return "werewolves" if wolves >= others else None


def _kill(db: Session, *, game: V2GameRecord, player_id: str, cause: str) -> None:
    state = db.get(V2PlayerState, (game.game_id, player_id))
    if state is None or not state.alive:
        raise V2RepositoryError("death target must be alive")
    state.alive = False
    state.death_cause = cause
    state.death_window_seq = None


def _match(db: Session, game: V2GameRecord) -> V2MatchState:
    match = db.get(V2MatchState, game.game_id)
    if match is None:
        raise V2RepositoryError("V2 match state is missing")
    return match


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
    event_type: str,
    payload: dict[str, Any],
) -> None:
    next_seq = game.last_record_seq + 1
    db.add(
        V2GameRecordEvent(
            game_id=game.game_id,
            event_id=next_seq,
            record_seq=next_seq,
            run_id=game.current_run_id,
            event_type=event_type,
            payload_schema_version=1,
            payload=payload,
        )
    )
    game.last_record_seq = next_seq


def _round_no(phase_id: str) -> int:
    if phase_id == "first_night":
        return 1
    if "_" in phase_id:
        value = phase_id.rsplit("_", 1)[-1]
        if value.isdigit() and int(value) >= 1:
            return int(value)
    return 1


def _now() -> datetime:
    return datetime.now(tz=UTC)
