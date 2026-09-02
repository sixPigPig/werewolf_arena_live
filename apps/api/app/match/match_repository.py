from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
import math
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.match.day_speech_pipeline_contract import (
    ResolvedDaySpeechPipelineContract,
    resolve_day_speech_pipeline_contract,
)
from app.match.knowledge_timeline import player_private_knowledge
from app.match.execution import RunFenceRejected, require_run_fence
from app.match.event_contract import canonical_event_payload
from app.match.model_context_contract import frozen_model_context_contract
from app.match.model_context_compaction import expand_known_events_v7
from app.match.model_context import (
    ModelPlayerReference,
    build_private_round_memory_action_context,
    project_model_action_context_with_metadata,
)
from app.match.model_generation_policy_contract import (
    MODEL_GENERATION_POLICY_SCHEMA_VERSION,
    resolve_model_generation_policy_contract,
)
from app.match.model_parameters import (
    FrozenModelParametersError,
    frozen_player_model_configuration,
)
from app.match.model_client import request_payload_matches_model_context
from app.match.pre_exile_pipeline_contract import (
    ResolvedPreExilePipelineContract,
    pre_exile_context_sha256,
    resolve_pre_exile_pipeline_contract,
)
from app.match.models import (
    DaySpeechSlot,
    GameRecord,
    GameRecordEvent,
    GameRun,
    KnowledgeFact,
    LivePresentation,
    MatchState,
    PlayerState,
    PreExilePipeline,
    PreExileResult,
    RoleAssignment,
)
from app.match.repository import (
    ExecutionOwnershipLost,
    GameCanceled,
    PhaseTransition,
    RepositoryError,
    _open_failure_episode_ids_for_locked_run,
)
from app.match.runtime_state import AudioMode, delivery_audio_mode
from app.match.win_conditions import (
    hunter_settlement_can_change_winner,
    winner_from_alive_roles,
)


_NONTERMINAL_DAY_SPEECH_SLOT_STATES = (
    "reserved",
    "generating",
    "ready",
    "presenting",
)
_NONTERMINAL_PRE_EXILE_PIPELINE_STATES = (
    "collecting",
    "no_explosion",
    "votes_accepted",
)


@dataclass(frozen=True)
class MatchPlayer:
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
    state: dict[str, Any]


@dataclass(frozen=True)
class MatchSnapshot:
    game_id: str
    run_id: str
    last_record_seq: int
    phase_id: str
    phase_state: str
    round_no: int
    sheriff_player_id: str | None
    sheriff_badge_state: str
    pre_sheriff_explosion_count: int
    rule: dict[str, Any]
    max_rounds: int
    model_context_contract: dict[str, Any]
    model_generation_policy_contract: dict[str, Any] | None
    day_speech_pipeline_contract: ResolvedDaySpeechPipelineContract
    audio_mode: AudioMode
    players: tuple[MatchPlayer, ...]
    public_history: tuple[dict[str, Any], ...]
    last_presentation_seq: int = 0
    pre_exile_pipeline_contract: ResolvedPreExilePipelineContract = field(
        default_factory=lambda: resolve_pre_exile_pipeline_contract({})
    )

    def player(self, player_id: str) -> MatchPlayer:
        for player in self.players:
            if player.player_id == player_id:
                return player
        raise RepositoryError(f"unknown V2 player {player_id}")


@dataclass(frozen=True)
class PrivateRoundMemoryCommit:
    player_id: str
    memory: str
    commit_index: int
    source_refs: tuple[str, ...]
    source_refs_sha256: str
    previous_snapshot_fact_id: str | None
    action_id: str
    model_response_record_seq: int
    terminal_event_record_seq: int
    provider_request_id: str
    attempt_id: str
    request_payload_sha256: str
    projected_context_sha256: str
    projected_known_event_refs: tuple[str, ...]
    projected_known_events_sha256: str


@dataclass(frozen=True)
class DaySpeechPrefetchSnapshot:
    match_snapshot: MatchSnapshot
    public_cutoff_record_seq: int
    predecessor_presentation_id: str
    predecessor_action_id: str
    predecessor_source_event_id: int
    predecessor_source_record_seq: int
    predecessor_sealed_record_seq: int
    predecessor_actor_id: str


@dataclass(frozen=True)
class PreExilePrefetchSnapshot:
    match_snapshot: MatchSnapshot
    public_cutoff_record_seq: int
    predecessor_presentation_id: str
    predecessor_action_id: str
    predecessor_source_event_id: int
    predecessor_source_record_seq: int
    predecessor_sealed_record_seq: int
    predecessor_actor_id: str


@dataclass(frozen=True)
class ExileResult:
    player_id: str
    outcome: str
    winner_after_exile: str | None


@dataclass(frozen=True)
class PreExileExplosionCommit:
    outcome: Literal["no_explosion", "explosion_selected"]
    selected_player_id: str | None
    failed_player_ids: tuple[str, ...]


@dataclass(frozen=True)
class DayVoteCommit:
    voter_player_id: str
    target_player_id: str | None
    weight: float
    decision_note: str | None
    technical_status: Literal["technical_abstain"] | None = None
    technical_reason: str | None = None
    source_action_id: str | None = None
    supporting_event_record_seq: int | None = None
    failure_episode_id: str | None = None
    failure_mode: (
        Literal[
            "output_budget_exhausted",
            "attempt_hard_timeout",
            "action_wall_timeout",
        ]
        | None
    ) = None


