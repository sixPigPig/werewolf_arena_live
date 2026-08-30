from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.match.ability_runtime import ability_snapshot_hash, resolve_first_night
from app.match.execution import RunFenceRejected, require_run_fence
from app.match.event_contract import canonical_event_payload
from app.match.knowledge_timeline import player_private_knowledge
from app.match.model_generation_policy_contract import (
    MODEL_GENERATION_POLICY_SUPPORTED_SCHEMA_VERSIONS,
)
from app.match.model_parameters import (
    FrozenModelParametersError,
    frozen_player_model_configuration,
)
from app.match.models import (
    AbilityActivation,
    AbilityInstance,
    ActionWindow,
    EffectIntent,
    GameRecord,
    GameRecordEvent,
    GameRun,
    KnowledgeFact,
    LivePresentation,
    MatchState,
    PlayerState,
    RoleAssignment,
)
from app.match.repository import (
    ExecutionOwnershipLost,
    GameCanceled,
    PhaseTransition,
    RepositoryError,
    _open_failure_episode_ids_for_locked_run,
)
from app.match.win_conditions import (
    all_hunter_settlement_branches_terminal,
    hunter_settlement_can_change_winner,
    winner_from_alive_roles,
)


@dataclass(frozen=True)
class NightPlayer:
    player_id: str
    seat: int
    display_name: str
    role_key: str
    team: str
    alive: bool
    tts_speaker: str | None
    tts_dialect: str | None
    model_provider: str
    model_id: str
    model_supports_thinking: bool
    model_parameters: dict[str, Any]
    persona: dict[str, Any]


@dataclass(frozen=True)
class NightRuntimeState:
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
    players: tuple[NightPlayer, ...]

    def player(self, player_id: str) -> NightPlayer:
        for player in self.players:
            if player.player_id == player_id:
                return player
        raise RepositoryError(f"unknown V2 player {player_id}")

    def instance(self, ability_id: str) -> dict[str, Any] | None:
        for item in self.snapshot["instances"]:
            if item["ability_id"] == ability_id:
                return item
        return None


@dataclass(frozen=True)
class ActivationRef:
    activation_id: str
    ability_instance_id: str
    ability_id: str
    actor_player_id: str | None
    occurrence: int
    audience: str


@dataclass(frozen=True)
class NightResolutionRecord:
    deaths: tuple[dict[str, str], ...]
    peaceful: bool
    attack_prevented_by: str | None
    transition: PhaseTransition


class NightRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        enforce_execution_fence: bool = False,
    ) -> None:
        self._session_factory = session_factory
        self._enforce_execution_fence = enforce_execution_fence

    def latest_record_seq(self, game_id: str) -> int:
        with self._session_factory() as db:
            game = db.get(GameRecord, game_id)
            if game is None:
                raise RepositoryError(f"unknown game {game_id}")
            return game.last_record_seq

    def append_event(
        self,
        *,
        game_id: str,
        event_type: str,
        audience: str,
        payload: dict[str, Any],
    ) -> int:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            record_seq = game.last_record_seq + 1
            _append_event(
                db,
                game=game,
                event_type=event_type,
                audience=audience,
                payload=payload,
            )
            return record_seq

    def execution_enabled(self, game_id: str) -> bool:
        with self._session_factory() as db:
            game = db.get(GameRecord, game_id)
            if game is None:
                raise RepositoryError(f"unknown game {game_id}")
            snapshot = game.ability_snapshot or {}
            if not snapshot:
                return False
            ability_snapshot_hash(snapshot)
            return snapshot.get("execution_enabled") is True

    def start_night(self, game_id: str, *, audience: str) -> NightRuntimeState:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            snapshot = game.ability_snapshot or {}
            digest = ability_snapshot_hash(snapshot)
            if snapshot.get("execution_enabled") is not True:
                raise RepositoryError("ability runtime is not executable")
            round_no = _night_round_no(game.phase_id)
            if game.status != "ready" or game.phase_state != "nightfall_announced":
                raise RepositoryError("night is not ready to start")
            next_window_seq = (
                int(
                    db.scalar(
                        select(func.coalesce(func.max(ActionWindow.window_seq), 0)).where(
                            ActionWindow.game_id == game_id
                        )
                    )
                    or 0
                )
                + 1
            )
            existing = db.scalar(
                select(ActionWindow).where(
                    ActionWindow.game_id == game_id,
                    ActionWindow.window_seq == next_window_seq,
                )
            )
            if existing is not None:
                raise RepositoryError("night action window already exists")
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
            window = ActionWindow(
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
                audience=audience,
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
                audience=audience,
                payload={"window_id": window.window_id, "plan": plan},
            )
            players = _players(db, game)
            rule = _compiled_rule(game, snapshot)
            match = db.get(MatchState, game_id)
            if match is None:
                raise RepositoryError("night match state is missing")
            return NightRuntimeState(
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

    def start_first_night(self, game_id: str, *, audience: str) -> NightRuntimeState:
        return self.start_night(game_id, audience=audience)

    def open_activation(
        self,
        *,
        state: NightRuntimeState,
        ability_id: str,
        actor_player_id: str | None,
        occurrence: int,
        audience: str,
    ) -> ActivationRef:
        instance_data = state.instance(ability_id)
        if instance_data is None:
            raise RepositoryError(f"ability {ability_id} is not configured")
        activation_id = f"v2_activation_{uuid4().hex[:16]}"
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                state.game_id,
                require_fence=self._enforce_execution_fence,
            )
            _row, activation = self._open_activation_locked(
                db=db,
                game=game,
                state=state,
                instance_data=instance_data,
                activation_id=activation_id,
                actor_player_id=actor_player_id,
                occurrence=occurrence,
                audience=audience,
            )
        return activation

    def _open_activation_locked(
        self,
        *,
        db: Session,
        game: GameRecord,
        state: NightRuntimeState,
        instance_data: dict[str, Any],
        activation_id: str,
        actor_player_id: str | None,
        occurrence: int,
        audience: str,
    ) -> tuple[AbilityActivation, ActivationRef]:
        if game.phase_state not in {"night_running", "dawn_reactions_ready"}:
            raise RepositoryError("ability activation opened outside action window")
        instance = db.get(AbilityInstance, instance_data["ability_instance_id"])
        if instance is None or instance.game_id != state.game_id:
            raise RepositoryError("ability instance is missing")
        row = AbilityActivation(
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
        db.add(row)
        _append_event(
            db,
            game=game,
            event_type="ability_activation_opened",
            audience=audience,
            payload={
                "activation_id": activation_id,
                "window_id": state.window_id,
                "ability_instance_id": instance.ability_instance_id,
                "ability_id": instance_data["ability_id"],
                "actor_player_id": actor_player_id,
                "occurrence": occurrence,
            },
        )
        return row, ActivationRef(
            activation_id=activation_id,
            ability_instance_id=instance.ability_instance_id,
            ability_id=str(instance_data["ability_id"]),
            actor_player_id=actor_player_id,
            occurrence=occurrence,
            audience=audience,
        )

    def complete_activation(
        self,
        *,
        state: NightRuntimeState,
        activation: ActivationRef,
        decision: dict[str, Any],
        result: dict[str, Any],
        effect_type: str | None = None,
        target_player_id: str | None = None,
        knowledge: tuple[tuple[str, str, dict[str, Any]], ...] = (),
        ability_state_patch: dict[str, Any] | None = None,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                state.game_id,
                require_fence=self._enforce_execution_fence,
            )
            row = db.get(AbilityActivation, activation.activation_id)
            if row is None or row.status != "open":
                raise RepositoryError("ability activation is not open")
            knowledge_ids: list[str] = []
            durable_knowledge = list(knowledge)
            if activation.actor_player_id is not None:
                decision_note = decision.get("decision_note")
                committed_decision = {
                    key: value
                    for key, value in decision.items()
                    if key not in {"speech", "decision_note"}
                }
                durable_knowledge.append(
                    (
                        "player",
                        activation.actor_player_id,
                        {
                            "fact_type": "private_ability_action_committed",
                            "payload": {
                                "ability_id": activation.ability_id,
                                "night_no": state.round_no,
                                "decision": committed_decision,
                                **(
                                    {
                                        "declared_reason": {
                                            "text": decision_note,
                                            "epistemic_status": "actor_declared_reason",
                                        }
                                    }
                                    if isinstance(decision_note, str) and decision_note.strip()
                                    else {}
                                ),
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
                    KnowledgeFact(
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
                    EffectIntent(
                        effect_intent_id=effect_id,
                        game_id=state.game_id,
                        window_id=state.window_id,
                        activation_id=activation.activation_id,
                        effect_type=effect_type,
                        actor_id=activation.actor_player_id,
                        target_player_id=target_player_id,
                        payload={"transport_audience": activation.audience},
                        state="pending",
                    )
                )
                _append_event(
                    db,
                    game=game,
                    event_type="effect_intent_recorded",
                    audience=activation.audience,
                    payload={
                        "action_id": row.action_id,
                        "activation_id": activation.activation_id,
                        "effect_intent_id": effect_id,
                        "effect_type": effect_type,
                        "actor_player_id": activation.actor_player_id,
                        "target_player_id": target_player_id,
                    },
                )
            row.status = "completed"
            row.decision_id = f"v2_decision_{uuid4().hex[:16]}"
            row.knowledge_fact_ids = [*(row.knowledge_fact_ids or []), *knowledge_ids]
            row.decision = decision
            row.result = {**result, "effect_intent_id": effect_id}
            row.closed_at = _now()
            if ability_state_patch:
                instance = db.get(AbilityInstance, activation.ability_instance_id)
                if instance is None:
                    raise RepositoryError("ability instance disappeared")
                instance.state = {**(instance.state or {}), **ability_state_patch}
            _append_event(
                db,
                game=game,
                event_type="ability_activation_completed",
                audience=activation.audience,
                payload={
                    "action_id": row.action_id,
                    "activation_id": activation.activation_id,
                    "ability_id": activation.ability_id,
                    "decision_id": row.decision_id,
                    "decision": decision,
                    "result": row.result,
                    "knowledge_fact_ids": row.knowledge_fact_ids,
                },
            )

    def complete_activation_technical_no_action(
        self,
        *,
        state: NightRuntimeState,
        activation: ActivationRef,
        technical_outcome: dict[str, Any],
        decision_context: dict[str, Any] | None = None,
        result_context: dict[str, Any] | None = None,
        knowledge: tuple[tuple[str, str, dict[str, Any]], ...] = (),
    ) -> None:
        if technical_outcome.get("kind") != "technical_no_action":
            raise RepositoryError("invalid technical no-action outcome")
        if activation.audience != "god_view":
            raise RepositoryError("technical no-action activation must remain god-view only")
        source_action_id = technical_outcome.get("source_action_id")
        supporting_event_record_seq = technical_outcome.get("supporting_event_record_seq")
        failure_episode_id = technical_outcome.get("failure_episode_id")
        source_failure_code = technical_outcome.get("source_failure_code")
        source_failure_category = technical_outcome.get("source_failure_category")
        source_attempt_id = technical_outcome.get("source_attempt_id")
        failure_mode = technical_outcome.get("failure_mode")
        if not isinstance(source_action_id, str) or not source_action_id:
            raise RepositoryError("technical no-action source action is missing")
        if not isinstance(failure_episode_id, str) or not failure_episode_id:
            raise RepositoryError("technical no-action failure episode is missing")
        if not isinstance(source_failure_code, str) or not source_failure_code:
            raise RepositoryError("technical no-action failure code is missing")
        if source_failure_category not in {"output_budget", "timeout"}:
            raise RepositoryError("technical no-action failure category is invalid")
        if not isinstance(source_attempt_id, str) or not source_attempt_id:
            raise RepositoryError("technical no-action source attempt is missing")
        if failure_mode not in {
            "output_budget_exhausted",
            "attempt_hard_timeout",
            "action_wall_timeout",
        }:
            raise RepositoryError("technical no-action failure mode is invalid")
        expected_failure_category = (
            "output_budget" if failure_mode == "output_budget_exhausted" else "timeout"
        )
        if source_failure_category != expected_failure_category:
            raise RepositoryError("technical no-action failure mode does not match")
        if (
            not isinstance(supporting_event_record_seq, int)
            or isinstance(supporting_event_record_seq, bool)
            or supporting_event_record_seq <= 0
        ):
            raise RepositoryError("technical no-action supporting event is invalid")
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                state.game_id,
                require_fence=self._enforce_execution_fence,
            )
            row = db.get(AbilityActivation, activation.activation_id)
            if row is None or row.status != "open":
                raise RepositoryError("ability activation is not open")
            if row.action_id != source_action_id:
                raise RepositoryError("technical no-action source action does not match")
            supporting_event = db.scalar(
                select(GameRecordEvent).where(
                    GameRecordEvent.game_id == state.game_id,
                    GameRecordEvent.record_seq == supporting_event_record_seq,
                )
            )
            supporting_payload = supporting_event.payload if supporting_event is not None else {}
            if (
                supporting_event is None
                or supporting_event.run_id != state.run_id
                or supporting_event.event_type != "technical_target_outcome_applied"
                or supporting_payload.get("action_id") != source_action_id
                or supporting_payload.get("activation_id") != activation.activation_id
                or supporting_payload.get("failure_episode_id") != failure_episode_id
                or supporting_payload.get("failure_code") != source_failure_code
                or supporting_payload.get("failure_category") != source_failure_category
                or supporting_payload.get("attempt_id") != source_attempt_id
                or supporting_payload.get("actor_id") != activation.actor_player_id
                or supporting_payload.get("technical_outcome") != "technical_no_action"
                or supporting_payload.get("audience") != "god_view"
                or supporting_payload.get("target_player_id") is not None
                or supporting_payload.get("target_exhaustion_failure_mode") != failure_mode
                or supporting_payload.get("model_generation_policy_schema_version")
                not in MODEL_GENERATION_POLICY_SUPPORTED_SCHEMA_VERSIONS
            ):
                raise RepositoryError("technical no-action supporting event does not match")
            action_succeeded_events = list(
                db.scalars(
                    select(GameRecordEvent).where(
                        GameRecordEvent.game_id == state.game_id,
                        GameRecordEvent.run_id == state.run_id,
                        GameRecordEvent.event_type == "action_succeeded",
                    )
                )
            )
            action_succeeded = next(
                (
                    event
                    for event in action_succeeded_events
                    if (event.payload or {}).get("action_id") == source_action_id
                ),
                None,
            )
            action_succeeded_payload = (
                action_succeeded.payload if action_succeeded is not None else {}
            )
            if (
                action_succeeded is None
                or action_succeeded.record_seq <= supporting_event_record_seq
                or action_succeeded_payload.get("activation_id") != activation.activation_id
                or action_succeeded_payload.get("failure_episode_id") != failure_episode_id
                or action_succeeded_payload.get("technical_outcome_record_seq")
                != supporting_event_record_seq
                or action_succeeded_payload.get("result")
                != "decision_recorded_without_presentation"
                or action_succeeded_payload.get("audience") != "god_view"
            ):
                raise RepositoryError("technical no-action action completion does not match")

            decision_payload = {
                **(decision_context or {}),
                "decision_status": "technical_no_action",
            }
            result_payload = {
                **(result_context or {}),
                "decision_status": "technical_no_action",
                "effect_applied": False,
                "technical_outcome": dict(technical_outcome),
                "effect_intent_id": None,
            }
            durable_knowledge = list(knowledge)
            if activation.actor_player_id is not None:
                durable_knowledge.append(
                    (
                        "player",
                        activation.actor_player_id,
                        {
                            "fact_type": "private_ability_action_not_taken",
                            "payload": {
                                "ability_id": activation.ability_id,
                                "night_no": state.round_no,
                                "decision": dict(decision_payload),
                                "result": {
                                    "decision_status": "technical_no_action",
                                    "effect_applied": False,
                                    "source_failure_code": technical_outcome.get(
                                        "source_failure_code"
                                    ),
                                },
                                "resolution_scope": (
                                    "本次私有动作因技术耗尽未执行；未选择目标、未产生效果，"
                                    "也不额外公开其他玩家身份。"
                                ),
                            },
                        },
                    )
                )

            knowledge_ids: list[str] = []
            for owner_scope, owner_id, fact in durable_knowledge:
                fact_id = f"v2_fact_{uuid4().hex[:16]}"
                knowledge_ids.append(fact_id)
                db.add(
                    KnowledgeFact(
                        knowledge_fact_id=fact_id,
                        game_id=state.game_id,
                        source_activation_id=activation.activation_id,
                        owner_scope=owner_scope,
                        owner_id=owner_id,
                        fact_type=str(fact["fact_type"]),
                        payload=dict(fact["payload"]),
                    )
                )

            row.status = "completed"
            row.decision_id = None
            row.knowledge_fact_ids = [*(row.knowledge_fact_ids or []), *knowledge_ids]
            row.decision = decision_payload
            row.result = result_payload
            row.closed_at = _now()
            _append_event(
                db,
                game=game,
                event_type="ability_activation_technical_no_action",
                audience=activation.audience,
                payload={
                    "action_id": row.action_id,
                    "activation_id": activation.activation_id,
                    "ability_id": activation.ability_id,
                    "decision": decision_payload,
                    "result": result_payload,
                    "knowledge_fact_ids": row.knowledge_fact_ids,
                },
            )

    def register_activation_knowledge(
        self,
        *,
        state: NightRuntimeState,
        activation: ActivationRef,
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
            game = _locked_game(
                db,
                state.game_id,
                require_fence=self._enforce_execution_fence,
            )
            row = db.get(AbilityActivation, activation.activation_id)
            if row is None or row.status != "open":
                raise RepositoryError("activation knowledge cannot be registered")
            existing_ids = tuple(row.knowledge_fact_ids or ())
            if existing_ids:
                facts_by_id = {
                    fact.knowledge_fact_id: fact
                    for fact in db.scalars(
                        select(KnowledgeFact).where(
                            KnowledgeFact.knowledge_fact_id.in_(existing_ids)
                        )
                    )
                }
                existing = [facts_by_id.get(fact_id) for fact_id in existing_ids]
                if (
                    any(fact is None for fact in existing)
                    or any(
                        fact.source_activation_id != activation.activation_id for fact in existing
                    )
                    or any(fact.owner_scope != "player" for fact in existing)
                    or any(fact.owner_id != owner_player_id for fact in existing)
                    or len(existing) != 1
                    or existing[0].fact_type != "action_context_projection"
                    or (existing[0].payload or {}).get("normalized_sha256") != digest
                ):
                    raise RepositoryError("activation knowledge projection changed during retry")
                _append_event(
                    db,
                    game=game,
                    event_type="activation_knowledge_reused",
                    audience=activation.audience,
                    payload={
                        "activation_id": activation.activation_id,
                        "knowledge_fact_ids": list(existing_ids),
                        "projection_policy_id": "v2_ability_allowed_knowledge.v1",
                        "normalized_sha256": digest,
                    },
                )
                return existing_ids, digest
            db.add(
                KnowledgeFact(
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
                audience=activation.audience,
                payload={
                    "activation_id": activation.activation_id,
                    "knowledge_fact_ids": [fact_id],
                    "projection_policy_id": "v2_ability_allowed_knowledge.v1",
                    "normalized_sha256": digest,
                },
            )
        return (fact_id,), digest

    def cancel_open_activation(
        self,
        *,
        state: NightRuntimeState,
        activation: ActivationRef,
        reason: str,
        batch_id: str | None = None,
        group: str | None = None,
    ) -> bool:
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                state.game_id,
                require_fence=self._enforce_execution_fence,
            )
            row = db.get(AbilityActivation, activation.activation_id)
            if row is None or row.game_id != state.game_id:
                raise RepositoryError("ability activation is missing")
            if row.status != "open":
                return False
            row.status = "canceled"
            row.skip_reason = reason
            row.result = {
                "decision_status": "canceled",
                "reason": reason,
                "action_id": row.action_id,
            }
            row.closed_at = _now()
            _append_event(
                db,
                game=game,
                event_type="ability_activation_canceled",
                audience=activation.audience,
                payload={
                    "activation_id": activation.activation_id,
                    "ability_id": activation.ability_id,
                    "action_id": row.action_id,
                    "reason": reason,
                },
            )
            if batch_id is not None and group is not None:
                _append_event(
                    db,
                    game=game,
                    event_type="night_parallel_lane_canceled",
                    audience=activation.audience,
                    payload={
                        "round_no": state.round_no,
                        "window_id": state.window_id,
                        "batch_id": batch_id,
                        "group": group,
                        "activation_id": activation.activation_id,
                    },
                )
            return True

    def cancel_open_activations(
        self,
        *,
        state: NightRuntimeState,
        reason: str,
        audience: str,
        batch_id: str | None = None,
        groups: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                state.game_id,
                require_fence=self._enforce_execution_fence,
            )
            rows = list(
                db.scalars(
                    select(AbilityActivation)
                    .where(
                        AbilityActivation.game_id == state.game_id,
                        AbilityActivation.window_id == state.window_id,
                        AbilityActivation.status == "open",
                    )
                    .order_by(
                        AbilityActivation.ability_instance_id,
                        AbilityActivation.occurrence,
                    )
                )
            )
            for row in rows:
                row.status = "canceled"
                row.skip_reason = reason
                row.result = {
                    "decision_status": "canceled",
                    "reason": reason,
                    "action_id": row.action_id,
                }
                row.closed_at = _now()
                instance = db.get(AbilityInstance, row.ability_instance_id)
                _append_event(
                    db,
                    game=game,
                    event_type="ability_activation_canceled",
                    audience=audience,
                    payload={
                        "activation_id": row.activation_id,
                        "ability_id": instance.ability_id if instance is not None else None,
                        "action_id": row.action_id,
                        "reason": reason,
                    },
                )
            if batch_id is not None:
                _append_event(
                    db,
                    game=game,
                    event_type="night_parallel_batch_canceled",
                    audience=audience,
                    payload={
                        "round_no": state.round_no,
                        "window_id": state.window_id,
                        "batch_id": batch_id,
                        "groups": list(groups),
                        "canceled_activation_ids": [row.activation_id for row in rows],
                    },
                )
            return tuple(row.activation_id for row in rows)

    def skip_activation(
        self,
        *,
        state: NightRuntimeState,
        ability_id: str,
        reason: str,
        audience: str,
        occurrence: int = 1,
    ) -> ActivationRef:
        instance_data = state.instance(ability_id)
        if instance_data is None:
            raise RepositoryError(f"ability {ability_id} is not configured")
        activation_id = f"v2_activation_{uuid4().hex[:16]}"
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                state.game_id,
                require_fence=self._enforce_execution_fence,
            )
            row, activation = self._open_activation_locked(
                db=db,
                game=game,
                state=state,
                instance_data=instance_data,
                activation_id=activation_id,
                actor_player_id=None,
                occurrence=occurrence,
                audience=audience,
            )
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
                audience=activation.audience,
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
        state: NightRuntimeState,
        attack_target: str | None,
        protected_target: str | None,
        healed_target: str | None,
        poisoned_target: str | None,
    ) -> NightResolutionRecord:
        resolution = resolve_first_night(
            attack_target=attack_target,
            protected_target=protected_target,
            healed_target=healed_target,
            poisoned_target=poisoned_target,
        )
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                state.game_id,
                require_fence=self._enforce_execution_fence,
            )
            window = db.get(ActionWindow, state.window_id)
            if window is None or window.state != "open" or game.phase_state != "night_running":
                raise RepositoryError("night window is not resolvable")
            effect_rows = list(
                db.scalars(
                    select(EffectIntent).where(
                        EffectIntent.game_id == state.game_id,
                        EffectIntent.window_id == state.window_id,
                        EffectIntent.state == "pending",
                    )
                )
            )
            death_by_player = {item["player_id"]: item["cause"] for item in resolution.deaths}
            for effect in effect_rows:
                effect.state = "resolved"
                effect.resolved_at = _now()
                effect_audience = _effect_intent_audience(effect)
                outcome = _effect_outcome(
                    effect.effect_type,
                    effect.target_player_id,
                    death_by_player,
                    resolution.attack_prevented_by,
                )
                effect.payload = {
                    **(effect.payload or {}),
                    "outcome": outcome,
                }
                activation = db.get(AbilityActivation, effect.activation_id)
                _append_event(
                    db,
                    game=game,
                    event_type="effect_intent_resolved",
                    audience=effect_audience,
                    payload={
                        "action_id": activation.action_id if activation is not None else None,
                        "activation_id": effect.activation_id,
                        "effect_intent_id": effect.effect_intent_id,
                        "effect_type": effect.effect_type,
                        "target_player_id": effect.target_player_id,
                        "outcome": outcome,
                    },
                )
            for item in resolution.deaths:
                player_state = db.get(PlayerState, (state.game_id, item["player_id"]))
                if player_state is None or not player_state.alive:
                    raise RepositoryError("night death target is not alive")
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
            match = db.get(MatchState, state.game_id)
            if match is None:
                raise RepositoryError("night match state is missing")
            should_elect_before_dawn = (
                state.round_no == 1
                and bool(game.ability_snapshot.get("sheriff_enabled"))
                and match.sheriff_badge_state == "pending"
                and not _pending_terminal_is_inevitable(db, game)
            )
            game.phase_state = (
                "sheriff_election_ready" if should_elect_before_dawn else "dawn_announcement_ready"
            )
            game.status = "ready"
            _run(db, game.current_run_id).status = "ready"
            transition = PhaseTransition(
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
                audience="god_view",
                payload={"window_id": window.window_id, "result": result},
            )
            _append_event(
                db,
                game=game,
                event_type="night_resolution_committed",
                audience="god_view",
                payload={
                    "round_no": state.round_no,
                    "pending_death_count": len(resolution.deaths),
                },
            )
            _append_event(
                db,
                game=game,
                event_type="game_phase_changed",
                audience="all",
                payload=_transition_payload(transition),
            )
        return NightResolutionRecord(
            deaths=resolution.deaths,
            peaceful=resolution.peaceful,
            attack_prevented_by=resolution.attack_prevented_by,
            transition=transition,
        )

    def ready_dawn_announcement(self, *, game_id: str) -> PhaseTransition:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            if game.phase_state != "sheriff_election_open":
                raise RepositoryError("pre-dawn sheriff election is not complete")
            game.phase_state = "dawn_announcement_ready"
            transition = PhaseTransition(
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
                audience="all",
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
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            if game.phase_state != "dawn_announcement_ready":
                raise RepositoryError("dawn deaths are not ready to reveal")
            revealed: list[dict[str, str]] = []
            rows = list(
                db.scalars(
                    select(PlayerState)
                    .where(PlayerState.game_id == game_id)
                    .order_by(PlayerState.seat)
                )
            )
            for player_state in rows:
                pending = (player_state.state or {}).get("pending_dawn_death")
                if not isinstance(pending, dict):
                    continue
                cause = pending.get("cause")
                window_seq = pending.get("window_seq")
                if not isinstance(cause, str) or not isinstance(window_seq, int):
                    raise RepositoryError("pending dawn death is invalid")
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
                raise RepositoryError("revealed dawn deaths differ from night resolution")
            round_no = _day_round_no(game.phase_id)
            _append_event(
                db,
                game=game,
                event_type="dawn_public_result",
                audience="all",
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
                    RoleAssignment.player_id,
                    PlayerState.death_cause,
                    PlayerState.state,
                )
                .join(
                    PlayerState,
                    (PlayerState.game_id == RoleAssignment.game_id)
                    & (PlayerState.player_id == RoleAssignment.player_id),
                )
                .where(
                    RoleAssignment.game_id == game_id,
                    RoleAssignment.role_key == "hunter",
                    PlayerState.alive.is_(False),
                    PlayerState.death_cause != "witch_poison",
                )
                .order_by(RoleAssignment.seat)
            )
            return tuple(
                player_id
                for player_id, _cause, state in rows
                if not (state or {}).get("hunter_response_resolved")
            )

    def hunter_settlement_can_change_winner(self, game_id: str) -> bool:
        with self._session_factory() as db:
            game = db.get(GameRecord, game_id)
            if game is None:
                raise RepositoryError(f"unknown game {game_id}")
            rows = list(
                db.execute(
                    select(
                        RoleAssignment.player_id,
                        RoleAssignment.role_key,
                        PlayerState.alive,
                        PlayerState.death_cause,
                        PlayerState.state,
                    )
                    .join(
                        PlayerState,
                        (PlayerState.game_id == RoleAssignment.game_id)
                        & (PlayerState.player_id == RoleAssignment.player_id),
                    )
                    .where(RoleAssignment.game_id == game_id)
                    .order_by(RoleAssignment.seat)
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
        state: NightRuntimeState,
    ) -> NightRuntimeState:
        hunter = state.instance("hunter.death_shot")
        if hunter is None:
            raise RepositoryError("hunter response is not configured")
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                state.game_id,
                require_fence=self._enforce_execution_fence,
            )
            if game.phase_id != f"day_{state.round_no}":
                raise RepositoryError("dawn response is not ready")
            if game.phase_state == "dawn_reactions_ready":
                window = db.scalar(
                    select(ActionWindow).where(
                        ActionWindow.game_id == state.game_id,
                        ActionWindow.window_type == "dawn_reaction",
                        ActionWindow.state == "open",
                    )
                )
                if window is None:
                    raise RepositoryError("dawn reaction window is missing")
                window_id = window.window_id
                next_window_seq = window.window_seq
            elif game.phase_state == "dawn_announced":
                next_window_seq = (
                    int(
                        db.scalar(
                            select(func.coalesce(func.max(ActionWindow.window_seq), 0)).where(
                                ActionWindow.game_id == state.game_id
                            )
                        )
                        or 0
                    )
                    + 1
                )
                window = ActionWindow(
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
                    audience="god_view",
                    payload={
                        "window_id": window_id,
                        "window_seq": next_window_seq,
                        "window_type": "dawn_reaction",
                    },
                )
            else:
                raise RepositoryError("dawn response is not ready")
        return NightRuntimeState(
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
        state: NightRuntimeState,
        activation_id: str,
        hunter_player_id: str,
        target_player_id: str,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                state.game_id,
                require_fence=self._enforce_execution_fence,
            )
            activation = db.get(AbilityActivation, activation_id)
            effect = db.scalar(
                select(EffectIntent).where(
                    EffectIntent.game_id == state.game_id,
                    EffectIntent.window_id == state.window_id,
                    EffectIntent.activation_id == activation_id,
                    EffectIntent.effect_type == "shoot",
                )
            )
            if activation is None or effect is None:
                raise RepositoryError("hunter shoot intent is missing")
            if (
                activation.game_id != state.game_id
                or activation.window_id != state.window_id
                or activation.status != "completed"
                or activation.actor_player_id != hunter_player_id
                or effect.actor_id != hunter_player_id
                or effect.target_player_id != target_player_id
            ):
                raise RepositoryError("hunter shoot intent does not match resolution")
            target = db.get(PlayerState, (state.game_id, target_player_id))
            hunter = db.get(PlayerState, (state.game_id, hunter_player_id))
            if hunter is None:
                raise RepositoryError("hunter state is missing")
            if target is None:
                raise RepositoryError("hunter target is missing")
            hunter_response_resolved = (hunter.state or {}).get("hunter_response_resolved")
            if effect.state == "resolved":
                if (
                    effect.resolved_at is not None
                    and (effect.payload or {}).get("outcome") == "killed"
                    and not target.alive
                    and target.death_cause == "hunter_shot"
                    and target.death_window_seq == state.window_seq
                    and hunter_response_resolved is True
                ):
                    return
                raise RepositoryError("resolved hunter shoot intent is inconsistent")
            if effect.state != "pending":
                raise RepositoryError("hunter shoot intent is not pending or resolved")
            if not target.alive:
                raise RepositoryError("hunter target is not alive")
            if hunter_response_resolved is True:
                raise RepositoryError("pending hunter shoot intent is inconsistent")
            target.alive = False
            target.death_cause = "hunter_shot"
            target.death_window_seq = state.window_seq
            hunter.state = {**(hunter.state or {}), "hunter_response_resolved": True}
            effect.state = "resolved"
            effect.resolved_at = _now()
            effect.payload = {**(effect.payload or {}), "outcome": "killed"}
            _append_event(
                db,
                game=game,
                event_type="effect_intent_resolved",
                audience=_effect_intent_audience(effect),
                payload={
                    "action_id": activation.action_id,
                    "activation_id": activation.activation_id,
                    "effect_intent_id": effect.effect_intent_id,
                    "effect_type": effect.effect_type,
                    "target_player_id": effect.target_player_id,
                    "outcome": "killed",
                },
            )
            _append_event(
                db,
                game=game,
                event_type="hunter_response_resolved",
                audience="all",
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
        state: NightRuntimeState,
        hunter_player_id: str,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(
                db,
                state.game_id,
                require_fence=self._enforce_execution_fence,
            )
            hunter = db.get(PlayerState, (state.game_id, hunter_player_id))
            if hunter is None:
                raise RepositoryError("hunter state is missing")
            hunter.state = {**(hunter.state or {}), "hunter_response_resolved": True}
            _append_event(
                db,
                game=game,
                event_type="hunter_response_resolved",
                audience="all",
                payload={
                    "round_no": state.round_no,
                    "period": "dawn",
                    "effect_type": "shoot_skipped",
                    "hunter_player_id": hunter_player_id,
                },
            )

    def finish_night(self, *, game_id: str) -> PhaseTransition:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            round_no = _day_round_no(game.phase_id)
            if game.phase_state not in {
                "dawn_announced",
                "dawn_reactions_ready",
            }:
                raise RepositoryError("night is not ready to finish")
            open_window = db.scalar(
                select(ActionWindow).where(
                    ActionWindow.game_id == game_id,
                    ActionWindow.state == "open",
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
                    audience="god_view",
                    payload={
                        "window_id": open_window.window_id,
                        "result": open_window.result,
                    },
                )
            winner = _winner(db, game)
            match = db.get(MatchState, game_id)
            if match is None:
                raise RepositoryError("V2 match state is missing")
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
                    audience="all",
                    payload={
                        "winner": winner,
                        "reason": "deterministic_win_condition",
                        "round_no": round_no,
                    },
                )
            transition = PhaseTransition(
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
                audience="all",
                payload=_transition_payload(transition),
            )
            return transition

    def finish_first_night(self, *, game_id: str) -> PhaseTransition:
        return self.finish_night(game_id=game_id)

    def current_winner(self, game_id: str) -> str | None:
        with self._session_factory() as db:
            game = db.get(GameRecord, game_id)
            if game is None:
                raise RepositoryError(f"unknown game {game_id}")
            return _winner(db, game)

    def match_state(self, game_id: str) -> dict[str, Any]:
        with self._session_factory() as db:
            match = db.get(MatchState, game_id)
            if match is None:
                raise RepositoryError("V2 match state is missing")
            return {
                "round_no": match.round_no,
                "sheriff_player_id": match.sheriff_player_id,
                "sheriff_badge_state": match.sheriff_badge_state,
                "winner": match.winner,
            }

    def ability_state(self, *, game_id: str, ability_id: str) -> dict[str, Any]:
        with self._session_factory() as db:
            row = db.scalar(
                select(AbilityInstance).where(
                    AbilityInstance.game_id == game_id,
                    AbilityInstance.ability_id == ability_id,
                )
            )
            return dict(row.state or {}) if row is not None else {}

    def player_knowledge(
        self,
        *,
        game_id: str,
        player_id: str,
        at_or_before_record_seq: int | None = None,
    ) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            return player_private_knowledge(
                db,
                game_id=game_id,
                player_id=player_id,
                at_or_before_record_seq=at_or_before_record_seq,
            )

    def record_player_knowledge(
        self,
        *,
        game_id: str,
        player_id: str,
        fact_type: str,
        payload: dict[str, Any],
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            fact_id = f"v2_fact_{uuid4().hex[:16]}"
            db.add(
                KnowledgeFact(
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
                audience="god_view",
                payload={
                    "knowledge_fact_id": fact_id,
                    "owner_scope": "player",
                    "owner_id": player_id,
                    "fact_type": fact_type,
                },
            )

    def public_history(self, game_id: str) -> list[dict[str, Any]]:
        public_types = {
            "action_skipped_technical",
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
        with self._session_factory() as db:
            rows = list(
                db.scalars(
                    select(GameRecordEvent)
                    .where(
                        GameRecordEvent.game_id == game_id,
                        GameRecordEvent.event_type.in_(public_types),
                    )
                    .order_by(GameRecordEvent.record_seq.desc())
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
                    select(LivePresentation)
                    .where(
                        LivePresentation.game_id == game_id,
                        LivePresentation.actor_kind == "player",
                        LivePresentation.audience == "all",
                        LivePresentation.state == "closed",
                    )
                    .order_by(LivePresentation.source_event_id)
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

    def current_players(self, game_id: str) -> tuple[NightPlayer, ...]:
        with self._session_factory() as db:
            game = db.get(GameRecord, game_id)
            if game is None:
                raise RepositoryError(f"unknown game {game_id}")
            return _players(db, game)

    def latest_presentation_seq(self, game_id: str) -> int:
        with self._session_factory() as db:
            game = db.get(GameRecord, game_id)
            if game is None:
                raise RepositoryError(f"unknown game {game_id}")
            return game.last_presentation_seq

    def current_phase_state(self, game_id: str) -> str:
        with self._session_factory() as db:
            game = db.get(GameRecord, game_id)
            if game is None:
                raise RepositoryError(f"unknown game {game_id}")
            return game.phase_state

    def fail_runtime(self, *, game_id: str, failure_code: str) -> str:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            run = _run(db, game.current_run_id)
            if run.stop_requested_at is not None:
                raise GameCanceled("V2 game was canceled by an administrator")
            game.status = "failed"
            game.phase_state = "failed"
            run.status = "failed"
            run.completed_at = _now()
            failed_failure_episode_ids = _open_failure_episode_ids_for_locked_run(
                db,
                game=game,
            )
            _append_event(
                db,
                game=game,
                event_type="ability_runtime_failed",
                audience="god_view",
                payload={
                    "failure_code": failure_code,
                    "failed_failure_episode_ids": list(failed_failure_episode_ids),
                    "failure_episode_disposition": "run_failure",
                },
            )
            return run.run_id


def _players(db: Session, game: GameRecord) -> tuple[NightPlayer, ...]:
    assignments = list(
        db.scalars(
            select(RoleAssignment)
            .where(RoleAssignment.game_id == game.game_id)
            .order_by(RoleAssignment.seat)
        )
    )
    profiles = {
        str(item["profile_id"]): item
        for item in game.players_snapshot
        if isinstance(item, dict) and item.get("profile_id")
    }
    result: list[NightPlayer] = []
    for assignment in assignments:
        player_state = db.get(PlayerState, (game.game_id, assignment.player_id))
        profile = profiles.get(assignment.player_id, {})
        if player_state is None:
            raise RepositoryError("player state is incomplete")
        try:
            frozen_model = frozen_player_model_configuration(profile)
        except FrozenModelParametersError as exc:
            raise RepositoryError("invalid frozen player model configuration") from exc
        result.append(
            NightPlayer(
                player_id=assignment.player_id,
                seat=assignment.seat,
                display_name=str(profile.get("name") or f"{assignment.seat}号玩家"),
                role_key=assignment.role_key,
                team=("werewolves" if assignment.role_key == "werewolf" else "villagers"),
                alive=player_state.alive,
                tts_speaker=(str(profile["tts_speaker"]) if profile.get("tts_speaker") else None),
                tts_dialect=(str(profile["tts_dialect"]) if profile.get("tts_dialect") else None),
                model_provider=frozen_model.provider,
                model_id=frozen_model.model_id,
                model_supports_thinking=frozen_model.supports_thinking,
                model_parameters=frozen_model.parameters,
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


def _winner(db: Session, game: GameRecord) -> str | None:
    rows = list(
        db.execute(
            select(RoleAssignment.role_key, PlayerState.alive)
            .join(
                PlayerState,
                (PlayerState.game_id == RoleAssignment.game_id)
                & (PlayerState.player_id == RoleAssignment.player_id),
            )
            .where(RoleAssignment.game_id == game.game_id)
        )
    )
    alive_roles = [role_key for role_key, alive in rows if alive]
    return winner_from_alive_roles(
        alive_roles,
        win_condition=str(game.ability_snapshot.get("win_condition") or "wolves_gte_others"),
    )


def _pending_terminal_is_inevitable(db: Session, game: GameRecord) -> bool:
    rows = list(
        db.execute(
            select(
                RoleAssignment.player_id,
                RoleAssignment.role_key,
                PlayerState.alive,
                PlayerState.state,
            )
            .join(
                PlayerState,
                (PlayerState.game_id == RoleAssignment.game_id)
                & (PlayerState.player_id == RoleAssignment.player_id),
            )
            .where(RoleAssignment.game_id == game.game_id)
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
    game: GameRecord,
    ability_snapshot: dict[str, Any],
) -> dict[str, Any]:
    rule = game.rule_snapshot.get("rule_set")
    if not isinstance(rule, dict):
        raise RepositoryError("V2 night runtime has no frozen rule")
    compiled = dict(rule)
    compiled["day_actions"] = list(ability_snapshot.get("day_actions") or [])
    compiled["ability_policies"] = dict(ability_snapshot.get("policies") or {})
    for key, value in dict(ability_snapshot.get("day_policies") or {}).items():
        compiled.setdefault(key, value)
    return compiled


def _locked_game(
    db: Session,
    game_id: str,
    *,
    require_fence: bool,
) -> GameRecord:
    game = db.scalar(select(GameRecord).where(GameRecord.game_id == game_id).with_for_update())
    if game is None:
        raise RepositoryError(f"unknown game {game_id}")
    if require_fence:
        try:
            require_run_fence(db, game)
        except RunFenceRejected as exc:
            raise ExecutionOwnershipLost(str(exc)) from exc
    run = _run(db, game.current_run_id)
    if run.stop_requested_at is not None:
        raise GameCanceled("V2 game was canceled by an administrator")
    return game


def _run(db: Session, run_id: str) -> GameRun:
    run = db.get(GameRun, run_id)
    if run is None:
        raise RepositoryError(f"unknown run {run_id}")
    return run


def _append_event(
    db: Session,
    *,
    game: GameRecord,
    event_type: str,
    audience: str,
    payload: dict[str, Any],
) -> None:
    next_seq = game.last_record_seq + 1
    db.add(
        GameRecordEvent(
            game_id=game.game_id,
            event_id=next_seq,
            record_seq=next_seq,
            run_id=game.current_run_id,
            event_type=event_type,
            payload_schema_version=1,
            payload=canonical_event_payload(payload, audience=audience),
        )
    )
    game.last_record_seq = next_seq


def _effect_intent_audience(effect: EffectIntent) -> str:
    audience = (effect.payload or {}).get("transport_audience")
    if not isinstance(audience, str):
        raise RepositoryError("effect intent has no explicit transport audience")
    return audience


def _transition_payload(transition: PhaseTransition) -> dict[str, Any]:
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
    raise RepositoryError("invalid V2 night phase id")


def _action_types_by_id(db: Session, game_id: str) -> dict[str, str]:
    rows = list(
        db.scalars(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == game_id,
                GameRecordEvent.event_type == "action_opened",
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
    raise RepositoryError("invalid V2 day phase id")
