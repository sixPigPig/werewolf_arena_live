from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.v2.ability_runtime import ability_snapshot_hash, resolve_first_night
from app.v2.models import (
    V2AbilityActivation,
    V2AbilityInstance,
    V2ActionWindow,
    V2EffectIntent,
    V2GameRecord,
    V2GameRecordEvent,
    V2GameRun,
    V2KnowledgeFact,
    V2LivePresentation,
    V2MatchState,
    V2PlayerState,
    V2RoleAssignment,
)
from app.v2.repository import V2GameCanceled, V2PhaseTransition, V2RepositoryError
from app.v2.win_conditions import (
    all_hunter_settlement_branches_terminal,
    hunter_settlement_can_change_winner,
    winner_from_alive_roles,
)


@dataclass(frozen=True)
class V2NightPlayer:
    player_id: str
    seat: int
    display_name: str
    role_key: str
    team: str
    alive: bool
    tts_speaker: str | None
    tts_dialect: str | None
    model_provider: str
    model_id: str | None
    model_parameters: dict[str, Any]
    persona: dict[str, Any]


@dataclass(frozen=True)
class V2NightRuntimeState:
    game_id: str
    run_id: str
    window_id: str
    window_seq: int
    phase_id: str
    round_no: int
    snapshot: dict[str, Any]
    rule: dict[str, Any]
    max_rounds: int
    sheriff_player_id: str | None
    sheriff_badge_state: str
    players: tuple[V2NightPlayer, ...]

    def player(self, player_id: str) -> V2NightPlayer:
        for player in self.players:
            if player.player_id == player_id:
                return player
        raise V2RepositoryError(f"unknown V2 player {player_id}")

    def instance(self, ability_id: str) -> dict[str, Any] | None:
        for item in self.snapshot["instances"]:
            if item["ability_id"] == ability_id:
                return item
        return None


@dataclass(frozen=True)
class V2ActivationRef:
    activation_id: str
    ability_instance_id: str
    ability_id: str
    actor_player_id: str | None
    occurrence: int


@dataclass(frozen=True)
class V2NightResolutionRecord:
    deaths: tuple[dict[str, str], ...]
    peaceful: bool
    attack_prevented_by: str | None
    transition: V2PhaseTransition