class MatchRepository:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        enforce_execution_fence: bool = False,
    ) -> None:
        self._session_factory = session_factory
        self._enforce_execution_fence = enforce_execution_fence

    def snapshot(self, game_id: str) -> MatchSnapshot:
        self._ensure_state(game_id)
        with self._session_factory() as db:
            game = db.get(GameRecord, game_id)
            match = db.get(MatchState, game_id)
            if game is None or match is None:
                raise RepositoryError(f"unknown game {game_id}")
            return _match_snapshot(
                db,
                game=game,
                match=match,
                public_history=_public_history(db, game_id),
            )

    def snapshot_for_day_speech_prefetch(
        self,
        *,
        game_id: str,
        run_id: str,
        phase_id: str,
        phase_state: str,
        predecessor_presentation_id: str,
        predecessor_action_id: str,
        predecessor_source_event_id: int,
        predecessor_turn_player_id: str | None = None,
    ) -> DaySpeechPrefetchSnapshot:
        """Freeze model context containing one active, sealed public predecessor.

        The regular snapshot remains closed-presentation-only. This projection is
        deliberately explicit so it cannot be reused as a public transport view.
        """

        self._ensure_state(game_id)
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            _raise_if_stop_requested(db, game)
            if (
                game.current_run_id != run_id
                or game.phase_id != phase_id
                or game.phase_state != phase_state
                or not phase_id.startswith("day_")
            ):
                raise RepositoryError("day speech prefetch game/run/phase changed")
            run = _run(db, run_id)
            if (
                run.game_id != game_id
                or game.status not in {"broadcasting", "finalizing", "ready", "generating"}
                or run.status != game.status
            ):
                raise RepositoryError("day speech prefetch predecessor is not presenting")
            match = _match(db, game)
            cutoff = game.last_record_seq
            latest_record_seq = db.scalar(
                select(GameRecordEvent.record_seq)
                .where(GameRecordEvent.game_id == game_id)
                .order_by(GameRecordEvent.record_seq.desc())
                .limit(1)
            )
            if latest_record_seq != cutoff:
                raise RepositoryError("day speech prefetch record cutoff is inconsistent")
            predecessor = db.scalar(
                select(LivePresentation).where(
                    LivePresentation.game_id == game_id,
                    LivePresentation.presentation_id == predecessor_presentation_id,
                )
            )
            if predecessor is None or predecessor.state not in {"active", "queued"}:
                raise RepositoryError(
                    "day speech prefetch predecessor is not an open presentation"
                )
            technical_skip_predecessor = predecessor_turn_player_id is not None
            if technical_skip_predecessor and resolve_day_speech_pipeline_contract(
                game.rule_snapshot
            ).schema_version not in {2, 3}:
                raise RepositoryError(
                    "technical skip prefetch predecessor requires pipeline schema v2 or v3"
                )
            if (
                predecessor.presentation_id != predecessor_presentation_id
                or predecessor.action_id != predecessor_action_id
                or predecessor.source_event_id != predecessor_source_event_id
                or predecessor.run_id != run_id
                or predecessor.phase_id != phase_id
                or predecessor.actor_kind != ("judge" if technical_skip_predecessor else "player")
                or (technical_skip_predecessor and predecessor.actor_id != "judge")
                or predecessor.audience != "all"
                or predecessor.closed_at is not None
            ):
                raise RepositoryError("day speech prefetch predecessor identity is invalid")
            latest_presentation_seq = db.scalar(
                select(LivePresentation.presentation_seq)
                .where(LivePresentation.game_id == game_id)
                .order_by(LivePresentation.presentation_seq.desc())
                .limit(1)
            )
            if (
                latest_presentation_seq != predecessor.presentation_seq
                or game.last_presentation_seq != predecessor.presentation_seq
            ):
                raise RepositoryError("day speech prefetch predecessor is not latest")

            source = db.get(
                GameRecordEvent,
                (game_id, predecessor_source_event_id),
            )
            source_payload = source.payload if source is not None else None
            if (
                source is None
                or source.run_id != run_id
                or source.record_seq > cutoff
                or source.event_type != "speech_segment_committed"
                or not isinstance(source_payload, dict)
                or source_payload.get("audience") != "all"
                or source_payload.get("action_id") != predecessor_action_id
                or source_payload.get("presentation_id") != predecessor_presentation_id
                or source_payload.get("speech_id") != predecessor.speech_id
                or source_payload.get("segment_index") != predecessor.segment_index
                or source_payload.get("text") != predecessor.subtitle_text
                or not predecessor.subtitle_text.strip()
            ):
                raise RepositoryError("day speech prefetch predecessor source is invalid")

            lineage = list(
                db.scalars(
                    select(GameRecordEvent)
                    .where(
                        GameRecordEvent.game_id == game_id,
                        GameRecordEvent.run_id == run_id,
                        GameRecordEvent.record_seq <= cutoff,
                        GameRecordEvent.event_type.in_(
                            {
                                "action_opened",
                                "action_succeeded",
                                "action_failed",
                                "speech_opened",
                                "speech_segment_committed",
                                "speech_sealed",
                                "speech_closed",
                                "speech_interrupted",
                            }
                        ),
                    )
                    .order_by(GameRecordEvent.record_seq)
                )
            )
            opened_actions = [
                event
                for event in lineage
                if event.event_type == "action_opened"
                and event.payload.get("action_id") == predecessor_action_id
            ]
            if len(opened_actions) != 1:
                raise RepositoryError("day speech prefetch predecessor action is invalid")
            opened = opened_actions[0]
            action_context = opened.payload.get("context")
            if (
                opened.record_seq >= source.record_seq
                or not isinstance(action_context, dict)
                or action_context.get("action_id") != predecessor_action_id
                or action_context.get("game_id") != game_id
                or action_context.get("run_id") != run_id
                or action_context.get("phase_id") != phase_id
                or action_context.get("action_record_seq") != opened.record_seq
            ):
                raise RepositoryError("day speech prefetch predecessor action is invalid")
            predecessor_turn_actor_id = predecessor.actor_id
            if technical_skip_predecessor:
                speech_order = action_context.get("speech_order")
                public_skip_record_seq = action_context.get("public_skip_record_seq")
                if (
                    action_context.get("action_type") != "judge_day_speech_technical_skip"
                    or action_context.get("actor") != {"kind": "judge", "id": "judge"}
                    or action_context.get("skipped_player_id") != predecessor_turn_player_id
                    or type(action_context.get("speech_round")) is not int
                    or action_context["speech_round"] <= 0
                    or type(speech_order) is not list
                    or predecessor_turn_player_id not in speech_order
                    or type(public_skip_record_seq) is not int
                    or public_skip_record_seq <= 0
                    or public_skip_record_seq >= opened.record_seq
                ):
                    raise RepositoryError(
                        "day speech technical skip predecessor action is invalid"
                    )
                public_skip = db.scalar(
                    select(GameRecordEvent).where(
                        GameRecordEvent.game_id == game_id,
                        GameRecordEvent.run_id == run_id,
                        GameRecordEvent.record_seq == public_skip_record_seq,
                        GameRecordEvent.event_type == "action_skipped_technical",
                    )
                )
                public_skip_payload = public_skip.payload if public_skip is not None else None
                if (
                    not isinstance(public_skip_payload, dict)
                    or public_skip_payload.get("audience") != "all"
                    or public_skip_payload.get("phase_id") != phase_id
                    or public_skip_payload.get("round_no") != match.round_no
                    or public_skip_payload.get("action_type") != "day_debate_speech"
                    or public_skip_payload.get("actor_id") != predecessor_turn_player_id
                ):
                    raise RepositoryError(
                        "day speech technical skip predecessor has no public fact"
                    )
                predecessor_turn_actor_id = predecessor_turn_player_id
            elif action_context.get("action_type") != "day_debate_speech" or action_context.get(
                "actor"
            ) != {"kind": "player", "id": predecessor.actor_id}:
                raise RepositoryError("day speech prefetch predecessor action is invalid")
            speech_events = [
                event
                for event in lineage
                if event.payload.get("presentation_id") == predecessor_presentation_id
            ]
            speech_opened = [
                event for event in speech_events if event.event_type == "speech_opened"
            ]
            segments = [
                event for event in speech_events if event.event_type == "speech_segment_committed"
            ]
            sealed = [event for event in speech_events if event.event_type == "speech_sealed"]
            terminal_speech = [
                event
                for event in speech_events
                if event.event_type in {"speech_closed", "speech_interrupted"}
            ]
            terminal_action = [
                event
                for event in lineage
                if event.event_type in {"action_succeeded", "action_failed"}
                and event.payload.get("action_id") == predecessor_action_id
            ]
            if (
                len(speech_opened) != 1
                or len(segments) != 1
                or segments[0].event_id != source.event_id
                or len(sealed) != 1
                or terminal_speech
                or terminal_action
                or not (
                    opened.record_seq
                    < speech_opened[0].record_seq
                    < source.record_seq
                    < sealed[0].record_seq
                    <= cutoff
                )
                or any(
                    event.payload.get("action_id") != predecessor_action_id
                    or event.payload.get("speech_id") != predecessor.speech_id
                    or event.payload.get("audience") != "all"
                    for event in (*speech_opened, *segments, *sealed)
                )
            ):
                raise RepositoryError("day speech prefetch predecessor is not sealed")

            public_history = list(
                _public_history(
                    db,
                    game_id,
                    at_or_before_record_seq=cutoff,
                )
            )
            if not technical_skip_predecessor:
                if any(int(item["record_seq"]) == source.record_seq for item in public_history):
                    raise RepositoryError(
                        "day speech prefetch history would duplicate predecessor"
                    )
                public_history.append(
                    {
                        "source_event_id": source.event_id,
                        "record_seq": source.record_seq,
                        "event_type": "public_player_speech_presented",
                        "payload": {
                            "round_no": _round_no(predecessor.phase_id),
                            "stage": "day_debate_speech",
                            "action_id": predecessor_action_id,
                            "phase_id": predecessor.phase_id,
                            "player_id": predecessor.actor_id,
                            "speech": predecessor.subtitle_text,
                        },
                    }
                )
            public_history.sort(key=lambda item: int(item["record_seq"]))
            snapshot = _match_snapshot(
                db,
                game=game,
                match=match,
                last_record_seq=cutoff,
                public_history=tuple(public_history),
            )
            return DaySpeechPrefetchSnapshot(
                match_snapshot=snapshot,
                public_cutoff_record_seq=cutoff,
                predecessor_presentation_id=predecessor_presentation_id,
                predecessor_action_id=predecessor_action_id,
                predecessor_source_event_id=source.event_id,
                predecessor_source_record_seq=source.record_seq,
                predecessor_sealed_record_seq=sealed[0].record_seq,
                predecessor_actor_id=predecessor_turn_actor_id,
            )

    def snapshot_for_pre_exile_pipeline(
        self,
        *,
        game_id: str,
        run_id: str,
        phase_id: str,
        phase_state: str,
        predecessor_presentation_id: str,
        predecessor_action_id: str,
        predecessor_source_event_id: int,
        predecessor_turn_player_id: str | None = None,
    ) -> PreExilePrefetchSnapshot:
        """Freeze the final sealed speech without publishing it before close."""

        frozen = self.snapshot_for_day_speech_prefetch(
            game_id=game_id,
            run_id=run_id,
            phase_id=phase_id,
            phase_state=phase_state,
            predecessor_presentation_id=predecessor_presentation_id,
            predecessor_action_id=predecessor_action_id,
            predecessor_source_event_id=predecessor_source_event_id,
            predecessor_turn_player_id=predecessor_turn_player_id,
        )
        contract = frozen.match_snapshot.pre_exile_pipeline_contract
        if not all(
            contract.enables(action_type)
            for action_type in ("werewolf_self_explosion", "exile_vote")
        ):
            raise RepositoryError("pre_exile_pipeline_contract_disabled")
        return PreExilePrefetchSnapshot(
            match_snapshot=frozen.match_snapshot,
            public_cutoff_record_seq=frozen.public_cutoff_record_seq,
            predecessor_presentation_id=frozen.predecessor_presentation_id,
            predecessor_action_id=frozen.predecessor_action_id,
            predecessor_source_event_id=frozen.predecessor_source_event_id,
            predecessor_source_record_seq=frozen.predecessor_source_record_seq,
            predecessor_sealed_record_seq=frozen.predecessor_sealed_record_seq,
            predecessor_actor_id=frozen.predecessor_actor_id,
        )

    def private_knowledge(
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

    def private_round_memory_batch_terminal_status(
        self,
        *,
        game_id: str,
        run_id: str,
        phase_id: str,
        phase_state: str,
        round_no: int,
        batch_id: str,
        private_round_memory_mode: str,
    ) -> Literal["completed", "failed"] | None:
        """Return the durable terminal status for the current day-memory batch.

        A successful batch can commit immediately before a worker loses ownership or
        exits.  The phase transition is intentionally a later transaction, so the day
        engine uses this marker to resume without regenerating the same memories.
        """

        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            _raise_if_stop_requested(db, game)
            match = _match(db, game)
            if (
                game.current_run_id != run_id
                or game.phase_id != phase_id
                or game.phase_state != phase_state
                or match.round_no != round_no
                or not phase_id.startswith("day_")
            ):
                raise RepositoryError("private round memory batch phase changed")
            terminal = _private_round_memory_batch_terminal_event(
                db,
                game_id=game_id,
                run_id=run_id,
                batch_id=batch_id,
            )
            if terminal is None:
                return None
            payload = terminal.payload if isinstance(terminal.payload, dict) else {}
            if (
                payload.get("round_no") != round_no
                or payload.get("phase_id") != phase_id
                or payload.get("phase_state") != phase_state
                or payload.get("private_round_memory_mode") != private_round_memory_mode
            ):
                raise RepositoryError("private round memory batch terminal is inconsistent")
            status = payload.get("public_summary_status")
            if status not in {"completed", "failed"}:
                raise RepositoryError("private round memory batch terminal status is invalid")
            source_cutoff = _positive_int(payload.get("source_cutoff_record_seq"))
            commit_order = payload.get("commit_order")
            memories = payload.get("memories")
            if (
                source_cutoff is None
                or source_cutoff >= terminal.record_seq
                or not isinstance(commit_order, list)
                or any(not isinstance(item, str) or not item for item in commit_order)
                or len(commit_order) != len(set(commit_order))
                or not isinstance(memories, list)
            ):
                raise RepositoryError("private round memory batch terminal is incomplete")
            memory_by_owner = {
                item.get("player_id"): item
                for item in memories
                if isinstance(item, dict) and isinstance(item.get("player_id"), str)
            }
            if set(memory_by_owner) != set(commit_order):
                raise RepositoryError("private round memory batch terminal is incomplete")
            fact_ids = {
                item.get("knowledge_fact_id")
                for item in memory_by_owner.values()
                if item.get("status") in {"committed", "reused"}
            }
            if any(not isinstance(fact_id, str) or not fact_id for fact_id in fact_ids):
                raise RepositoryError("private round memory batch terminal is incomplete")
            durable_fact_ids = set(
                db.scalars(
                    select(KnowledgeFact.knowledge_fact_id).where(
                        KnowledgeFact.game_id == game_id,
                        KnowledgeFact.owner_scope == "player",
                        KnowledgeFact.fact_type == "private_round_memory",
                        KnowledgeFact.knowledge_fact_id.in_(fact_ids),
                    )
                )
            )
            if durable_fact_ids != fact_ids or any(
                item.get("status") not in {"committed", "reused", "generation_failed"}
                for item in memory_by_owner.values()
            ):
                raise RepositoryError("private round memory batch terminal is incomplete")
            return status

    def record_private_action_decision(
        self,
        *,
        game_id: str,
        player_id: str,
        round_no: int,
        action_type: str,
        decision: dict[str, Any],
        decision_note: str | None,
        context: dict[str, Any] | None = None,
    ) -> str | None:
        if not _normalized_decision_note(decision_note):
            return None
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            _raise_if_stop_requested(db, game)
            match = _match(db, game)
            if match.round_no != round_no or not game.phase_id.startswith("day_"):
                raise RepositoryError("private action decision phase changed before commit")
            player = db.get(PlayerState, (game_id, player_id))
            if player is None or not player.alive:
                raise RepositoryError("private action decision owner must be alive")
            return _add_private_action_decision(
                db,
                game=game,
                player_id=player_id,
                round_no=round_no,
                action_type=action_type,
                decision=decision,
                decision_note=decision_note,
                context=context,
            )

    def finalize_day_vote_batch(
        self,
        *,
        game_id: str,
        phase_id: str,
        phase_state: str,
        round_no: int,
        action_type: str,
        batch_id: str,
        public_cutoff_record_seq: int,
        expected_voter_ids: tuple[str, ...],
        votes: tuple[DayVoteCommit, ...],
        decision_context: dict[str, Any],
        resolution_payload: dict[str, Any],
        pre_exile_pipeline_id: str | None = None,
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            _raise_if_stop_requested(db, game)
            match = _match(db, game)
            pre_exile_pipeline: PreExilePipeline | None = None
            pre_exile_all_results: list[PreExileResult] = []
            pre_exile_self_results: list[PreExileResult] = []
            pre_exile_results: list[PreExileResult] = []
            if pre_exile_pipeline_id is not None:
                pre_exile_pipeline = db.scalar(
                    select(PreExilePipeline)
                    .where(PreExilePipeline.pipeline_id == pre_exile_pipeline_id)
                    .with_for_update()
                )
                if pre_exile_pipeline is None:
                    raise RepositoryError("unknown pre-exile pipeline")
                pre_exile_all_results = list(
                    db.scalars(
                        select(PreExileResult)
                        .where(PreExileResult.pipeline_id == pre_exile_pipeline_id)
                        .order_by(
                            PreExileResult.result_kind,
                            PreExileResult.actor_player_id,
                        )
                        .with_for_update()
                    )
                )
                pre_exile_results = [
                    result for result in pre_exile_all_results if result.result_kind == "exile_vote"
                ]
                pre_exile_self_results = [
                    result
                    for result in pre_exile_all_results
                    if result.result_kind == "self_explosion"
                ]
                if pre_exile_pipeline.state == "consumed":
                    _validate_idempotent_pre_exile_vote_commit(
                        db,
                        game=game,
                        pipeline=pre_exile_pipeline,
                        results=pre_exile_all_results,
                        phase_id=phase_id,
                        phase_state=phase_state,
                        round_no=round_no,
                        action_type=action_type,
                        batch_id=batch_id,
                        public_cutoff_record_seq=public_cutoff_record_seq,
                        expected_voter_ids=expected_voter_ids,
                        votes=votes,
                        decision_context=decision_context,
                        resolution_payload=resolution_payload,
                    )
                    return
                _validate_pre_exile_vote_commit_gate(
                    db,
                    game=game,
                    match=match,
                    pipeline=pre_exile_pipeline,
                    results=pre_exile_results,
                    self_results=pre_exile_self_results,
                    phase_id=phase_id,
                    phase_state=phase_state,
                    round_no=round_no,
                    action_type=action_type,
                    public_cutoff_record_seq=public_cutoff_record_seq,
                    expected_voter_ids=expected_voter_ids,
                    votes=votes,
                )
            _validate_day_vote_batch(
                db,
                game=game,
                match=match,
                phase_id=phase_id,
                phase_state=phase_state,
                round_no=round_no,
                action_type=action_type,
                batch_id=batch_id,
                public_cutoff_record_seq=public_cutoff_record_seq,
                expected_voter_ids=expected_voter_ids,
                votes=votes,
                decision_context=decision_context,
                resolution_payload=resolution_payload,
            )
            for vote in votes:
                vote_payload = {
                    "round_no": round_no,
                    "action_type": action_type,
                    "voter_player_id": vote.voter_player_id,
                    "target_player_id": vote.target_player_id,
                    "weight": vote.weight,
                    "batch_id": batch_id,
                    "public_cutoff_record_seq": public_cutoff_record_seq,
                }
                if vote.technical_status is not None:
                    vote_payload.update(
                        {
                            "technical_status": vote.technical_status,
                            "technical_reason": vote.technical_reason,
                        }
                    )
                _append_event(
                    db,
                    game=game,
                    event_type="day_vote_committed",
                    audience="all",
                    payload=vote_payload,
                )
                if vote.technical_status == "technical_abstain":
                    _append_event(
                        db,
                        game=game,
                        event_type="day_vote_technical_abstention_committed",
                        audience="god_view",
                        payload={
                            **vote_payload,
                            "source_action_id": vote.source_action_id,
                            "supporting_event_record_seq": (vote.supporting_event_record_seq),
                            "failure_episode_id": vote.failure_episode_id,
                            "failure_mode": vote.failure_mode,
                        },
                    )
                else:
                    _add_private_action_decision(
                        db,
                        game=game,
                        player_id=vote.voter_player_id,
                        round_no=round_no,
                        action_type=action_type,
                        decision={"target_player_id": vote.target_player_id},
                        decision_note=vote.decision_note,
                        context=decision_context,
                    )
            _append_event(
                db,
                game=game,
                event_type="day_vote_resolved",
                audience="all",
                payload=resolution_payload,
            )
            if pre_exile_pipeline is not None:
                consumed_at = _now()
                for result in pre_exile_results:
                    result.state = "committed"
                    result.terminal_at = consumed_at
                pre_exile_pipeline.state = "consumed"
                pre_exile_pipeline.vote_batch_id = batch_id
                pre_exile_pipeline.vote_decision_context_sha256 = pre_exile_context_sha256(
                    decision_context
                )
                pre_exile_pipeline.votes_accepted_at = consumed_at
                pre_exile_pipeline.consumed_at = consumed_at
                pre_exile_pipeline.terminal_at = consumed_at
                _append_event(
                    db,
                    game=game,
                    event_type="pre_exile_pipeline_consumed",
                    audience="god_view",
                    payload={
                        "pipeline_id": pre_exile_pipeline.pipeline_id,
                        "pipeline_run_id": pre_exile_pipeline.run_id,
                        "phase_id": pre_exile_pipeline.phase_id,
                        "round_no": pre_exile_pipeline.round_no,
                        "state": "consumed",
                        "vote_batch_id": batch_id,
                        "vote_decision_context_sha256": (
                            pre_exile_pipeline.vote_decision_context_sha256
                        ),
                        "committed_vote_count": len(pre_exile_results),
                        "committed_result_count": len(pre_exile_all_results),
                        "commit_mode": "durable_atomic_arbiter",
                    },
                )

    def record_private_round_memories(
        self,
        *,
        game_id: str,
        run_id: str,
        phase_id: str,
        phase_state: str,
        round_no: int,
        batch_id: str,
        source_cutoff_record_seq: int,
        commits: tuple[PrivateRoundMemoryCommit, ...],
        batch_completed_payload: dict[str, Any] | None = None,
    ) -> list[tuple[str, bool]]:
        commit_indexes = tuple(commit.commit_index for commit in commits)
        if (
            any(index <= 0 for index in commit_indexes)
            or commit_indexes != tuple(sorted(set(commit_indexes)))
        ):
            raise RepositoryError("private round memory commit order is invalid")
        if len({commit.player_id for commit in commits}) != len(commits):
            raise RepositoryError("private round memory owners are duplicated")
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            _raise_if_stop_requested(db, game)
            match = _match(db, game)
            if (
                match.round_no != round_no
                or not game.phase_id.startswith("day_")
                or game.current_run_id != run_id
                or game.phase_id != phase_id
                or game.phase_state != phase_state
            ):
                raise RepositoryError("private round memory phase changed before commit")
            terminal = _private_round_memory_batch_terminal_event(
                db,
                game_id=game_id,
                run_id=game.current_run_id,
                batch_id=batch_id,
            )
            existing_rows = list(
                db.scalars(
                    select(KnowledgeFact).where(
                        KnowledgeFact.game_id == game_id,
                        KnowledgeFact.owner_scope == "player",
                        KnowledgeFact.fact_type == "private_round_memory",
                    )
                )
            )
            if source_cutoff_record_seq <= 0 or source_cutoff_record_seq > game.last_record_seq:
                raise RepositoryError("private round memory cutoff is invalid")
            rows_by_owner: dict[str, list[KnowledgeFact]] = {}
            for row in existing_rows:
                rows_by_owner.setdefault(row.owner_id, []).append(row)
            prepared: list[
                tuple[
                    PrivateRoundMemoryCommit,
                    str,
                    str,
                    KnowledgeFact | None,
                ]
            ] = []
            for commit in commits:
                normalized_memory = commit.memory.strip()
                if not normalized_memory:
                    raise RepositoryError("private round memory cannot be empty")
                player = db.get(PlayerState, (game_id, commit.player_id))
                if player is None or not player.alive:
                    raise RepositoryError("private round memory owner must be alive")
                owner_rows = rows_by_owner.get(commit.player_id, [])
                latest = max(owner_rows, key=_private_round_memory_order, default=None)
                latest_id = latest.knowledge_fact_id if latest is not None else None
                latest_payload = latest.payload if latest is not None else {}
                latest_round = (
                    _positive_int(latest_payload.get("round_no"))
                    if isinstance(latest_payload, dict)
                    else None
                )
                latest_cutoff = (
                    _positive_int(latest_payload.get("source_cutoff_record_seq"))
                    if isinstance(latest_payload, dict)
                    else None
                )
                source_refs = list(commit.source_refs)
                if (
                    not source_refs
                    or any(not isinstance(item, str) or not item for item in source_refs)
                    or len(source_refs) != len(set(source_refs))
                ):
                    raise RepositoryError("private round memory source refs are invalid")
                expected_hash = private_round_memory_source_refs_sha256(
                    owner_id=commit.player_id,
                    round_no=round_no,
                    previous_snapshot_fact_id=commit.previous_snapshot_fact_id,
                    source_cutoff_record_seq=source_cutoff_record_seq,
                    source_refs=source_refs,
                )
                if commit.source_refs_sha256 != expected_hash:
                    raise RepositoryError("private round memory source hash is invalid")
                expected_source_refs = _private_round_memory_source_refs(
                    db,
                    game_id=game_id,
                    owner_id=commit.player_id,
                    source_cutoff_record_seq=source_cutoff_record_seq,
                    previous_snapshot_fact_id=commit.previous_snapshot_fact_id,
                )
                if source_refs != expected_source_refs:
                    raise RepositoryError("private round memory source refs do not match facts")
                _validate_private_round_memory_model_lineage(
                    db,
                    game=game,
                    commit=commit,
                    batch_id=batch_id,
                    phase_id=game.phase_id,
                    phase_state=game.phase_state,
                    round_no=round_no,
                    source_cutoff_record_seq=source_cutoff_record_seq,
                    normalized_memory=normalized_memory,
                )
                existing = next(
                    (
                        row
                        for row in owner_rows
                        if isinstance(row.payload, dict)
                        and row.payload.get("round_no") == round_no
                    ),
                    None,
                )
                if existing is not None:
                    payload = existing.payload if isinstance(existing.payload, dict) else {}
                    memory_sha256 = hashlib.sha256(normalized_memory.encode("utf-8")).hexdigest()
                    if any(
                        (
                            payload.get("batch_id") != batch_id,
                            payload.get("previous_snapshot_fact_id")
                            != commit.previous_snapshot_fact_id,
                            payload.get("source_cutoff_record_seq")
                            != source_cutoff_record_seq,
                            payload.get("source_refs") != source_refs,
                            payload.get("source_refs_sha256") != commit.source_refs_sha256,
                            payload.get("memory_sha256") != memory_sha256,
                            payload.get("source_action_id") != commit.action_id,
                            payload.get("source_model_response_record_seq")
                            != commit.model_response_record_seq,
                            payload.get("source_terminal_event_record_seq")
                            != commit.terminal_event_record_seq,
                            payload.get("provider_request_id") != commit.provider_request_id,
                            payload.get("source_attempt_id") != commit.attempt_id,
                            payload.get("source_request_payload_sha256")
                            != commit.request_payload_sha256,
                            payload.get("source_projected_context_sha256")
                            != commit.projected_context_sha256,
                            payload.get("projected_known_event_refs")
                            != list(commit.projected_known_event_refs),
                            payload.get("projected_known_events_sha256")
                            != commit.projected_known_events_sha256,
                        )
                    ):
                        raise RepositoryError("private round memory retry changed frozen input")
                    prepared.append((commit, normalized_memory, memory_sha256, existing))
                    continue
                if latest_id != commit.previous_snapshot_fact_id:
                    raise RepositoryError("private round memory predecessor changed before commit")
                if latest_round is not None and latest_round >= round_no:
                    raise RepositoryError("private round memory round is not monotonic")
                if latest_cutoff is not None and source_cutoff_record_seq <= latest_cutoff:
                    raise RepositoryError("private round memory cutoff is not monotonic")
                prepared.append(
                    (
                        commit,
                        normalized_memory,
                        hashlib.sha256(normalized_memory.encode("utf-8")).hexdigest(),
                        None,
                    )
                )

            if terminal is not None:
                if any(existing is None for _commit, _memory, _hash, existing in prepared):
                    raise RepositoryError(
                        "private round memory terminal exists without committed facts"
                    )
                results = [
                    (existing.knowledge_fact_id, False)
                    for _commit, _memory, _hash, existing in prepared
                    if existing is not None
                ]
                terminal_payload = terminal.payload if isinstance(terminal.payload, dict) else {}
                if terminal_payload.get("public_summary_status") != "completed":
                    raise RepositoryError("private round memory batch already failed")
                if batch_completed_payload is not None:
                    expected_keys = (
                        "round_no",
                        "batch_id",
                        "phase_id",
                        "phase_state",
                        "source_cutoff_record_seq",
                        "public_summary_status",
                        "commit_order",
                        "private_round_memory_mode",
                    )
                    if any(
                        terminal_payload.get(key) != batch_completed_payload.get(key)
                        for key in expected_keys
                    ):
                        raise RepositoryError(
                            "private round memory retry changed terminal input"
                        )
                    expected_failed = {
                        item.get("player_id")
                        for item in batch_completed_payload.get("memories", [])
                        if isinstance(item, dict)
                        and item.get("status") == "generation_failed"
                    }
                    terminal_by_owner = {
                        item.get("player_id"): item
                        for item in terminal_payload.get("memories", [])
                        if isinstance(item, dict) and isinstance(item.get("player_id"), str)
                    }
                    terminal_failed = {
                        player_id
                        for player_id, item in terminal_by_owner.items()
                        if item.get("status") == "generation_failed"
                    }
                    if expected_failed != terminal_failed or any(
                        terminal_by_owner.get(commit.player_id, {}).get("knowledge_fact_id")
                        != fact_id
                        for commit, (fact_id, _created) in zip(
                            commits, results, strict=True
                        )
                    ):
                        raise RepositoryError(
                            "private round memory retry changed terminal results"
                        )
                return results

            results: list[tuple[str, bool]] = []
            for commit, normalized_memory, memory_sha256, existing in prepared:
                if existing is not None:
                    results.append((existing.knowledge_fact_id, False))
                    continue
                fact_id = f"v2_fact_{uuid4().hex[:16]}"
                source_refs = list(commit.source_refs)
                payload = {
                    "schema_version": 2,
                    "owner": {"scope": "player", "id": commit.player_id},
                    "round_no": round_no,
                    "memory": normalized_memory,
                    "epistemic_status": "actor_subjective_memory",
                    "batch_id": batch_id,
                    "previous_snapshot_fact_id": commit.previous_snapshot_fact_id,
                    "supersedes_fact_id": commit.previous_snapshot_fact_id,
                    "source_cutoff_record_seq": source_cutoff_record_seq,
                    "source_refs": source_refs,
                    "source_refs_sha256": commit.source_refs_sha256,
                    "memory_sha256": memory_sha256,
                    "source_action_id": commit.action_id,
                    "source_model_response_record_seq": commit.model_response_record_seq,
                    "source_terminal_event_record_seq": commit.terminal_event_record_seq,
                    "provider_request_id": commit.provider_request_id,
                    "source_attempt_id": commit.attempt_id,
                    "source_request_payload_sha256": commit.request_payload_sha256,
                    "source_projected_context_sha256": commit.projected_context_sha256,
                    "projected_known_event_refs": list(commit.projected_known_event_refs),
                    "projected_known_events_sha256": (
                        commit.projected_known_events_sha256
                    ),
                }
                db.add(
                    KnowledgeFact(
                        knowledge_fact_id=fact_id,
                        game_id=game_id,
                        source_activation_id=None,
                        owner_scope="player",
                        owner_id=commit.player_id,
                        fact_type="private_round_memory",
                        payload=payload,
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
                        "owner_id": commit.player_id,
                        "fact_type": "private_round_memory",
                        "round_no": round_no,
                        "batch_id": batch_id,
                        "commit_index": commit.commit_index,
                        **payload,
                    },
                )
                results.append((fact_id, True))
            if batch_completed_payload is not None:
                completed_payload = dict(batch_completed_payload)
                status_by_owner = {
                    str(item.get("player_id")): dict(item)
                    for item in completed_payload.get("memories", [])
                    if isinstance(item, dict) and isinstance(item.get("player_id"), str)
                }
                for commit, (fact_id, created) in zip(commits, results, strict=True):
                    status_by_owner[commit.player_id] = {
                        "player_id": commit.player_id,
                        "status": "committed" if created else "reused",
                        "knowledge_fact_id": fact_id,
                    }
                commit_order = completed_payload.get("commit_order")
                if isinstance(commit_order, list):
                    completed_payload["memories"] = [
                        status_by_owner[player_id]
                        for player_id in commit_order
                        if isinstance(player_id, str) and player_id in status_by_owner
                    ]
                _append_event(
                    db,
                    game=game,
                    event_type="day_private_memory_batch_completed",
                    audience="god_view",
                    payload=completed_payload,
                )
            return results

    def append_event(
        self,
        *,
        game_id: str,
        event_type: str,
        audience: str,
        payload: dict[str, Any],
    ) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            _raise_if_stop_requested(db, game)
            _append_event(
                db,
                game=game,
                event_type=event_type,
                audience=audience,
                payload=payload,
            )

    def record_phase_state(self, *, game_id: str, previous_phase_state: str) -> PhaseTransition:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            _raise_if_stop_requested(db, game)
            transition = PhaseTransition(
                game_id=game.game_id,
                run_id=game.current_run_id,
                phase_seq=game.phase_seq,
                previous_phase_id=game.phase_id,
                phase_id=game.phase_id,
                phase_state=game.phase_state,
                reveal_presentation_seq=game.last_presentation_seq,
            )
            _append_event(
                db,
                game=game,
                event_type="game_phase_changed",
                audience="all",
                payload={
                    "phase_seq": game.phase_seq,
                    "previous_phase_id": game.phase_id,
                    "previous_phase_state": previous_phase_state,
                    "phase_id": game.phase_id,
                    "phase_state": game.phase_state,
                    "reveal_presentation_seq": game.last_presentation_seq,
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
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            _raise_if_stop_requested(db, game)
            match = _match(db, game)
            if player_id is not None:
                target = db.get(PlayerState, (game_id, player_id))
                if target is None or not target.alive:
                    raise RepositoryError("sheriff target must be alive")
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
                audience="all",
                payload={
                    "player_id": player_id,
                    "from_player_id": previous_sheriff_id,
                    "reason": reason,
                },
            )

    def record_pre_sheriff_explosion(self, *, game_id: str, player_id: str) -> str:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            _raise_if_stop_requested(db, game)
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
                audience="all",
                payload={
                    "round_no": match.round_no,
                    "player_id": player_id,
                    "stage": "pre_sheriff_election",
                    "count": match.pre_sheriff_explosion_count,
                    "outcome": outcome,
                },
            )
            return outcome

    def record_day_explosion(self, *, game_id: str, player_id: str, stage: str) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            _raise_if_stop_requested(db, game)
            match = _match(db, game)
            _kill(db, game=game, player_id=player_id, cause="werewolf_self_explosion")
            _append_event(
                db,
                game=game,
                event_type="werewolf_self_exploded",
                audience="all",
                payload={
                    "round_no": match.round_no,
                    "player_id": player_id,
                    "stage": stage,
                    "outcome": "day_ended",
                },
            )

    def resolve_pre_exile_self_explosions(
        self,
        *,
        game_id: str,
        pipeline_id: str,
        expected_wolf_ids: tuple[str, ...],
        stage: str = "before_exile_vote",
    ) -> PreExileExplosionCommit:
        """Resolve the arbiter and mutate an explosion in one transaction."""

        from app.match.pre_exile_pipeline_repository import (  # avoids module cycle
            _terminalize_result_actions,
            _validate_predecessor_closed,
        )

        if (
            not expected_wolf_ids
            or len(set(expected_wolf_ids)) != len(expected_wolf_ids)
            or any(
                not isinstance(player_id, str) or not player_id for player_id in expected_wolf_ids
            )
        ):
            raise RepositoryError("invalid expected pre-exile wolves")
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            _raise_if_stop_requested(db, game)
            run = _run(db, game.current_run_id)
            match = _match(db, game)
            pipeline = db.scalar(
                select(PreExilePipeline)
                .where(PreExilePipeline.pipeline_id == pipeline_id)
                .with_for_update()
            )
            if (
                pipeline is None
                or pipeline.game_id != game.game_id
                or pipeline.run_id != game.current_run_id
                or pipeline.fence_worker_id != run.worker_id
                or pipeline.fence_token != run.fence_token
                or pipeline.phase_id != game.phase_id
                or pipeline.round_no != match.round_no
            ):
                raise RepositoryError("pre-exile self-explosion gate changed")
            self_results = list(
                db.scalars(
                    select(PreExileResult)
                    .where(
                        PreExileResult.pipeline_id == pipeline.pipeline_id,
                        PreExileResult.result_kind == "self_explosion",
                    )
                    .with_for_update()
                )
            )
            by_actor = {row.actor_player_id: row for row in self_results}
            if set(by_actor) != set(expected_wolf_ids):
                raise RepositoryError("pre-exile self-explosion batch is incomplete")
            failed = tuple(
                player_id
                for player_id in expected_wolf_ids
                if by_actor[player_id].failure is not None
            )
            if pipeline.state in {
                "no_explosion",
                "votes_accepted",
                "consumed",
                "explosion_selected",
            }:
                if any(row.state != "committed" for row in self_results):
                    raise RepositoryError(
                        "resolved pre-exile self-explosion result is nonterminal"
                    )
                selected = pipeline.selected_explosion_player_id
                return PreExileExplosionCommit(
                    outcome=("explosion_selected" if selected is not None else "no_explosion"),
                    selected_player_id=selected,
                    failed_player_ids=failed,
                )
            if pipeline.state != "collecting":
                raise RepositoryError(f"cannot resolve pre-exile pipeline from {pipeline.state}")
            if any(row.state not in {"ready", "failed"} for row in self_results):
                raise RepositoryError("pre-exile self-explosion batch is incomplete")
            if any(
                not isinstance(row.private_fact_id, str)
                or not row.private_fact_id
                or type(row.private_fact_record_seq) is not int
                for row in self_results
            ):
                raise RepositoryError("pre-exile self-explosion private fact is incomplete")
            for row in self_results:
                _validate_pre_exile_self_fact_lineage(
                    db,
                    pipeline=pipeline,
                    result=row,
                )
            predecessor_closed_record_seq = _validate_predecessor_closed(
                db,
                pipeline=pipeline,
            )
            _validate_pre_exile_predecessor_canonical_commit(
                db,
                pipeline=pipeline,
                predecessor_closed_record_seq=predecessor_closed_record_seq,
            )
            wolf_rows = list(
                db.execute(
                    select(
                        RoleAssignment.player_id,
                        RoleAssignment.seat,
                        PlayerState.alive,
                    )
                    .join(
                        PlayerState,
                        (PlayerState.game_id == RoleAssignment.game_id)
                        & (PlayerState.player_id == RoleAssignment.player_id),
                    )
                    .where(
                        RoleAssignment.game_id == game.game_id,
                        RoleAssignment.role_key == "werewolf",
                    )
                )
            )
            alive_wolves = {player_id: seat for player_id, seat, alive in wolf_rows if alive}
            if set(alive_wolves) != set(expected_wolf_ids):
                raise RepositoryError("pre-exile wolf roster changed")
            affirmative = sorted(
                (
                    player_id
                    for player_id in expected_wolf_ids
                    if bool((by_actor[player_id].decision or {}).get("explode"))
                ),
                key=lambda player_id: alive_wolves[player_id],
            )
            resolved_at = _now()
            pipeline.explosion_resolved_at = resolved_at
            if affirmative:
                selected = affirmative[0]
                existing_vote_event = db.scalar(
                    select(GameRecordEvent).where(
                        GameRecordEvent.game_id == game.game_id,
                        GameRecordEvent.run_id == game.current_run_id,
                        GameRecordEvent.record_seq > pipeline.predecessor_sealed_record_seq,
                        GameRecordEvent.event_type.in_(
                            ("day_vote_committed", "day_vote_resolved")
                        ),
                    )
                )
                if existing_vote_event is not None:
                    raise RepositoryError("cannot resolve explosion after public vote commit")
                vote_results = list(
                    db.scalars(
                        select(PreExileResult)
                        .where(
                            PreExileResult.pipeline_id == pipeline.pipeline_id,
                            PreExileResult.result_kind == "exile_vote",
                        )
                        .with_for_update()
                    )
                )
                _terminalize_result_actions(
                    db,
                    game=game,
                    pipeline=pipeline,
                    rows=vote_results,
                    failure_code="pre_exile_vote_discarded_by_self_explosion",
                    failure_stage="self_explosion_resolved",
                    failure_episode_disposition="isolated_action_failure",
                )
                for result in vote_results:
                    result.state = "discarded"
                    result.terminal_at = resolved_at
                _kill(
                    db,
                    game=game,
                    player_id=selected,
                    cause="werewolf_self_explosion",
                )
                _append_event(
                    db,
                    game=game,
                    event_type="werewolf_self_exploded",
                    audience="all",
                    payload={
                        "round_no": match.round_no,
                        "player_id": selected,
                        "stage": stage,
                        "outcome": "day_ended",
                        "pipeline_id": pipeline.pipeline_id,
                    },
                )
                pipeline.state = "explosion_selected"
                pipeline.selected_explosion_player_id = selected
                pipeline.terminal_at = resolved_at
                outcome: Literal["no_explosion", "explosion_selected"] = "explosion_selected"
            else:
                selected = None
                pipeline.state = "no_explosion"
                outcome = "no_explosion"
            for result in self_results:
                result.state = "committed"
                result.terminal_at = resolved_at
                _append_event(
                    db,
                    game=game,
                    event_type="pre_exile_private_fact_committed",
                    audience="god_view",
                    payload={
                        "pipeline_id": pipeline.pipeline_id,
                        "result_id": result.result_id,
                        "actor_player_id": result.actor_player_id,
                        "knowledge_fact_id": result.private_fact_id,
                        "provisional_record_seq": result.private_fact_record_seq,
                        "visibility_mode": "committed_after_atomic_arbiter",
                    },
                )
            _append_event(
                db,
                game=game,
                event_type="pre_exile_self_explosions_resolved",
                audience="god_view",
                payload={
                    "pipeline_id": pipeline.pipeline_id,
                    "pipeline_run_id": pipeline.run_id,
                    "phase_id": pipeline.phase_id,
                    "round_no": pipeline.round_no,
                    "state": pipeline.state,
                    "eligible_count": len(expected_wolf_ids),
                    "completed_count": len(expected_wolf_ids) - len(failed),
                    "failed_count": len(failed),
                    "affirmative_count": len(affirmative),
                    "committed_self_result_count": len(self_results),
                    "selected_player_id": selected,
                    "selection_policy": "lowest_seat_affirmative",
                    "outcome": outcome,
                    "commit_mode": "durable_atomic_arbiter",
                },
            )
            return PreExileExplosionCommit(
                outcome=outcome,
                selected_player_id=selected,
                failed_player_ids=failed,
            )

    def resolve_exile(self, *, game_id: str, player_id: str) -> ExileResult:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            _raise_if_stop_requested(db, game)
            match = _match(db, game)
            assignment = db.scalar(
                select(RoleAssignment).where(
                    RoleAssignment.game_id == game_id,
                    RoleAssignment.player_id == player_id,
                )
            )
            state = db.get(PlayerState, (game_id, player_id))
            if assignment is None or state is None or not state.alive:
                raise RepositoryError("exile target must be alive")
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
                    audience="all",
                    payload={
                        "round_no": match.round_no,
                        "player_id": player_id,
                        "survived": True,
                    },
                )
            else:
                _kill(db, game=game, player_id=player_id, cause="exile")
                outcome = "eliminated"
                _append_event(
                    db,
                    game=game,
                    event_type="player_exiled",
                    audience="all",
                    payload={"round_no": match.round_no, "player_id": player_id},
                )
            return ExileResult(
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
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            _raise_if_stop_requested(db, game)
            match = _match(db, game)
            hunter = db.get(PlayerState, (game_id, hunter_id))
            if hunter is None or hunter.alive or hunter.death_cause == "witch_poison":
                raise RepositoryError("hunter response is not eligible")
            hunter_state = dict(hunter.state or {})
            if hunter_state.get("hunter_response_resolved"):
                raise RepositoryError("hunter response already resolved")
            hunter_state["hunter_response_resolved"] = True
            hunter.state = hunter_state
            if target_player_id is not None:
                _kill(db, game=game, player_id=target_player_id, cause="hunter_shot")
            knowledge_fact_id = f"v2_fact_{uuid4().hex[:16]}"
            db.add(
                KnowledgeFact(
                    knowledge_fact_id=knowledge_fact_id,
                    game_id=game_id,
                    source_activation_id=None,
                    owner_scope="player",
                    owner_id=hunter_id,
                    fact_type="private_ability_action_committed",
                    payload={
                        "ability_id": "hunter.death_shot",
                        "round_no": match.round_no,
                        "decision": {"target_player_id": target_player_id},
                        "result": {"shot_used": target_player_id is not None},
                        "resolution_scope": (
                            "法官已接受本次私有动作；猎人已明确知道自己的"
                            "开枪或放弃决定，公开结果由法官另行播报。"
                        ),
                    },
                )
            )
            _append_event(
                db,
                game=game,
                event_type="hunter_response_resolved",
                audience="all",
                payload={
                    "round_no": match.round_no,
                    "period": "day",
                    "hunter_player_id": hunter_id,
                    "target_player_id": target_player_id,
                    "knowledge_fact_id": knowledge_fact_id,
                },
            )

    def pending_hunters(self, game_id: str) -> tuple[str, ...]:
        with self._session_factory() as db:
            rows = list(
                db.execute(
                    select(
                        RoleAssignment.player_id, PlayerState.death_cause, PlayerState.state
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

    def finish_day(self, *, game_id: str, reason: str) -> PhaseTransition:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            _raise_if_stop_requested(db, game)
            open_slot_id = db.scalar(
                select(DaySpeechSlot.slot_id)
                .where(
                    DaySpeechSlot.game_id == game.game_id,
                    DaySpeechSlot.run_id == game.current_run_id,
                    DaySpeechSlot.state.in_(_NONTERMINAL_DAY_SPEECH_SLOT_STATES),
                )
                .order_by(DaySpeechSlot.slot_id)
                .limit(1)
                .with_for_update()
            )
            if open_slot_id is not None:
                raise RepositoryError("cannot finish day with a nonterminal day speech slot")
            open_pre_exile_pipeline_id = db.scalar(
                select(PreExilePipeline.pipeline_id)
                .where(
                    PreExilePipeline.game_id == game.game_id,
                    PreExilePipeline.run_id == game.current_run_id,
                    PreExilePipeline.state.in_(_NONTERMINAL_PRE_EXILE_PIPELINE_STATES),
                )
                .order_by(PreExilePipeline.pipeline_id)
                .limit(1)
                .with_for_update()
            )
            if open_pre_exile_pipeline_id is not None:
                raise RepositoryError("cannot finish day with a nonterminal pre-exile pipeline")
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
                    audience="all",
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
                failed_failure_episode_ids = _open_failure_episode_ids_for_locked_run(
                    db,
                    game=game,
                )
                _append_event(
                    db,
                    game=game,
                    event_type="match_runtime_failed",
                    audience="god_view",
                    payload={
                        "reason": "max_rounds_exceeded",
                        "round_no": match.round_no,
                        "failed_failure_episode_ids": list(failed_failure_episode_ids),
                        "failure_episode_disposition": "run_failure",
                    },
                )
            else:
                match.round_no += 1
                game.phase_id = f"night_{match.round_no}"
                game.phase_state = "nightfall_ready"
                game.status = "ready"
                _run(db, game.current_run_id).status = "ready"
            transition = PhaseTransition(
                game_id=game.game_id,
                run_id=game.current_run_id,
                phase_seq=game.phase_seq,
                previous_phase_id=previous_phase_id,
                phase_id=game.phase_id,
                phase_state=game.phase_state,
                reveal_presentation_seq=game.last_presentation_seq,
            )
            _append_event(
                db,
                game=game,
                event_type="game_phase_changed",
                audience="all",
                payload={
                    "phase_seq": transition.phase_seq,
                    "previous_phase_id": transition.previous_phase_id,
                    "phase_id": transition.phase_id,
                    "phase_state": transition.phase_state,
                    "reason": reason,
                    "reveal_presentation_seq": transition.reveal_presentation_seq,
                },
            )
            return transition

    def current_winner(self, game_id: str) -> str | None:
        with self._session_factory() as db:
            game = db.get(GameRecord, game_id)
            if game is None:
                raise RepositoryError(f"unknown game {game_id}")
            return _winner(db, game)

    def fail_runtime(self, *, game_id: str, failure_code: str) -> str:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            _raise_if_stop_requested(db, game)
            run = _run(db, game.current_run_id)
            failed_at = _now()
            invalidated_slots = list(
                db.scalars(
                    select(DaySpeechSlot)
                    .where(
                        DaySpeechSlot.game_id == game.game_id,
                        DaySpeechSlot.run_id == run.run_id,
                        DaySpeechSlot.state.in_(_NONTERMINAL_DAY_SPEECH_SLOT_STATES),
                    )
                    .order_by(DaySpeechSlot.slot_id)
                    .with_for_update()
                )
            )
            for slot in invalidated_slots:
                slot.state = "invalidated"
                slot.failure = {
                    "kind": "runtime_failed",
                    "reason_code": "day_runtime_failed",
                    "failure_code": failure_code,
                }
                slot.terminal_at = failed_at
                _append_event(
                    db,
                    game=game,
                    event_type="day_speech_slot_invalidated",
                    audience="god_view",
                    payload={
                        "slot_id": slot.slot_id,
                        "slot_run_id": slot.run_id,
                        "phase_id": slot.phase_id,
                        "round_no": slot.round_no,
                        "speech_round": slot.speech_round,
                        "turn_index": slot.turn_index,
                        "actor_player_id": slot.actor_player_id,
                        "state": slot.state,
                        "failure_kind": "runtime_failed",
                        "reason_code": "day_runtime_failed",
                        "failure_code": failure_code,
                    },
                )
            invalidated_pre_exile_pipelines = list(
                db.scalars(
                    select(PreExilePipeline)
                    .where(
                        PreExilePipeline.game_id == game.game_id,
                        PreExilePipeline.run_id == run.run_id,
                        PreExilePipeline.state.in_(_NONTERMINAL_PRE_EXILE_PIPELINE_STATES),
                    )
                    .order_by(PreExilePipeline.pipeline_id)
                    .with_for_update()
                )
            )
            invalidated_pre_exile_result_count = 0
            if invalidated_pre_exile_pipelines:
                from app.match.pre_exile_pipeline_repository import (
                    _terminalize_result_actions,
                )

                for pipeline in invalidated_pre_exile_pipelines:
                    results = list(
                        db.scalars(
                            select(PreExileResult)
                            .where(PreExileResult.pipeline_id == pipeline.pipeline_id)
                            .with_for_update()
                        )
                    )
                    invalidated_pre_exile_result_count += len(results)
                    _terminalize_result_actions(
                        db,
                        game=game,
                        pipeline=pipeline,
                        rows=results,
                        failure_code="pre_exile_pipeline_invalidated",
                        failure_stage="day_runtime_failed",
                    )
                    for result in results:
                        if result.state not in {"committed", "discarded"}:
                            result.state = "discarded"
                            result.terminal_at = failed_at
                    pipeline.state = "invalidated"
                    pipeline.failure = {
                        "kind": "runtime_failed",
                        "reason_code": "day_runtime_failed",
                        "failure_code": failure_code,
                    }
                    pipeline.terminal_at = failed_at
                    _append_event(
                        db,
                        game=game,
                        event_type="pre_exile_pipeline_invalidated",
                        audience="god_view",
                        payload={
                            "pipeline_id": pipeline.pipeline_id,
                            "pipeline_run_id": pipeline.run_id,
                            "phase_id": pipeline.phase_id,
                            "round_no": pipeline.round_no,
                            "state": pipeline.state,
                            "failure_kind": "runtime_failed",
                            "reason_code": "day_runtime_failed",
                            "failure_code": failure_code,
                            "discarded_result_count": len(results),
                        },
                    )
            game.status = "failed"
            game.phase_state = "failed"
            run.status = "failed"
            run.completed_at = failed_at
            match = db.get(MatchState, game_id)
            if match is not None:
                match.completion_reason = failure_code
            # The session factory disables autoflush. Make the synthetic attempt/action
            # terminals visible before deriving the run-level failure episode set.
            db.flush()
            failed_failure_episode_ids = _open_failure_episode_ids_for_locked_run(
                db,
                game=game,
            )
            _append_event(
                db,
                game=game,
                event_type="day_runtime_failed",
                audience="god_view",
                payload={
                    "failure_code": failure_code,
                    "invalidated_day_speech_slot_count": len(invalidated_slots),
                    "invalidated_pre_exile_pipeline_count": len(invalidated_pre_exile_pipelines),
                    "invalidated_pre_exile_result_count": (invalidated_pre_exile_result_count),
                    "failed_failure_episode_ids": list(failed_failure_episode_ids),
                    "failure_episode_disposition": "run_failure",
                },
            )
            return run.run_id

    def _ensure_state(self, game_id: str) -> None:
        with self._session_factory.begin() as db:
            game = _locked_game(db, game_id, require_fence=self._enforce_execution_fence)
            if db.get(MatchState, game_id) is not None:
                return
            rule = game.rule_snapshot.get("rule_set")
            if not isinstance(rule, dict):
                raise RepositoryError("V2 match has no frozen rule")
            db.add(
                MatchState(
                    game_id=game_id,
                    round_no=_round_no(game.phase_id),
                    sheriff_badge_state=(
                        "pending" if bool(rule.get("sheriff_enabled")) else "disabled"
                    ),
                )
            )


def _players(db: Session, game: GameRecord) -> tuple[MatchPlayer, ...]:
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
    players: list[MatchPlayer] = []
    for assignment in assignments:
        state = db.get(PlayerState, (game.game_id, assignment.player_id))
        if state is None:
            raise RepositoryError("player state is incomplete")
        profile = profiles.get(assignment.player_id, {})
        try:
            frozen_model = frozen_player_model_configuration(profile)
        except FrozenModelParametersError as exc:
            raise RepositoryError("invalid frozen player model configuration") from exc
        players.append(
            MatchPlayer(
                player_id=assignment.player_id,
                seat=assignment.seat,
                display_name=str(profile.get("name") or f"{assignment.seat}号玩家"),
                role_key=assignment.role_key,
                team="werewolves" if assignment.role_key == "werewolf" else "villagers",
                alive=state.alive,
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
                state=dict(state.state or {}),
            )
        )
    return tuple(players)


_PUBLIC_HISTORY_TYPES = {
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


def _match_snapshot(
    db: Session,
    *,
    game: GameRecord,
    match: MatchState,
    public_history: tuple[dict[str, Any], ...],
    last_record_seq: int | None = None,
) -> MatchSnapshot:
    rule = game.rule_snapshot.get("rule_set")
    if not isinstance(rule, dict):
        raise RepositoryError("V2 match has no frozen rule")
    compiled_rule = dict(rule)
    compiled_rule["day_actions"] = list(game.ability_snapshot.get("day_actions") or [])
    compiled_rule["ability_policies"] = dict(game.ability_snapshot.get("policies") or {})
    for key, value in dict(game.ability_snapshot.get("day_policies") or {}).items():
        compiled_rule.setdefault(key, value)
    return MatchSnapshot(
        game_id=game.game_id,
        run_id=game.current_run_id,
        last_record_seq=(game.last_record_seq if last_record_seq is None else last_record_seq),
        phase_id=game.phase_id,
        phase_state=game.phase_state,
        round_no=match.round_no,
        sheriff_player_id=match.sheriff_player_id,
        sheriff_badge_state=match.sheriff_badge_state,
        pre_sheriff_explosion_count=match.pre_sheriff_explosion_count,
        rule=compiled_rule,
        max_rounds=int(game.rule_snapshot.get("max_rounds") or 8),
        model_context_contract=(frozen_model_context_contract(game.rule_snapshot) or {}),
        model_generation_policy_contract=(
            resolve_model_generation_policy_contract(game.rule_snapshot)
        ),
        day_speech_pipeline_contract=resolve_day_speech_pipeline_contract(game.rule_snapshot),
        pre_exile_pipeline_contract=resolve_pre_exile_pipeline_contract(game.rule_snapshot),
        audio_mode=delivery_audio_mode(game.delivery_snapshot),
        players=_players(db, game),
        public_history=public_history,
        last_presentation_seq=game.last_presentation_seq,
    )


def _public_history(
    db: Session,
    game_id: str,
    *,
    at_or_before_record_seq: int | None = None,
) -> tuple[dict[str, Any], ...]:
    event_conditions = [
        GameRecordEvent.game_id == game_id,
        GameRecordEvent.event_type.in_(_PUBLIC_HISTORY_TYPES),
    ]
    if at_or_before_record_seq is not None:
        event_conditions.append(GameRecordEvent.record_seq <= at_or_before_record_seq)
    rows = list(
        db.scalars(
            select(GameRecordEvent)
            .where(*event_conditions)
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
    presentation_conditions = [
        LivePresentation.game_id == game_id,
        LivePresentation.actor_kind == "player",
        LivePresentation.audience == "all",
        LivePresentation.state == "closed",
    ]
    presentations = list(
        db.scalars(
            select(LivePresentation)
            .where(*presentation_conditions)
            .order_by(LivePresentation.source_event_id)
        )
    )
    source_events = {
        row.event_id: row
        for row in db.scalars(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == game_id,
                GameRecordEvent.event_id.in_({row.source_event_id for row in presentations}),
            )
        )
    }
    presentation_record_seq = {
        row.presentation_id: (
            source_events[row.source_event_id].record_seq
            if row.source_event_id in source_events
            else row.source_event_id
        )
        for row in presentations
    }
    if at_or_before_record_seq is not None:
        closed_event_seqs = {
            str(payload.get("presentation_id")): event.record_seq
            for event in db.scalars(
                select(GameRecordEvent).where(
                    GameRecordEvent.game_id == game_id,
                    GameRecordEvent.event_type.in_({"speech_closed", "presentation_closed"}),
                    GameRecordEvent.record_seq <= at_or_before_record_seq,
                )
            )
            for payload in (event.payload,)
            if isinstance(payload, dict) and isinstance(payload.get("presentation_id"), str)
        }
        presentations = [
            row
            for row in presentations
            if presentation_record_seq[row.presentation_id] <= at_or_before_record_seq
            and row.presentation_id in closed_event_seqs
        ]
    action_types = _action_types_by_id(
        db,
        game_id,
        at_or_before_record_seq=at_or_before_record_seq,
    )
    history.extend(
        {
            "source_event_id": row.source_event_id,
            "record_seq": presentation_record_seq[row.presentation_id],
            "event_type": "public_player_speech_presented",
            "payload": {
                "round_no": _round_no(row.phase_id),
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
    return tuple(history)


def _action_types_by_id(
    db: Session,
    game_id: str,
    *,
    at_or_before_record_seq: int | None = None,
) -> dict[str, str]:
    conditions = [
        GameRecordEvent.game_id == game_id,
        GameRecordEvent.event_type == "action_opened",
    ]
    if at_or_before_record_seq is not None:
        conditions.append(GameRecordEvent.record_seq <= at_or_before_record_seq)
    rows = list(db.scalars(select(GameRecordEvent).where(*conditions)))
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


def _kill(db: Session, *, game: GameRecord, player_id: str, cause: str) -> None:
    state = db.get(PlayerState, (game.game_id, player_id))
    if state is None or not state.alive:
        raise RepositoryError("death target must be alive")
    state.alive = False
    state.death_cause = cause
    state.death_window_seq = None


def _match(db: Session, game: GameRecord) -> MatchState:
    match = db.get(MatchState, game.game_id)
    if match is None:
        raise RepositoryError("V2 match state is missing")
    return match


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
    return game


def _run(db: Session, run_id: str) -> GameRun:
    run = db.get(GameRun, run_id)
    if run is None:
        raise RepositoryError(f"unknown run {run_id}")
    return run


def _normalized_decision_note(value: str | None) -> str:
    return value.strip() if isinstance(value, str) else ""


def _add_private_action_decision(
    db: Session,
    *,
    game: GameRecord,
    player_id: str,
    round_no: int,
    action_type: str,
    decision: dict[str, Any],
    decision_note: str | None,
    context: dict[str, Any] | None,
) -> str | None:
    normalized_note = _normalized_decision_note(decision_note)
    if not normalized_note:
        return None
    fact_id = f"v2_fact_{uuid4().hex[:16]}"
    db.add(
        KnowledgeFact(
            knowledge_fact_id=fact_id,
            game_id=game.game_id,
            source_activation_id=None,
            owner_scope="player",
            owner_id=player_id,
            fact_type="private_action_decision",
            payload={
                "schema_version": 1,
                "round_no": round_no,
                "action_type": action_type,
                "decision": {key: value for key, value in decision.items() if value is not None},
                "declared_reason": {
                    "text": normalized_note,
                    "epistemic_status": "actor_declared_reason",
                },
                **({"context": dict(context)} if context else {}),
            },
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
            "fact_type": "private_action_decision",
            "round_no": round_no,
            "action_type": action_type,
        },
    )
    return fact_id


def _validate_pre_exile_predecessor_canonical_commit(
    db: Session,
    *,
    pipeline: PreExilePipeline,
    predecessor_closed_record_seq: int,
) -> None:
    game = db.get(GameRecord, pipeline.game_id)
    presentation = db.scalar(
        select(LivePresentation).where(
            LivePresentation.game_id == pipeline.game_id,
            LivePresentation.presentation_id == pipeline.predecessor_presentation_id,
        )
    )
    opened = list(
        db.scalars(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == pipeline.game_id,
                GameRecordEvent.run_id == pipeline.run_id,
                GameRecordEvent.event_type == "action_opened",
            )
        )
    )
    matching_opened = [
        event
        for event in opened
        if isinstance(event.payload, dict)
        and event.payload.get("action_id") == pipeline.predecessor_action_id
    ]
    if presentation is None or len(matching_opened) != 1:
        raise RepositoryError("pre-exile predecessor canonical speech lineage is invalid")
    context = matching_opened[0].payload.get("context")
    if not isinstance(context, dict):
        raise RepositoryError("pre-exile predecessor canonical speech lineage is invalid")
    action_type = context.get("action_type")
    technical_skip = action_type == "judge_day_speech_technical_skip"
    speech_order = context.get("speech_order")
    final_speech_round = max(
        1,
        int(
            (
                ((game.rule_snapshot if game is not None else {}).get("rule_set") or {}).get(
                    "speech_rounds"
                )
            )
            or 1
        ),
    )
    turn_player_id = context.get("skipped_player_id") if technical_skip else presentation.actor_id
    if (
        presentation.run_id != pipeline.run_id
        or presentation.action_id != pipeline.predecessor_action_id
        or presentation.state != "closed"
        or presentation.closed_at is None
        or matching_opened[0].record_seq >= pipeline.predecessor_source_record_seq
        or predecessor_closed_record_seq <= pipeline.predecessor_sealed_record_seq
        or context.get("speech_round") != final_speech_round
        or not isinstance(speech_order, list)
        or speech_order[-1:] != [turn_player_id]
    ):
        raise RepositoryError("pre-exile predecessor canonical speech lineage is invalid")
    commits = list(
        db.scalars(
            select(GameRecordEvent)
            .where(
                GameRecordEvent.game_id == pipeline.game_id,
                GameRecordEvent.run_id == pipeline.run_id,
                GameRecordEvent.event_type == "day_speech_committed",
                GameRecordEvent.record_seq > pipeline.predecessor_sealed_record_seq,
            )
            .order_by(GameRecordEvent.record_seq)
        )
    )
    if technical_skip:
        public_skip_record_seq = context.get("public_skip_record_seq")
        public_skip = (
            db.scalar(
                select(GameRecordEvent).where(
                    GameRecordEvent.game_id == pipeline.game_id,
                    GameRecordEvent.run_id == pipeline.run_id,
                    GameRecordEvent.record_seq == public_skip_record_seq,
                    GameRecordEvent.event_type == "action_skipped_technical",
                )
            )
            if type(public_skip_record_seq) is int
            else None
        )
        public_skip_payload = (
            public_skip.payload
            if public_skip is not None and isinstance(public_skip.payload, dict)
            else {}
        )
        if (
            context.get("actor") != {"kind": "judge", "id": "judge"}
            or presentation.actor_kind != "judge"
            or presentation.actor_id != "judge"
            or type(public_skip_record_seq) is not int
            or public_skip_record_seq <= 0
            or public_skip_record_seq >= matching_opened[0].record_seq
            or public_skip_payload.get("audience") != "all"
            or public_skip_payload.get("phase_id") != pipeline.phase_id
            or public_skip_payload.get("round_no") != pipeline.round_no
            or public_skip_payload.get("action_type") != "day_debate_speech"
            or public_skip_payload.get("actor_id") != turn_player_id
            or public_skip_payload.get("reason") != "technical_failure"
            or commits
        ):
            raise RepositoryError("pre-exile technical-skip canonical predecessor changed")
        return
    expected_payload = canonical_event_payload(
        {
            "round_no": pipeline.round_no,
            "stage": "day_debate",
            "player_id": presentation.actor_id,
            "speech": presentation.subtitle_text,
        },
        audience="all",
    )
    if (
        action_type != "day_debate_speech"
        or context.get("actor") != {"kind": "player", "id": presentation.actor_id}
        or presentation.actor_kind != "player"
        or len(commits) != 1
        or commits[0].record_seq <= predecessor_closed_record_seq
        or commits[0].payload != expected_payload
    ):
        raise RepositoryError("pre-exile predecessor canonical day speech is not committed")


def _validate_pre_exile_self_fact_lineage(
    db: Session,
    *,
    pipeline: PreExilePipeline,
    result: PreExileResult,
) -> None:
    fact = db.get(KnowledgeFact, result.private_fact_id)
    payload = fact.payload if fact is not None and isinstance(fact.payload, dict) else {}
    fact_context = payload.get("context")
    decision = payload.get("decision")
    result_decision = result.decision or {}
    matching_events = [
        event
        for event in db.scalars(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == pipeline.game_id,
                GameRecordEvent.run_id == pipeline.run_id,
                GameRecordEvent.event_type == "private_knowledge_recorded",
            )
        )
        if isinstance(event.payload, dict)
        and event.payload.get("knowledge_fact_id") == result.private_fact_id
    ]
    if (
        fact is None
        or fact.game_id != pipeline.game_id
        or fact.owner_scope != "player"
        or fact.owner_id != result.actor_player_id
        or fact.fact_type != "private_action_decision"
        or payload.get("action_type") != "werewolf_self_explosion"
        or payload.get("source_action_id") != result.action_id
        or not isinstance(decision, dict)
        or not isinstance(decision.get("explode"), bool)
        or decision.get("explode") != result_decision.get("explode")
        or not isinstance(fact_context, dict)
        or fact_context.get("pipeline_id") != pipeline.pipeline_id
        or fact_context.get("public_history_cutoff_record_seq") != pipeline.public_cutoff_record_seq
        or fact_context.get("visibility_mode") != "pre_exile_provisional_until_atomic_arbiter"
        or len(matching_events) != 1
        or matching_events[0].record_seq != result.private_fact_record_seq
        or matching_events[0].event_id <= 0
        or matching_events[0].payload.get("pipeline_id") != pipeline.pipeline_id
        or matching_events[0].payload.get("pipeline_run_id") != pipeline.run_id
        or matching_events[0].payload.get("owner_scope") != "player"
        or matching_events[0].payload.get("owner_id") != result.actor_player_id
        or matching_events[0].payload.get("fact_type") != "private_action_decision"
        or matching_events[0].payload.get("action_type") != "werewolf_self_explosion"
        or matching_events[0].payload.get("source_action_id") != result.action_id
        or matching_events[0].payload.get("audience") != "god_view"
    ):
        raise RepositoryError("pre-exile self-explosion private fact lineage changed")


def _validate_pre_exile_vote_commit_gate(
    db: Session,
    *,
    game: GameRecord,
    match: MatchState,
    pipeline: PreExilePipeline,
    results: list[PreExileResult],
    self_results: list[PreExileResult],
    phase_id: str,
    phase_state: str,
    round_no: int,
    action_type: str,
    public_cutoff_record_seq: int,
    expected_voter_ids: tuple[str, ...],
    votes: tuple[DayVoteCommit, ...],
) -> None:
    run = _run(db, game.current_run_id)
    if (
        pipeline.game_id != game.game_id
        or pipeline.run_id != game.current_run_id
        or pipeline.fence_worker_id != run.worker_id
        or pipeline.fence_token != run.fence_token
        or pipeline.phase_id != phase_id
        or pipeline.round_no != round_no
        or pipeline.state != "no_explosion"
        or pipeline.selected_explosion_player_id is not None
        or match.round_no != round_no
        or game.phase_state != phase_state
        or action_type != "exile_vote"
        or pipeline.public_cutoff_record_seq != public_cutoff_record_seq
    ):
        raise RepositoryError("pre-exile vote commit gate changed")
    presentation = db.scalar(
        select(LivePresentation).where(
            LivePresentation.game_id == game.game_id,
            LivePresentation.presentation_id == pipeline.predecessor_presentation_id,
        )
    )
    if (
        presentation is None
        or presentation.run_id != pipeline.run_id
        or presentation.action_id != pipeline.predecessor_action_id
        or presentation.state != "closed"
        or presentation.closed_at is None
    ):
        raise RepositoryError("pre-exile votes cannot commit before predecessor close")
    if not self_results or any(
        result.state != "committed" or result.terminal_at is None for result in self_results
    ):
        raise RepositoryError("pre-exile self-explosion results are not atomically committed")
    closed_events = list(
        db.scalars(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == game.game_id,
                GameRecordEvent.run_id == pipeline.run_id,
                GameRecordEvent.event_type == "speech_closed",
                GameRecordEvent.record_seq > pipeline.predecessor_sealed_record_seq,
            )
        )
    )
    matching_closed = [
        event
        for event in closed_events
        if isinstance(event.payload, dict)
        and event.payload.get("action_id") == pipeline.predecessor_action_id
        and event.payload.get("presentation_id") == pipeline.predecessor_presentation_id
    ]
    if len(matching_closed) != 1:
        raise RepositoryError("pre-exile predecessor has no unique durable close event")
    _validate_pre_exile_predecessor_canonical_commit(
        db,
        pipeline=pipeline,
        predecessor_closed_record_seq=matching_closed[0].record_seq,
    )
    by_actor = {result.actor_player_id: result for result in results}
    if (
        len(by_actor) != len(results)
        or set(by_actor) != set(expected_voter_ids)
        or len(set(expected_voter_ids)) != len(expected_voter_ids)
        or len(votes) != len(expected_voter_ids)
    ):
        raise RepositoryError("pre-exile vote result membership is incomplete")
    for vote in votes:
        result = by_actor.get(vote.voter_player_id)
        if result is None or result.state not in {"ready", "failed"}:
            raise RepositoryError("pre-exile vote result is not durable")
        if result.state == "ready":
            decision = result.decision or {}
            if (
                (
                    result.failure is not None
                    and not (
                        result.recovery_action_id is not None
                        and set(result.failure) == {"initial_admission_failure"}
                    )
                )
                or vote.technical_status is not None
                or decision.get("target_player_id") != vote.target_player_id
                or decision.get("decision_note") != vote.decision_note
            ):
                raise RepositoryError("pre-exile committed vote changed its speculative result")
            continue
        failure = result.failure or {}
        technical = failure.get("technical_outcome")
        if not isinstance(technical, dict):
            raise RepositoryError("pre-exile failed vote has no technical abstention lineage")
        if (
            vote.technical_status != "technical_abstain"
            or vote.source_action_id != (result.recovery_action_id or result.action_id)
            or vote.supporting_event_record_seq != failure.get("technical_outcome_record_seq")
            or vote.failure_episode_id != technical.get("failure_episode_id")
            or vote.failure_mode != technical.get("target_exhaustion_failure_mode")
            or vote.technical_reason != technical.get("failure_code")
        ):
            raise RepositoryError("pre-exile technical abstention changed its speculative result")


def _validate_idempotent_pre_exile_vote_commit(
    db: Session,
    *,
    game: GameRecord,
    pipeline: PreExilePipeline,
    results: list[PreExileResult],
    phase_id: str,
    phase_state: str,
    round_no: int,
    action_type: str,
    batch_id: str,
    public_cutoff_record_seq: int,
    expected_voter_ids: tuple[str, ...],
    votes: tuple[DayVoteCommit, ...],
    decision_context: dict[str, Any],
    resolution_payload: dict[str, Any],
) -> None:
    voter_ids = tuple(vote.voter_player_id for vote in votes)
    if (
        pipeline.vote_batch_id != batch_id
        or any(result.state != "committed" for result in results)
        or phase_id != pipeline.phase_id
        or phase_state != game.phase_state
        or round_no != pipeline.round_no
        or action_type != "exile_vote"
        or public_cutoff_record_seq != pipeline.public_cutoff_record_seq
        or batch_id != f"{pipeline.phase_id}:exile_vote:{pipeline.public_cutoff_record_seq}:vote"
        or expected_voter_ids != voter_ids
        or len(set(expected_voter_ids)) != len(expected_voter_ids)
        or decision_context.get("batch_id") != batch_id
        or decision_context.get("public_cutoff_record_seq") != public_cutoff_record_seq
        or pipeline.vote_decision_context_sha256 != pre_exile_context_sha256(decision_context)
    ):
        raise RepositoryError("consumed pre-exile pipeline has different durable output")
    vote_results = {
        result.actor_player_id: result for result in results if result.result_kind == "exile_vote"
    }
    if set(vote_results) != set(expected_voter_ids):
        raise RepositoryError(
            "consumed pre-exile pipeline has different durable result membership"
        )
    for vote in votes:
        result = vote_results[vote.voter_player_id]
        if vote.technical_status is None:
            decision = result.decision or {}
            if (
                decision.get("target_player_id") != vote.target_player_id
                or decision.get("decision_note") != vote.decision_note
            ):
                raise RepositoryError("pre-exile retry changed a committed private vote")
        else:
            failure = result.failure or {}
            technical = failure.get("technical_outcome")
            if (
                vote.decision_note is not None
                or vote.technical_status != "technical_abstain"
                or not isinstance(technical, dict)
                or vote.source_action_id != (result.recovery_action_id or result.action_id)
                or vote.supporting_event_record_seq != failure.get("technical_outcome_record_seq")
                or vote.failure_episode_id != technical.get("failure_episode_id")
                or vote.failure_mode != technical.get("target_exhaustion_failure_mode")
                or vote.technical_reason != technical.get("failure_code")
            ):
                raise RepositoryError("pre-exile retry changed a committed technical vote")
    events = list(
        db.scalars(
            select(GameRecordEvent)
            .where(
                GameRecordEvent.game_id == game.game_id,
                GameRecordEvent.run_id == pipeline.run_id,
                GameRecordEvent.event_type.in_(("day_vote_committed", "day_vote_resolved")),
            )
            .order_by(GameRecordEvent.record_seq)
        )
    )
    committed = [
        event
        for event in events
        if isinstance(event.payload, dict)
        and event.payload.get("batch_id") == batch_id
        and event.event_type == "day_vote_committed"
    ]
    resolved = [
        event
        for event in events
        if isinstance(event.payload, dict)
        and event.payload.get("batch_id") == batch_id
        and event.event_type == "day_vote_resolved"
    ]
    if len(committed) != len(votes) or len(resolved) != 1:
        raise RepositoryError("pre-exile vote commit is not idempotent")
    durable_votes = [
        (
            event.payload.get("voter_player_id"),
            event.payload.get("target_player_id"),
            event.payload.get("weight"),
            event.payload.get("technical_status"),
            event.payload.get("technical_reason"),
        )
        for event in committed
    ]
    requested_votes = [
        (
            vote.voter_player_id,
            vote.target_player_id,
            vote.weight,
            vote.technical_status,
            vote.technical_reason,
        )
        for vote in votes
    ]
    durable_resolution = {
        key: value
        for key, value in resolved[0].payload.items()
        if key not in {"audience", "audience_contract_version"}
    }
    if (
        durable_votes != requested_votes
        or type(resolution_payload) is not dict
        or resolution_payload != durable_resolution
    ):
        raise RepositoryError("pre-exile retry changed an already committed vote batch")


def _validate_day_vote_batch(
    db: Session,
    *,
    game: GameRecord,
    match: MatchState,
    phase_id: str,
    phase_state: str,
    round_no: int,
    action_type: str,
    batch_id: str,
    public_cutoff_record_seq: int,
    expected_voter_ids: tuple[str, ...],
    votes: tuple[DayVoteCommit, ...],
    decision_context: dict[str, Any],
    resolution_payload: dict[str, Any],
) -> None:
    if (
        game.phase_id != phase_id
        or game.phase_state != phase_state
        or not phase_id.startswith("day_")
        or match.round_no != round_no
    ):
        raise RepositoryError("day vote phase changed before batch commit")
    expected_batch_id = f"{phase_id}:{action_type}:{public_cutoff_record_seq}:vote"
    if batch_id != expected_batch_id:
        raise RepositoryError("day vote batch identity is invalid")
    if (
        not isinstance(public_cutoff_record_seq, int)
        or isinstance(public_cutoff_record_seq, bool)
        or public_cutoff_record_seq < 0
        or public_cutoff_record_seq > game.last_record_seq
    ):
        raise RepositoryError("day vote public cutoff is invalid")
    voter_ids = tuple(vote.voter_player_id for vote in votes)
    if len(set(expected_voter_ids)) != len(expected_voter_ids) or voter_ids != expected_voter_ids:
        raise RepositoryError("day vote batch is incomplete or out of order")
    if len(set(voter_ids)) != len(voter_ids):
        raise RepositoryError("day vote batch contains duplicate voters")
    if (
        decision_context.get("batch_id") != batch_id
        or decision_context.get("public_cutoff_record_seq") != public_cutoff_record_seq
    ):
        raise RepositoryError("day vote private decision context is inconsistent")
    expected_resolution_values = {
        "round_no": round_no,
        "action_type": action_type,
        "batch_id": batch_id,
        "public_cutoff_record_seq": public_cutoff_record_seq,
    }
    if any(
        resolution_payload.get(key) != value for key, value in expected_resolution_values.items()
    ):
        raise RepositoryError("day vote resolution payload is inconsistent")
    eligible_voter_ids = resolution_payload.get("eligible_voter_ids")
    if (
        not isinstance(eligible_voter_ids, list)
        or any(not isinstance(player_id, str) for player_id in eligible_voter_ids)
        or len(set(eligible_voter_ids)) != len(eligible_voter_ids)
        or set(eligible_voter_ids) != set(expected_voter_ids)
    ):
        raise RepositoryError("day vote eligible voter set is inconsistent")
    candidate_ids = resolution_payload.get("candidate_player_ids")
    if (
        not isinstance(candidate_ids, list)
        or any(not isinstance(player_id, str) for player_id in candidate_ids)
        or len(set(candidate_ids)) != len(candidate_ids)
    ):
        raise RepositoryError("day vote candidate set is invalid")
    candidate_id_set = set(candidate_ids)
    computed_totals: dict[str, float] = {}
    computed_weights: dict[str, float] = {}
    computed_technical_abstentions: list[dict[str, str]] = []
    for vote in votes:
        voter = db.get(PlayerState, (game.game_id, vote.voter_player_id))
        if voter is None or not voter.alive:
            raise RepositoryError("day vote voter must be alive")
        try:
            weight = float(vote.weight)
        except (TypeError, ValueError) as exc:
            raise RepositoryError("day vote weight is invalid") from exc
        if not math.isfinite(weight):
            raise RepositoryError("day vote weight is invalid")

        if vote.technical_status == "technical_abstain":
            reason = vote.technical_reason
            if (
                vote.target_player_id is not None
                or weight != 0.0
                or vote.decision_note is not None
                or not isinstance(reason, str)
                or not reason.strip()
                or len(reason) > 120
            ):
                raise RepositoryError("day vote technical abstention is invalid")
            _validate_day_vote_technical_abstention_lineage(
                db,
                game=game,
                vote=vote,
                action_type=action_type,
                public_cutoff_record_seq=public_cutoff_record_seq,
            )
            computed_weights[vote.voter_player_id] = 0.0
            computed_technical_abstentions.append(
                {
                    "voter_player_id": vote.voter_player_id,
                    "technical_status": "technical_abstain",
                    "technical_reason": reason,
                }
            )
            continue

        if (
            vote.technical_status is not None
            or vote.technical_reason is not None
            or vote.source_action_id is not None
            or vote.supporting_event_record_seq is not None
            or vote.failure_episode_id is not None
            or vote.failure_mode is not None
        ):
            raise RepositoryError("day vote technical status is invalid")
        if (
            not isinstance(vote.target_player_id, str)
            or vote.target_player_id == vote.voter_player_id
            or vote.target_player_id not in candidate_id_set
        ):
            raise RepositoryError("day vote target is invalid")
        target = db.get(PlayerState, (game.game_id, vote.target_player_id))
        if target is None or not target.alive:
            raise RepositoryError("day vote target must be alive")
        if weight <= 0:
            raise RepositoryError("day vote weight must be positive")
        computed_weights[vote.voter_player_id] = weight
        computed_totals[vote.target_player_id] = (
            computed_totals.get(vote.target_player_id, 0.0) + weight
        )
    if resolution_payload.get("voter_weights") != computed_weights:
        raise RepositoryError("day vote voter weights are inconsistent")
    if resolution_payload.get("totals") != computed_totals:
        raise RepositoryError("day vote totals are inconsistent")
    technical_abstentions = resolution_payload.get("technical_abstentions")
    if computed_technical_abstentions:
        if technical_abstentions != computed_technical_abstentions:
            raise RepositoryError("day vote technical abstentions are inconsistent")
    elif technical_abstentions not in (None, []):
        raise RepositoryError("day vote technical abstentions are inconsistent")
    leaders = []
    if computed_totals:
        highest = max(computed_totals.values())
        leaders = sorted(
            player_id for player_id, total in computed_totals.items() if total == highest
        )
    if resolution_payload.get("leaders") != leaders:
        raise RepositoryError("day vote leaders are inconsistent")
    existing_vote_events = list(
        db.scalars(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == game.game_id,
                GameRecordEvent.event_type.in_(("day_vote_committed", "day_vote_resolved")),
            )
        )
    )
    if any(
        isinstance(event.payload, dict) and event.payload.get("batch_id") == batch_id
        for event in existing_vote_events
    ):
        raise RepositoryError("day vote batch already has durable output")
    existing_private_decisions = list(
        db.scalars(
            select(KnowledgeFact).where(
                KnowledgeFact.game_id == game.game_id,
                KnowledgeFact.fact_type == "private_action_decision",
            )
        )
    )
    if any(
        isinstance(fact.payload, dict)
        and isinstance(fact.payload.get("context"), dict)
        and fact.payload["context"].get("batch_id") == batch_id
        for fact in existing_private_decisions
    ):
        raise RepositoryError("day vote batch already has durable private decisions")


def _validate_day_vote_technical_abstention_lineage(
    db: Session,
    *,
    game: GameRecord,
    vote: DayVoteCommit,
    action_type: str,
    public_cutoff_record_seq: int,
) -> None:
    source_action_id = vote.source_action_id
    supporting_record_seq = vote.supporting_event_record_seq
    failure_episode_id = vote.failure_episode_id
    failure_mode = vote.failure_mode
    if (
        not isinstance(source_action_id, str)
        or not source_action_id
        or not isinstance(supporting_record_seq, int)
        or isinstance(supporting_record_seq, bool)
        or supporting_record_seq <= public_cutoff_record_seq
        or not isinstance(failure_episode_id, str)
        or not failure_episode_id
        or failure_mode
        not in {
            "output_budget_exhausted",
            "attempt_hard_timeout",
            "action_wall_timeout",
        }
    ):
        raise RepositoryError("day vote technical abstention lineage is invalid")

    supporting = db.scalar(
        select(GameRecordEvent).where(
            GameRecordEvent.game_id == game.game_id,
            GameRecordEvent.record_seq == supporting_record_seq,
        )
    )
    supporting_payload = supporting.payload if supporting is not None else None
    if (
        supporting is None
        or supporting.run_id != game.current_run_id
        or supporting.event_type != "technical_target_outcome_applied"
        or not isinstance(supporting_payload, dict)
        or supporting_payload.get("audience") != "god_view"
        or supporting_payload.get("action_id") != source_action_id
        or supporting_payload.get("failure_episode_id") != failure_episode_id
        or supporting_payload.get("actor_id") != vote.voter_player_id
        or supporting_payload.get("action_type") != action_type
        or supporting_payload.get("technical_outcome") != "technical_abstain"
        or supporting_payload.get("failure_code") != vote.technical_reason
        or supporting_payload.get("target_exhaustion_failure_mode") != failure_mode
        or supporting_payload.get("target_player_id") is not None
        or supporting_payload.get("model_generation_policy_schema_version")
        != MODEL_GENERATION_POLICY_SCHEMA_VERSION
    ):
        raise RepositoryError("day vote technical abstention lineage is invalid")

    succeeded_events = list(
        db.scalars(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == game.game_id,
                GameRecordEvent.run_id == game.current_run_id,
                GameRecordEvent.event_type == "action_succeeded",
            )
        )
    )
    matching_succeeded = [
        event
        for event in succeeded_events
        if event.record_seq > supporting_record_seq
        and isinstance(event.payload, dict)
        and event.payload.get("action_id") == source_action_id
        and event.payload.get("failure_episode_id") == failure_episode_id
        and event.payload.get("technical_outcome_record_seq") == supporting_record_seq
    ]
    if len(matching_succeeded) != 1:
        raise RepositoryError("day vote technical abstention lineage is invalid")

    existing_lineage_events = list(
        db.scalars(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == game.game_id,
                GameRecordEvent.run_id == game.current_run_id,
                GameRecordEvent.event_type == "day_vote_technical_abstention_committed",
            )
        )
    )
    if any(
        isinstance(event.payload, dict)
        and (
            event.payload.get("source_action_id") == source_action_id
            or event.payload.get("supporting_event_record_seq") == supporting_record_seq
        )
        for event in existing_lineage_events
    ):
        raise RepositoryError("day vote technical abstention lineage was already committed")


def _raise_if_stop_requested(db: Session, game: GameRecord) -> None:
    run = _run(db, game.current_run_id)
    if run.stop_requested_at is not None:
        raise GameCanceled("V2 game was canceled by an administrator")


def _private_round_memory_batch_terminal_event(
    db: Session,
    *,
    game_id: str,
    run_id: str,
    batch_id: str,
) -> GameRecordEvent | None:
    matching = [
        event
        for event in db.scalars(
            select(GameRecordEvent)
            .where(
                GameRecordEvent.game_id == game_id,
                GameRecordEvent.run_id == run_id,
                GameRecordEvent.event_type == "day_private_memory_batch_completed",
            )
            .order_by(GameRecordEvent.record_seq)
        )
        if isinstance(event.payload, dict) and event.payload.get("batch_id") == batch_id
    ]
    if len(matching) > 1:
        raise RepositoryError("private round memory batch has duplicate terminal events")
    return matching[0] if matching else None


def _private_round_memory_source_refs(
    db: Session,
    *,
    game_id: str,
    owner_id: str,
    source_cutoff_record_seq: int,
    previous_snapshot_fact_id: str | None,
) -> list[str]:
    public_history = _public_history(
        db,
        game_id,
        at_or_before_record_seq=source_cutoff_record_seq,
    )
    private_facts = player_private_knowledge(
        db,
        game_id=game_id,
        player_id=owner_id,
        at_or_before_record_seq=source_cutoff_record_seq,
    )
    previous_cutoff = 0
    if previous_snapshot_fact_id is not None:
        previous = next(
            (
                item
                for item in private_facts
                if item.get("knowledge_fact_id") == previous_snapshot_fact_id
                and item.get("fact_type") == "private_round_memory"
            ),
            None,
        )
        if previous is None:
            raise RepositoryError("private round memory predecessor source is invalid")
        payload = previous.get("payload") if isinstance(previous.get("payload"), dict) else {}
        previous_cutoff = _positive_int(payload.get("source_cutoff_record_seq")) or 0
    elif any(item.get("fact_type") == "private_round_memory" for item in private_facts):
        raise RepositoryError("private round memory predecessor source is missing")
    public_refs = [
        f"event:{item['source_event_id']}"
        for item in public_history
        if isinstance(item.get("source_event_id"), int)
        and isinstance(item.get("record_seq"), int)
        and item["record_seq"] > previous_cutoff
    ]
    private_refs = [
        f"fact:{item['knowledge_fact_id']}"
        for item in private_facts
        if item.get("fact_type") != "private_round_memory"
        and isinstance(item.get("knowledge_fact_id"), str)
    ]
    return [
        *(
            [f"fact:{previous_snapshot_fact_id}"]
            if previous_snapshot_fact_id is not None
            else []
        ),
        f"state:{source_cutoff_record_seq}",
        *public_refs,
        *private_refs,
    ]


def _validate_private_round_memory_model_lineage(
    db: Session,
    *,
    game: GameRecord,
    commit: PrivateRoundMemoryCommit,
    batch_id: str,
    phase_id: str,
    phase_state: str,
    round_no: int,
    source_cutoff_record_seq: int,
    normalized_memory: str,
) -> None:
    response = db.scalar(
        select(GameRecordEvent).where(
            GameRecordEvent.game_id == game.game_id,
            GameRecordEvent.run_id == game.current_run_id,
            GameRecordEvent.record_seq == commit.model_response_record_seq,
            GameRecordEvent.event_type == "model_response_received",
        )
    )
    terminal = db.scalar(
        select(GameRecordEvent).where(
            GameRecordEvent.game_id == game.game_id,
            GameRecordEvent.run_id == game.current_run_id,
            GameRecordEvent.record_seq == commit.terminal_event_record_seq,
            GameRecordEvent.event_type == "action_succeeded",
        )
    )
    opened_matches = [
        event
        for event in db.scalars(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == game.game_id,
                GameRecordEvent.run_id == game.current_run_id,
                GameRecordEvent.event_type == "action_opened",
            )
        )
        if isinstance(event.payload, dict)
        and event.payload.get("action_id") == commit.action_id
    ]
    opened = opened_matches[0] if len(opened_matches) == 1 else None
    response_payload = response.payload if response is not None else None
    terminal_payload = terminal.payload if terminal is not None else None
    opened_payload = opened.payload if opened is not None else None
    context = opened_payload.get("context") if isinstance(opened_payload, dict) else None
    context = (
        {
            key: value
            for key, value in context.items()
            if key not in {"audience", "audience_contract_version"}
        }
        if isinstance(context, dict)
        else None
    )
    parsed_output = (
        response_payload.get("parsed_output") if isinstance(response_payload, dict) else None
    )
    requests = list(
        db.scalars(
            select(GameRecordEvent).where(
                GameRecordEvent.game_id == game.game_id,
                GameRecordEvent.run_id == game.current_run_id,
                GameRecordEvent.event_type == "model_request_started",
            )
        )
    )
    request_matches = [
        event
        for event in requests
        if isinstance(event.payload, dict)
        and event.payload.get("action_id") == commit.action_id
        and event.payload.get("attempt_id") == commit.attempt_id
    ]
    request = request_matches[0] if len(request_matches) == 1 else None
    request_payload = (
        request.payload.get("request_payload")
        if request is not None and isinstance(request.payload, dict)
        else None
    )
    request_model_context = (
        request.payload.get("model_context")
        if request is not None and isinstance(request.payload, dict)
        else None
    )
    replayed_model_context: dict[str, Any] | None = None
    if isinstance(context, dict) and opened is not None:
        try:
            replayed_model_context = project_model_action_context_with_metadata(
                context,
                players=tuple(
                    ModelPlayerReference(
                        player_id=player.player_id,
                        seat=player.seat,
                        display_name=player.display_name,
                    )
                    for player in _players(db, game)
                ),
                model_context_contract=frozen_model_context_contract(game.rule_snapshot),
                action_record_seq=opened.record_seq,
                projection_at_seq=source_cutoff_record_seq,
            ).context
        except (TypeError, ValueError):
            replayed_model_context = None
    request_sha256 = (
        hashlib.sha256(
            json.dumps(
                request_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if isinstance(request_payload, dict)
        else None
    )
    projected_context_sha256 = (
        hashlib.sha256(
            json.dumps(
                request_model_context,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if isinstance(request_model_context, dict)
        else None
    )
    expected_previous_cutoff = 0
    expected_previous_snapshot: dict[str, Any] | None = None
    expected_private_facts = player_private_knowledge(
        db,
        game_id=game.game_id,
        player_id=commit.player_id,
        at_or_before_record_seq=source_cutoff_record_seq,
    )
    if commit.previous_snapshot_fact_id is not None:
        previous_rows = list(
            db.scalars(
                select(KnowledgeFact).where(
                    KnowledgeFact.game_id == game.game_id,
                    KnowledgeFact.owner_scope == "player",
                    KnowledgeFact.owner_id == commit.player_id,
                    KnowledgeFact.fact_type == "private_round_memory",
                    KnowledgeFact.knowledge_fact_id == commit.previous_snapshot_fact_id,
                )
            )
        )
        if len(previous_rows) == 1:
            previous_row = previous_rows[0]
            previous_payload = (
                previous_row.payload if isinstance(previous_row.payload, dict) else {}
            )
            expected_previous_cutoff = (
                _positive_int(previous_payload.get("source_cutoff_record_seq")) or 0
            )
            expected_previous_snapshot = next(
                (
                    item
                    for item in expected_private_facts
                    if item.get("knowledge_fact_id") == commit.previous_snapshot_fact_id
                ),
                None,
            )
    match = _match(db, game)
    expected_players = _players(db, game)
    expected_owner = next(
        (player for player in expected_players if player.player_id == commit.player_id),
        None,
    )
    expected_context_facts = [dict(item) for item in expected_private_facts]
    expected_public_history = [
        dict(item)
        for item in _public_history(
            db,
            game.game_id,
            at_or_before_record_seq=source_cutoff_record_seq,
        )
        if isinstance(item.get("record_seq"), int)
        and item["record_seq"] > expected_previous_cutoff
    ]
    expected_action_context = (
        build_private_round_memory_action_context(
            game_id=game.game_id,
            action_id=commit.action_id,
            phase_id=phase_id,
            round_no=round_no,
            batch_id=batch_id,
            source_cutoff_record_seq=source_cutoff_record_seq,
            player_id=expected_owner.player_id,
            seat=expected_owner.seat,
            role_key=expected_owner.role_key,
            team=expected_owner.team,
            persona=expected_owner.persona,
            alive=expected_owner.alive,
            sheriff_player_id=match.sheriff_player_id,
            sheriff_badge_state=match.sheriff_badge_state,
            rule=_match_snapshot(
                db,
                game=game,
                match=match,
                public_history=tuple(expected_public_history),
                last_record_seq=source_cutoff_record_seq,
            ).rule,
            max_rounds=int(game.rule_snapshot.get("max_rounds") or 8),
            player_state=expected_owner.state,
            players=expected_players,
            private_facts=expected_context_facts,
            public_history=expected_public_history,
            previous_memory_snapshot=expected_previous_snapshot,
            previous_memory_fact_id=commit.previous_snapshot_fact_id,
            previous_memory_source_cutoff_record_seq=(expected_previous_cutoff or None),
            memory_source_refs=commit.source_refs,
            memory_source_refs_sha256=commit.source_refs_sha256,
        )
        if expected_owner is not None
        else None
    )
    context_source_refs = context.get("memory_source_refs") if isinstance(context, dict) else None
    context_source_hash = (
        context.get("memory_source_refs_sha256") if isinstance(context, dict) else None
    )
    context_previous_cutoff = (
        context.get("previous_memory_source_cutoff_record_seq")
        if isinstance(context, dict)
        else None
    )
    request_known_events = (
        request_model_context.get("known_events")
        if isinstance(request_model_context, dict)
        else None
    )
    try:
        expanded_known_events = (
            expand_known_events_v7(request_known_events)
            if isinstance(request_known_events, dict)
            else None
        )
    except Exception:
        expanded_known_events = None
    projected_event_refs = (
        tuple(
            str(item["event_ref"])
            for item in expanded_known_events.get("events", [])
            if isinstance(item, dict) and isinstance(item.get("event_ref"), str)
        )
        if isinstance(expanded_known_events, dict)
        else None
    )
    projected_known_events_sha256 = (
        hashlib.sha256(
            json.dumps(
                request_known_events,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if isinstance(request_known_events, dict)
        else None
    )
    context_matches_frozen_db = (
        isinstance(context, dict)
        and isinstance(expected_action_context, dict)
        and {
            key: value
            for key, value in context.items()
            if key not in {"run_id", "action_record_seq"}
        }
        == expected_action_context
        and context.get("run_id") == game.current_run_id
        and context.get("action_record_seq") == opened.record_seq
    )
    if (
        response is None
        or terminal is None
        or opened is None
        or request is None
        or not isinstance(response_payload, dict)
        or not isinstance(terminal_payload, dict)
        or not isinstance(context, dict)
        or not isinstance(parsed_output, dict)
        or response_payload.get("action_id") != commit.action_id
        or response_payload.get("attempt_id") != commit.attempt_id
        or terminal_payload.get("action_id") != commit.action_id
        or terminal_payload.get("source_attempt_id") != commit.attempt_id
        or terminal_payload.get("source_model_response_record_seq")
        != commit.model_response_record_seq
        or terminal_payload.get("provider_request_id") != commit.provider_request_id
        or opened_payload.get("action_id") != commit.action_id
        or context.get("action_type") != "private_round_memory"
        or context.get("actor") != {"kind": "player", "id": commit.player_id}
        or context.get("phase_id") != phase_id
        or context.get("round_no") != round_no
        or context.get("batch_id") != batch_id
        or context.get("projection_at_seq") != source_cutoff_record_seq
        or context.get("public_cutoff_record_seq") != source_cutoff_record_seq
        or context.get("previous_memory_fact_id") != commit.previous_snapshot_fact_id
        or context.get("previous_memory_snapshot") != expected_previous_snapshot
        or context_previous_cutoff != (expected_previous_cutoff or None)
        or context_source_refs != list(commit.source_refs)
        or context_source_hash != commit.source_refs_sha256
        or not context_matches_frozen_db
        or response_payload.get("provider_request_id") != commit.provider_request_id
        or request_sha256 != commit.request_payload_sha256
        or expected_owner is None
        or not request_payload_matches_model_context(
            request_payload,
            model_context=request_model_context,
            model_provider=expected_owner.model_provider,
            model_id=expected_owner.model_id,
            parameters=expected_owner.model_parameters,
            supports_thinking=expected_owner.model_supports_thinking,
        )
        or projected_context_sha256 != commit.projected_context_sha256
        or replayed_model_context != request_model_context
        or projected_event_refs != commit.projected_known_event_refs
        or projected_known_events_sha256 != commit.projected_known_events_sha256
        or str(parsed_output.get("speech") or "").strip()[:400].rstrip()
        != normalized_memory
        or not (opened.record_seq < request.record_seq < response.record_seq < terminal.record_seq)
    ):
        raise RepositoryError("private round memory model lineage is invalid")


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


def private_round_memory_source_refs_sha256(
    *,
    owner_id: str,
    round_no: int,
    previous_snapshot_fact_id: str | None,
    source_cutoff_record_seq: int,
    source_refs: list[str],
) -> str:
    encoded = json.dumps(
        {
            "owner_id": owner_id,
            "round_no": round_no,
            "previous_snapshot_fact_id": previous_snapshot_fact_id,
            "source_cutoff_record_seq": source_cutoff_record_seq,
            "source_refs": source_refs,
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _private_round_memory_order(row: KnowledgeFact) -> tuple[int, int, str]:
    payload = row.payload if isinstance(row.payload, dict) else {}
    round_no = _positive_int(payload.get("round_no")) or 0
    cutoff = _positive_int(payload.get("source_cutoff_record_seq")) or 0
    return (round_no, cutoff, row.knowledge_fact_id)


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


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