class V2NightRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def execution_enabled(self, game_id: str) -> bool:
        with self._session_factory() as db:
            game = db.get(V2GameRecord, game_id)
            if game is None:
                raise V2RepositoryError(f"unknown game {game_id}")
            snapshot = game.ability_snapshot or {}
            if not snapshot:
                return False
            ability_snapshot_hash(snapshot)
            return snapshot.get("execution_enabled") is True

    def start_night(self, game_id: str) -> V2NightRuntimeState:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            snapshot = game.ability_snapshot or {}
            digest = ability_snapshot_hash(snapshot)
            if snapshot.get("execution_enabled") is not True:
                raise V2RepositoryError("ability runtime is not executable")
            round_no = _night_round_no(game.phase_id)
            if game.status != "ready" or game.phase_state != "nightfall_announced":
                raise V2RepositoryError("night is not ready to start")
            next_window_seq = (
                int(
                    db.scalar(
                        select(func.coalesce(func.max(V2ActionWindow.window_seq), 0)).where(
                            V2ActionWindow.game_id == game_id
                        )
                    )
                    or 0
                )
                + 1
            )
            existing = db.scalar(
                select(V2ActionWindow).where(
                    V2ActionWindow.game_id == game_id,
                    V2ActionWindow.window_seq == next_window_seq,
                )
            )
            if existing is not None:
                raise V2RepositoryError("night action window already exists")
            plan = [
                {
                    "ability_instance_id": item["ability_instance_id"],
                    "ability_id": item["ability_id"],
                    "order": item["order"],
                    "trigger": item["trigger"],
                }
                for item in snapshot["instances"]
                if item["window_type"] == "night"
            ]
            window = V2ActionWindow(
                window_id=f"v2_window_{uuid4().hex[:16]}",
                game_id=game.game_id,
                run_id=game.current_run_id,
                window_seq=next_window_seq,
                window_type="night",
                state="open",
                ability_snapshot_hash=digest,
                plan=plan,
                result={},
            )
            db.add(window)
            game.status = "ready"
            game.phase_state = "night_running"
            run = _run(db, game.current_run_id)
            run.status = "ready"
            _append_event(
                db,
                game=game,
                event_type="action_window_opened",
                payload={
                    "window_id": window.window_id,
                    "window_seq": next_window_seq,
                    "window_type": "night",
                    "round_no": round_no,
                    "ability_snapshot_hash": digest,
                },
            )
            _append_event(
                db,
                game=game,
                event_type="activation_plan_compiled",
                payload={"window_id": window.window_id, "plan": plan},
            )
            players = _players(db, game)
            rule = _compiled_rule(game, snapshot)
            match = db.get(V2MatchState, game_id)
            if match is None:
                raise V2RepositoryError("night match state is missing")
            return V2NightRuntimeState(
                game_id=game.game_id,
                run_id=game.current_run_id,
                window_id=window.window_id,
                window_seq=window.window_seq,
                phase_id=game.phase_id,
                round_no=round_no,
                snapshot=snapshot,
                rule=rule,
                max_rounds=int(game.rule_snapshot.get("max_rounds") or 8),
                sheriff_player_id=match.sheriff_player_id,
                sheriff_badge_state=match.sheriff_badge_state,
                players=players,
            )

    def start_first_night(self, game_id: str) -> V2NightRuntimeState:
        return self.start_night(game_id)

    def open_activation(
        self,
        *,
        state: V2NightRuntimeState,
        ability_id: str,
        actor_player_id: str | None,
        occurrence: int,
    ) -> V2ActivationRef:
        instance_data = state.instance(ability_id)
        if instance_data is None:
            raise V2RepositoryError(f"ability {ability_id} is not configured")
        activation_id = f"v2_activation_{uuid4().hex[:16]}"
        with self._session_factory.begin() as db:
            game = _locked_game(db, state.game_id)
            if game.phase_state not in {"night_running", "dawn_reactions_ready"}:
                raise V2RepositoryError("ability activation opened outside action window")
            instance = db.get(V2AbilityInstance, instance_data["ability_instance_id"])
            if instance is None or instance.game_id != state.game_id:
                raise V2RepositoryError("ability instance is missing")
            activation = V2AbilityActivation(
                activation_id=activation_id,
                game_id=state.game_id,
                run_id=state.run_id,
                window_id=state.window_id,
                ability_instance_id=instance.ability_instance_id,
                occurrence=occurrence,
                actor_player_id=actor_player_id,
                status="open",
                knowledge_fact_ids=[],
                decision={},
                result={},
            )
            db.add(activation)
            _append_event(
                db,
                game=game,
                event_type="ability_activation_opened",
                payload={
                    "activation_id": activation_id,
                    "window_id": state.window_id,
                    "ability_instance_id": instance.ability_instance_id,
                    "ability_id": ability_id,
                    "actor_player_id": actor_player_id,
                    "occurrence": occurrence,
                },
            )
        return V2ActivationRef(
            activation_id=activation_id,
            ability_instance_id=instance_data["ability_instance_id"],
            ability_id=ability_id,
            actor_player_id=actor_player_id,
            occurrence=occurrence,
        )

    def complete_activation(
        self,
        *,
        state: V2NightRuntimeState,
        activation: V2ActivationRef,
        decision: dict[str, Any],
        result: dict[str, Any],
        effect_type: str | None = None,
        target_player_id: str | None = None,
        knowledge: tuple[tuple[str, str, dict[str, Any]], ...] = (),
        ability_state_patch: dict[str, Any] | None = None,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, state.game_id)
            row = db.get(V2AbilityActivation, activation.activation_id)
            if row is None or row.status != "open":
                raise V2RepositoryError("ability activation is not open")
            knowledge_ids: list[str] = []
            durable_knowledge = list(knowledge)
            if activation.actor_player_id is not None:
                durable_knowledge.append(
                    (
                        "player",
                        activation.actor_player_id,
                        {
                            "fact_type": "private_ability_action_committed",
                            "payload": {
                                "ability_id": activation.ability_id,
                                "night_no": state.round_no,
                                "decision": {
                                    key: value
                                    for key, value in decision.items()
                                    if key != "speech"
                                },
                                "result": dict(result),
                                "resolution_scope": (
                                    "法官已接受本次私有动作；这里只记录动作决定与资源使用，"
                                    "不额外公开其他玩家身份。"
                                ),
                            },
                        },
                    )
                )
            for owner_scope, owner_id, fact in durable_knowledge:
                fact_id = f"v2_fact_{uuid4().hex[:16]}"
                knowledge_ids.append(fact_id)
                db.add(
                    V2KnowledgeFact(
                        knowledge_fact_id=fact_id,
                        game_id=state.game_id,
                        source_activation_id=activation.activation_id,
                        owner_scope=owner_scope,
                        owner_id=owner_id,
                        fact_type=str(fact["fact_type"]),
                        payload=dict(fact["payload"]),
                    )
                )
            effect_id: str | None = None
            if effect_type is not None and target_player_id is not None:
                effect_id = f"v2_effect_{uuid4().hex[:16]}"
                db.add(
                    V2EffectIntent(
                        effect_intent_id=effect_id,
                        game_id=state.game_id,
                        window_id=state.window_id,
                        activation_id=activation.activation_id,
                        effect_type=effect_type,
                        actor_id=activation.actor_player_id,
                        target_player_id=target_player_id,
                        payload={},
                        state="pending",
                    )
                )
            row.status = "completed"
            row.decision_id = f"v2_decision_{uuid4().hex[:16]}"
            row.knowledge_fact_ids = [*(row.knowledge_fact_ids or []), *knowledge_ids]
            row.decision = decision
            row.result = {**result, "effect_intent_id": effect_id}
            row.closed_at = _now()
            if ability_state_patch:
                instance = db.get(V2AbilityInstance, activation.ability_instance_id)
                if instance is None:
                    raise V2RepositoryError("ability instance disappeared")
                instance.state = {**(instance.state or {}), **ability_state_patch}
            _append_event(
                db,
                game=game,
                event_type="ability_activation_completed",
                payload={
                    "activation_id": activation.activation_id,
                    "ability_id": activation.ability_id,
                    "decision_id": row.decision_id,
                    "decision": decision,
                    "result": row.result,
                    "knowledge_fact_ids": row.knowledge_fact_ids,
                },
            )

    def register_activation_knowledge(
        self,
        *,
        state: V2NightRuntimeState,
        activation: V2ActivationRef,
        owner_player_id: str,
        allowed_knowledge: dict[str, Any],
    ) -> tuple[tuple[str, ...], str]:
        canonical = json.dumps(
            allowed_knowledge,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        digest = hashlib.sha256(canonical).hexdigest()
        fact_id = f"v2_fact_{uuid4().hex[:16]}"
        with self._session_factory.begin() as db:
            game = _locked_game(db, state.game_id)
            row = db.get(V2AbilityActivation, activation.activation_id)
            if row is None or row.status != "open" or row.knowledge_fact_ids:
                raise V2RepositoryError("activation knowledge cannot be registered")
            db.add(
                V2KnowledgeFact(
                    knowledge_fact_id=fact_id,
                    game_id=state.game_id,
                    source_activation_id=activation.activation_id,
                    owner_scope="player",
                    owner_id=owner_player_id,
                    fact_type="action_context_projection",
                    payload={
                        "schema_version": 1,
                        "projection_policy_id": "v2_ability_allowed_knowledge.v1",
                        "normalized_sha256": digest,
                        "facts": allowed_knowledge,
                    },
                )
            )
            row.knowledge_fact_ids = [fact_id]
            _append_event(
                db,
                game=game,
                event_type="activation_knowledge_projected",
                payload={
                    "activation_id": activation.activation_id,
                    "knowledge_fact_ids": [fact_id],
                    "projection_policy_id": "v2_ability_allowed_knowledge.v1",
                    "normalized_sha256": digest,
                },
            )
        return (fact_id,), digest

    def skip_activation(
        self,
        *,
        state: V2NightRuntimeState,
        ability_id: str,
        reason: str,
        occurrence: int = 1,
    ) -> V2ActivationRef:
        activation = self.open_activation(
            state=state,
            ability_id=ability_id,
            actor_player_id=None,
            occurrence=occurrence,
        )
        with self._session_factory.begin() as db:
            game = _locked_game(db, state.game_id)
            row = db.get(V2AbilityActivation, activation.activation_id)
            assert row is not None
            row.status = "skipped"
            row.skip_reason = reason
            decision_status = (
                "skipped"
                if reason in {"owner_not_alive", "no_eligible_actor_or_target"}
                else "unavailable"
            )
            row.result = {"decision_status": decision_status}
            row.closed_at = _now()
            _append_event(
                db,
                game=game,
                event_type="ability_activation_skipped",
                payload={
                    "activation_id": activation.activation_id,
                    "ability_id": ability_id,
                    "reason": reason,
                    "decision_status": decision_status,
                },
            )
        return activation

    def resolve_night(
        self,
        *,
        state: V2NightRuntimeState,
        attack_target: str | None,
        protected_target: str | None,
        healed_target: str | None,
        poisoned_target: str | None,
    ) -> V2NightResolutionRecord:
        resolution = resolve_first_night(
            attack_target=attack_target,
            protected_target=protected_target,
            healed_target=healed_target,
            poisoned_target=poisoned_target,
        )
        with self._session_factory.begin() as db:
            game = _locked_game(db, state.game_id)
            window = db.get(V2ActionWindow, state.window_id)
            if window is None or window.state != "open" or game.phase_state != "night_running":
                raise V2RepositoryError("night window is not resolvable")
            effect_rows = list(
                db.scalars(
                    select(V2EffectIntent).where(
                        V2EffectIntent.game_id == state.game_id,
                        V2EffectIntent.window_id == state.window_id,
                        V2EffectIntent.state == "pending",
                    )
                )
            )
            death_by_player = {item["player_id"]: item["cause"] for item in resolution.deaths}
            for effect in effect_rows:
                effect.state = "resolved"
                effect.resolved_at = _now()
                effect.payload = {
                    **(effect.payload or {}),
                    "outcome": _effect_outcome(
                        effect.effect_type,
                        effect.target_player_id,
                        death_by_player,
                        resolution.attack_prevented_by,
                    ),
                }
            for item in resolution.deaths:
                player_state = db.get(V2PlayerState, (state.game_id, item["player_id"]))
                if player_state is None or not player_state.alive:
                    raise V2RepositoryError("night death target is not alive")
                player_state.state = {
                    **(player_state.state or {}),
                    "pending_dawn_death": {
                        "cause": item["cause"],
                        "window_seq": state.window_seq,
                    },
                }
            result = {
                "deaths": list(resolution.deaths),
                "peaceful": resolution.peaceful,
                "attack_prevented_by": resolution.attack_prevented_by,
            }
            window.state = "closed"
            window.result = result
            window.closed_at = _now()
            previous_phase_id = game.phase_id
            game.phase_seq += 1
            game.phase_id = f"day_{state.round_no}"
            match = db.get(V2MatchState, state.game_id)
            if match is None:
                raise V2RepositoryError("night match state is missing")
            should_elect_before_dawn = (
                state.round_no == 1
                and bool(game.ability_snapshot.get("sheriff_enabled"))
                and match.sheriff_badge_state == "pending"
                and not _pending_terminal_is_inevitable(db, game)
            )
            game.phase_state = (
                "sheriff_election_ready"
                if should_elect_before_dawn
                else "dawn_announcement_ready"
            )
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
                event_type="action_window_closed",
                payload={"window_id": window.window_id, "result": result},
            )
            _append_event(
                db,
                game=game,
                event_type="night_resolution_committed",
                payload={
                    "round_no": state.round_no,
                    "pending_death_count": len(resolution.deaths),
                },
            )
            _append_event(
                db,
                game=game,
                event_type="game_phase_changed",
                payload=_transition_payload(transition),
            )
        return V2NightResolutionRecord(
            deaths=resolution.deaths,
            peaceful=resolution.peaceful,
            attack_prevented_by=resolution.attack_prevented_by,
            transition=transition,
        )

    def ready_dawn_announcement(self, *, game_id: str) -> V2PhaseTransition:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            if game.phase_state != "sheriff_election_open":
                raise V2RepositoryError("pre-dawn sheriff election is not complete")
            game.phase_state = "dawn_announcement_ready"
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
                payload=_transition_payload(transition),
            )
            return transition

    def reveal_pending_dawn_deaths(
        self,
        *,
        game_id: str,
        expected_player_ids: tuple[str, ...],
    ) -> tuple[dict[str, str], ...]:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            if game.phase_state != "dawn_announcement_ready":
                raise V2RepositoryError("dawn deaths are not ready to reveal")
            revealed: list[dict[str, str]] = []
            rows = list(
                db.scalars(
                    select(V2PlayerState)
                    .where(V2PlayerState.game_id == game_id)
                    .order_by(V2PlayerState.seat)
                )
            )
            for player_state in rows:
                pending = (player_state.state or {}).get("pending_dawn_death")
                if not isinstance(pending, dict):
                    continue
                cause = pending.get("cause")
                window_seq = pending.get("window_seq")
                if not isinstance(cause, str) or not isinstance(window_seq, int):
                    raise V2RepositoryError("pending dawn death is invalid")
                player_state.alive = False
                player_state.death_cause = cause
                player_state.death_window_seq = window_seq
                next_state = dict(player_state.state or {})
                next_state.pop("pending_dawn_death", None)
                player_state.state = next_state
                revealed.append(
                    {
                        "player_id": player_state.player_id,
                        "cause": cause,
                    }
                )
            revealed_ids = tuple(item["player_id"] for item in revealed)
            if set(revealed_ids) != set(expected_player_ids):
                raise V2RepositoryError("revealed dawn deaths differ from night resolution")
            round_no = _day_round_no(game.phase_id)
            _append_event(
                db,
                game=game,
                event_type="dawn_public_result",
                payload={
                    "round_no": round_no,
                    "dead_player_ids": list(revealed_ids),
                },
            )
            return tuple(revealed)

    def hunter_reactions(self, game_id: str) -> tuple[str, ...]:
        with self._session_factory() as db:
            rows = db.execute(
                select(
                    V2RoleAssignment.player_id,
                    V2PlayerState.death_cause,
                    V2PlayerState.state,
                )
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
            return tuple(
                player_id
                for player_id, _cause, state in rows
                if not (state or {}).get("hunter_response_resolved")
            )

    def hunter_settlement_can_change_winner(self, game_id: str) -> bool:
        with self._session_factory() as db:
            game = db.get(V2GameRecord, game_id)
            if game is None:
                raise V2RepositoryError(f"unknown game {game_id}")
            rows = list(
                db.execute(
                    select(
                        V2RoleAssignment.player_id,
                        V2RoleAssignment.role_key,
                        V2PlayerState.alive,
                        V2PlayerState.death_cause,
                        V2PlayerState.state,
                    )
                    .join(
                        V2PlayerState,
                        (V2PlayerState.game_id == V2RoleAssignment.game_id)
                        & (V2PlayerState.player_id == V2RoleAssignment.player_id),
                    )
                    .where(V2RoleAssignment.game_id == game_id)
                    .order_by(V2RoleAssignment.seat)
                )
            )
            return hunter_settlement_can_change_winner(
                living_player_ids=frozenset(
                    player_id for player_id, _role, alive, _cause, _state in rows if alive
                ),
                pending_hunter_ids=tuple(
                    player_id
                    for player_id, role, alive, cause, state in rows
                    if role == "hunter"
                    and not alive
                    and cause != "witch_poison"
                    and not (state or {}).get("hunter_response_resolved")
                ),
                role_by_player_id={
                    player_id: role for player_id, role, _alive, _cause, _state in rows
                },
                win_condition=str(
                    game.ability_snapshot.get("win_condition") or "wolves_gte_others"
                ),
            )

    def open_dawn_reaction_window(
        self,
        *,
        state: V2NightRuntimeState,
    ) -> V2NightRuntimeState:
        hunter = state.instance("hunter.death_shot")
        if hunter is None:
            raise V2RepositoryError("hunter response is not configured")
        with self._session_factory.begin() as db:
            game = _locked_game(db, state.game_id)
            if game.phase_id != f"day_{state.round_no}":
                raise V2RepositoryError("dawn response is not ready")
            if game.phase_state == "dawn_reactions_ready":
                window = db.scalar(
                    select(V2ActionWindow).where(
                        V2ActionWindow.game_id == state.game_id,
                        V2ActionWindow.window_type == "dawn_reaction",
                        V2ActionWindow.state == "open",
                    )
                )
                if window is None:
                    raise V2RepositoryError("dawn reaction window is missing")
                window_id = window.window_id
                next_window_seq = window.window_seq
            elif game.phase_state == "dawn_announced":
                next_window_seq = (
                    int(
                        db.scalar(
                            select(func.coalesce(func.max(V2ActionWindow.window_seq), 0)).where(
                                V2ActionWindow.game_id == state.game_id
                            )
                        )
                        or 0
                    )
                    + 1
                )
                window = V2ActionWindow(
                    window_id=f"v2_window_{uuid4().hex[:16]}",
                    game_id=state.game_id,
                    run_id=state.run_id,
                    window_seq=next_window_seq,
                    window_type="dawn_reaction",
                    state="open",
                    ability_snapshot_hash=ability_snapshot_hash(state.snapshot),
                    plan=[
                        {
                            "ability_instance_id": hunter["ability_instance_id"],
                            "ability_id": hunter["ability_id"],
                            "order": hunter["order"],
                            "trigger": hunter["trigger"],
                        }
                    ],
                    result={},
                )
                db.add(window)
                window_id = window.window_id
                game.phase_state = "dawn_reactions_ready"
                _append_event(
                    db,
                    game=game,
                    event_type="action_window_opened",
                    payload={
                        "window_id": window_id,
                        "window_seq": next_window_seq,
                        "window_type": "dawn_reaction",
                    },
                )
            else:
                raise V2RepositoryError("dawn response is not ready")
        return V2NightRuntimeState(
            game_id=state.game_id,
            run_id=state.run_id,
            window_id=window_id,
            window_seq=next_window_seq,
            phase_id=f"day_{state.round_no}",
            round_no=state.round_no,
            snapshot=state.snapshot,
            rule=state.rule,
            max_rounds=state.max_rounds,
            sheriff_player_id=state.sheriff_player_id,
            sheriff_badge_state=state.sheriff_badge_state,
            players=self.current_players(state.game_id),
        )

    def apply_hunter_shot(
        self,
        *,
        state: V2NightRuntimeState,
        hunter_player_id: str,
        target_player_id: str,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, state.game_id)
            target = db.get(V2PlayerState, (state.game_id, target_player_id))
            if target is None or not target.alive:
                raise V2RepositoryError("hunter target is not alive")
            target.alive = False
            target.death_cause = "hunter_shot"
            target.death_window_seq = state.window_seq
            hunter = db.get(V2PlayerState, (state.game_id, hunter_player_id))
            if hunter is None:
                raise V2RepositoryError("hunter state is missing")
            hunter.state = {**(hunter.state or {}), "hunter_response_resolved": True}
            _append_event(
                db,
                game=game,
                event_type="hunter_response_resolved",
                payload={
                    "round_no": state.round_no,
                    "period": "dawn",
                    "effect_type": "shoot",
                    "hunter_player_id": hunter_player_id,
                    "target_player_id": target_player_id,
                },
            )

    def mark_hunter_response_resolved(
        self,
        *,
        state: V2NightRuntimeState,
        hunter_player_id: str,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, state.game_id)
            hunter = db.get(V2PlayerState, (state.game_id, hunter_player_id))
            if hunter is None:
                raise V2RepositoryError("hunter state is missing")
            hunter.state = {**(hunter.state or {}), "hunter_response_resolved": True}
            _append_event(
                db,
                game=game,
                event_type="hunter_response_resolved",
                payload={
                    "round_no": state.round_no,
                    "period": "dawn",
                    "effect_type": "shoot_skipped",
                    "hunter_player_id": hunter_player_id,
                },
            )

    def finish_night(self, *, game_id: str) -> V2PhaseTransition:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            round_no = _day_round_no(game.phase_id)
            if game.phase_state not in {
                "dawn_announced",
                "dawn_reactions_ready",
            }:
                raise V2RepositoryError("night is not ready to finish")
            open_window = db.scalar(
                select(V2ActionWindow).where(
                    V2ActionWindow.game_id == game_id,
                    V2ActionWindow.state == "open",
                )
            )
            if open_window is not None:
                open_window.state = "closed"
                open_window.result = {"completed": True}
                open_window.closed_at = _now()
                _append_event(
                    db,
                    game=game,
                    event_type="action_window_closed",
                    payload={
                        "window_id": open_window.window_id,
                        "result": open_window.result,
                    },
                )
            winner = _winner(db, game)
            match = db.get(V2MatchState, game_id)
            if match is None:
                raise V2RepositoryError("V2 match state is missing")
            next_state = (
                "game_completed"
                if winner is not None
                else (
                    "sheriff_election_ready"
                    if bool(game.ability_snapshot.get("sheriff_enabled"))
                    and match.sheriff_badge_state == "pending"
                    else "public_day_ready"
                )
            )
            game.phase_state = next_state
            next_live_state = "awaiting_observation" if winner is not None else "ready"
            game.status = next_live_state
            run = _run(db, game.current_run_id)
            run.status = next_live_state
            if winner is not None:
                match.winner = winner
                match.completion_reason = "deterministic_win_condition"
                run.completed_at = _now()
                _append_event(
                    db,
                    game=game,
                    event_type="game_completed",
                    payload={
                        "winner": winner,
                        "reason": "deterministic_win_condition",
                        "round_no": round_no,
                    },
                )
            transition = V2PhaseTransition(
                game_id=game.game_id,
                run_id=game.current_run_id,
                phase_seq=game.phase_seq,
                previous_phase_id=game.phase_id,
                phase_id=game.phase_id,
                phase_state=next_state,
            )
            _append_event(
                db,
                game=game,
                event_type="game_phase_changed",
                payload=_transition_payload(transition),
            )
            return transition

    def finish_first_night(self, *, game_id: str) -> V2PhaseTransition:
        return self.finish_night(game_id=game_id)

    def current_winner(self, game_id: str) -> str | None:
        with self._session_factory() as db:
            game = db.get(V2GameRecord, game_id)
            if game is None:
                raise V2RepositoryError(f"unknown game {game_id}")
            return _winner(db, game)

    def match_state(self, game_id: str) -> dict[str, Any]:
        with self._session_factory() as db:
            match = db.get(V2MatchState, game_id)
            if match is None:
                raise V2RepositoryError("V2 match state is missing")
            return {
                "round_no": match.round_no,
                "sheriff_player_id": match.sheriff_player_id,
                "sheriff_badge_state": match.sheriff_badge_state,
                "winner": match.winner,
            }

    def ability_state(self, *, game_id: str, ability_id: str) -> dict[str, Any]:
        with self._session_factory() as db:
            row = db.scalar(
                select(V2AbilityInstance).where(
                    V2AbilityInstance.game_id == game_id,
                    V2AbilityInstance.ability_id == ability_id,
                )
            )
            return dict(row.state or {}) if row is not None else {}

    def player_knowledge(self, *, game_id: str, player_id: str) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            rows = list(
                db.scalars(
                    select(V2KnowledgeFact)
                    .where(
                        V2KnowledgeFact.game_id == game_id,
                        V2KnowledgeFact.owner_scope == "player",
                        V2KnowledgeFact.owner_id == player_id,
                        V2KnowledgeFact.fact_type != "action_context_projection",
                    )
                    .order_by(V2KnowledgeFact.created_at)
                )
            )
            return [
                {"fact_type": row.fact_type, "payload": dict(row.payload or {})} for row in rows
            ]

    def record_player_knowledge(
        self,
        *,
        game_id: str,
        player_id: str,
        fact_type: str,
        payload: dict[str, Any],
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            fact_id = f"v2_fact_{uuid4().hex[:16]}"
            db.add(
                V2KnowledgeFact(
                    knowledge_fact_id=fact_id,
                    game_id=game_id,
                    source_activation_id=None,
                    owner_scope="player",
                    owner_id=player_id,
                    fact_type=fact_type,
                    payload=dict(payload),
                )
            )
            _append_event(
                db,
                game=game,
                event_type="private_knowledge_recorded",
                payload={
                    "knowledge_fact_id": fact_id,
                    "owner_scope": "player",
                    "owner_id": player_id,
                    "fact_type": fact_type,
                },
            )

    def public_history(self, game_id: str) -> list[dict[str, Any]]:
        public_types = {
            "day_speech_committed",
            "day_vote_committed",
            "day_vote_resolved",
            "player_exiled",
            "idiot_revealed",
            "werewolf_self_exploded",
            "sheriff_elected",
            "sheriff_badge_destroyed",
            "hunter_response_resolved",
            "dawn_public_result",
        }
        with self._session_factory() as db:
            rows = list(
                db.scalars(
                    select(V2GameRecordEvent)
                    .where(
                        V2GameRecordEvent.game_id == game_id,
                        V2GameRecordEvent.event_type.in_(public_types),
                    )
                    .order_by(V2GameRecordEvent.record_seq.desc())
                )
            )
            rows.reverse()
            history = [
                {
                    "source_event_id": row.event_id,
                    "record_seq": row.record_seq,
                    "event_type": row.event_type,
                    "payload": dict(row.payload or {}),
                }
                for row in rows
            ]
            presentations = list(
                db.scalars(
                    select(V2LivePresentation)
                    .where(
                        V2LivePresentation.game_id == game_id,
                        V2LivePresentation.actor_kind == "player",
                        V2LivePresentation.audience == "all",
                        V2LivePresentation.state == "closed",
                    )
                    .order_by(V2LivePresentation.source_event_id)
                )
            )
            action_types = _action_types_by_id(db, game_id)
            history.extend(
                {
                    "source_event_id": row.source_event_id,
                    "record_seq": row.source_event_id,
                    "event_type": "public_player_speech_presented",
                    "payload": {
                        "round_no": _phase_round_no(row.phase_id),
                        "stage": action_types.get(row.action_id, row.phase_id),
                        "action_id": row.action_id,
                        "phase_id": row.phase_id,
                        "player_id": row.actor_id,
                        "speech": row.subtitle_text,
                    },
                }
                for row in presentations
            )
            history.sort(key=lambda item: int(item["record_seq"]))
            return history

    def current_players(self, game_id: str) -> tuple[V2NightPlayer, ...]:
        with self._session_factory() as db:
            game = db.get(V2GameRecord, game_id)
            if game is None:
                raise V2RepositoryError(f"unknown game {game_id}")
            return _players(db, game)

    def latest_presentation_seq(self, game_id: str) -> int:
        with self._session_factory() as db:
            game = db.get(V2GameRecord, game_id)
            if game is None:
                raise V2RepositoryError(f"unknown game {game_id}")
            return game.last_presentation_seq

    def current_phase_state(self, game_id: str) -> str:
        with self._session_factory() as db:
            game = db.get(V2GameRecord, game_id)
            if game is None:
                raise V2RepositoryError(f"unknown game {game_id}")
            return game.phase_state

    def fail_runtime(self, *, game_id: str, failure_code: str) -> str:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id)
            run = _run(db, game.current_run_id)
            if run.stop_requested_at is not None:
                raise V2GameCanceled("V2 game was canceled by an administrator")
            game.status = "failed"
            game.phase_state = "failed"
            run.status = "failed"
            run.completed_at = _now()
            _append_event(
                db,
                game=game,
                event_type="ability_runtime_failed",
                payload={"failure_code": failure_code},
            )
            return run.run_id


def _players(db: Session, game: V2GameRecord) -> tuple[V2NightPlayer, ...]:
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
    result: list[V2NightPlayer] = []
    for assignment in assignments:
        player_state = db.get(V2PlayerState, (game.game_id, assignment.player_id))
        profile = profiles.get(assignment.player_id, {})
        if player_state is None:
            raise V2RepositoryError("player state is incomplete")
        result.append(
            V2NightPlayer(
                player_id=assignment.player_id,
                seat=assignment.seat,
                display_name=str(profile.get("name") or f"{assignment.seat}号玩家"),
                role_key=assignment.role_key,
                team=("werewolves" if assignment.role_key == "werewolf" else "villagers"),
                alive=player_state.alive,
                tts_speaker=(str(profile["tts_speaker"]) if profile.get("tts_speaker") else None),
                tts_dialect=(
                    str(profile["tts_dialect"]) if profile.get("tts_dialect") else None
                ),
                model_provider=str(profile["model_provider"]),
                model_id=str(profile["model"]),
                model_parameters=dict(profile.get("model_parameters") or {}),
                persona={
                    key: profile[key]
                    for key in (
                        "name",
                        "personality",
                        "strategy_profile",
                        "base_delivery_mood",
                        "base_delivery_intensity",
                        "base_delivery_pace",
                        "base_delivery_instruction",
                    )
                    if profile.get(key) is not None
                },
            )
        )
    return tuple(result)


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
    return winner_from_alive_roles(
        alive_roles,
        win_condition=str(game.ability_snapshot.get("win_condition") or "wolves_gte_others"),
    )


def _pending_terminal_is_inevitable(db: Session, game: V2GameRecord) -> bool:
    rows = list(
        db.execute(
            select(
                V2RoleAssignment.player_id,
                V2RoleAssignment.role_key,
                V2PlayerState.alive,
                V2PlayerState.state,
            )
            .join(
                V2PlayerState,
                (V2PlayerState.game_id == V2RoleAssignment.game_id)
                & (V2PlayerState.player_id == V2RoleAssignment.player_id),
            )
            .where(V2RoleAssignment.game_id == game.game_id)
        )
    )
    roles = {player_id: role_key for player_id, role_key, _alive, _state in rows}
    alive = {player_id for player_id, _role, is_alive, _state in rows if is_alive}
    pending_hunters: list[str] = []
    for player_id, role_key, is_alive, raw_state in rows:
        pending = (raw_state or {}).get("pending_dawn_death")
        if not is_alive or not isinstance(pending, dict):
            continue
        alive.discard(player_id)
        if role_key == "hunter" and pending.get("cause") != "witch_poison":
            pending_hunters.append(player_id)
    win_condition = str(game.ability_snapshot.get("win_condition") or "wolves_gte_others")

    return all_hunter_settlement_branches_terminal(
        living_player_ids=frozenset(alive),
        pending_hunter_ids=tuple(pending_hunters),
        role_by_player_id=roles,
        win_condition=win_condition,
    )


def _effect_outcome(
    effect_type: str,
    target_player_id: str | None,
    death_by_player: dict[str, str],
    prevented_by: str | None,
) -> str:
    if effect_type == "attack":
        if target_player_id in death_by_player:
            return "killed"
        return f"prevented_by_{prevented_by}" if prevented_by else "no_death"
    if effect_type in {"protect", "heal"}:
        return "prevented_attack" if prevented_by == effect_type else "unused"
    if effect_type == "poison":
        return "killed" if target_player_id in death_by_player else "unused"
    return "resolved"


def _compiled_rule(
    game: V2GameRecord,
    ability_snapshot: dict[str, Any],
) -> dict[str, Any]:
    rule = game.rule_snapshot.get("rule_set")
    if not isinstance(rule, dict):
        raise V2RepositoryError("V2 night runtime has no frozen rule")
    compiled = dict(rule)
    compiled["day_actions"] = list(ability_snapshot.get("day_actions") or [])
    compiled["ability_policies"] = dict(ability_snapshot.get("policies") or {})
    for key, value in dict(ability_snapshot.get("day_policies") or {}).items():
        compiled.setdefault(key, value)
    return compiled


def _locked_game(db: Session, game_id: str) -> V2GameRecord:
    game = db.scalar(select(V2GameRecord).where(V2GameRecord.game_id == game_id).with_for_update())
    if game is None:
        raise V2RepositoryError(f"unknown game {game_id}")
    run = _run(db, game.current_run_id)
    if run.stop_requested_at is not None:
        raise V2GameCanceled("V2 game was canceled by an administrator")
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


def _transition_payload(transition: V2PhaseTransition) -> dict[str, Any]:
    return {
        "phase_seq": transition.phase_seq,
        "previous_phase_id": transition.previous_phase_id,
        "phase_id": transition.phase_id,
        "phase_state": transition.phase_state,
    }


def _now() -> datetime:
    return datetime.now(tz=UTC)


def _night_round_no(phase_id: str) -> int:
    if phase_id == "first_night":
        return 1
    if phase_id.startswith("night_") and phase_id[6:].isdigit():
        round_no = int(phase_id[6:])
        if round_no >= 2:
            return round_no
    raise V2RepositoryError("invalid V2 night phase id")


def _action_types_by_id(db: Session, game_id: str) -> dict[str, str]:
    rows = list(
        db.scalars(
            select(V2GameRecordEvent).where(
                V2GameRecordEvent.game_id == game_id,
                V2GameRecordEvent.event_type == "action_opened",
            )
        )
    )
    action_types: dict[str, str] = {}
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        context = payload.get("context")
        if not isinstance(context, dict):
            continue
        action_id = payload.get("action_id")
        action_type = context.get("action_type")
        if isinstance(action_id, str) and isinstance(action_type, str):
            action_types[action_id] = action_type
    return action_types


def _phase_round_no(phase_id: str) -> int:
    if phase_id == "first_night":
        return 1
    if "_" in phase_id:
        value = phase_id.rsplit("_", 1)[-1]
        if value.isdigit() and int(value) >= 1:
            return int(value)
    return 1


def _day_round_no(phase_id: str) -> int:
    if phase_id.startswith("day_") and phase_id[4:].isdigit():
        round_no = int(phase_id[4:])
        if round_no >= 1:
            return round_no
    raise V2RepositoryError("invalid V2 day phase id")
