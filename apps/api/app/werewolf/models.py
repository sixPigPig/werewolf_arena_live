from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.werewolf.lm import LmLog


@dataclass
class DeathEvent:
    player: str
    cause: str
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"player": self.player, "cause": self.cause, "source": self.source}


PublicOutcomeKind = Literal[
    "night_death",
    "hunter_shot",
    "self_explosion",
    "exile",
    "idiot_reveal",
    "badge_transferred",
    "badge_lost",
]


@dataclass(frozen=True)
class PublicOutcomeEventV1:
    schema_version: Literal[1]
    event_id: str
    sequence: int
    kind: PublicOutcomeKind
    actor_player_id: str | None
    target_player_id: str | None
    outcome: str
    caused_by_event_id: str | None
    occurred_phase: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ActionLog:
    actor: str
    action: str
    options: list[str]
    choice: str | None
    lm_log: LmLog
    invalid_value: object | None = None
    fallback_choice: object | None = None
    fallback_reason: str | None = None
    attempt_count: int = 1
    decision_schema: str | None = None
    decision_audit: dict[str, str] | None = None
    raw_choice: object | None = None
    choice_normalization_kind: str | None = None
    speech_mission: dict[str, object] | None = None
    speech_quality_report: dict[str, object] | None = None
    speech_quality_attempt_count: int = 0
    speech_quality_retry_exhausted: bool = False
    speech_quality_initial_codes: list[str] = field(default_factory=list)
    execution_status: Literal["completed", "timed_out", "fallback", "failed"] = (
        "completed"
    )
    duration_ms: int = 0
    budget_ms: int | None = None
    first_token_ms: int | None = None
    fact_prompt_coverage: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "actor": self.actor,
            "action": self.action,
            "options": self.options,
            "choice": self.choice,
            "lm_log": self.lm_log.to_dict(),
            "invalid_value": self.invalid_value,
            "fallback_choice": self.fallback_choice,
            "fallback_reason": self.fallback_reason,
            "attempt_count": self.attempt_count,
        }
        if (
            self.execution_status != "completed"
            or self.duration_ms > 0
            or self.budget_ms is not None
            or self.first_token_ms is not None
        ):
            payload["execution_status"] = self.execution_status
            payload["duration_ms"] = self.duration_ms
            payload["budget_ms"] = self.budget_ms
            payload["first_token_ms"] = self.first_token_ms
        if self.decision_schema is not None:
            payload["decision_schema"] = self.decision_schema
        if self.decision_audit is not None:
            payload["decision_audit"] = self.decision_audit.copy()
        if self.choice_normalization_kind is not None:
            payload["raw_choice"] = self.raw_choice
            payload["choice_normalization_kind"] = self.choice_normalization_kind
        if self.speech_quality_report is not None:
            payload["speech_mission"] = self.speech_mission
            payload["speech_quality_report"] = self.speech_quality_report
            payload["speech_quality_attempt_count"] = self.speech_quality_attempt_count
            payload["speech_quality_retry_exhausted"] = (
                self.speech_quality_retry_exhausted
            )
            payload["speech_quality_initial_codes"] = (
                self.speech_quality_initial_codes.copy()
            )
        if self.fact_prompt_coverage is not None:
            payload["fact_prompt_coverage"] = copy.deepcopy(self.fact_prompt_coverage)
        return payload


@dataclass
class DebateEntry:
    speaker: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class GameView:
    round_number: int
    current_players: list[str]
    debate: list[DebateEntry] = field(default_factory=list)
    other_wolf: str | None = None
    wolf_teammates: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "current_players": self.current_players,
            "debate": [entry.to_dict() for entry in self.debate],
            "other_wolf": self.other_wolf,
            "wolf_teammates": self.wolf_teammates,
        }


@dataclass
class Player:
    name: str
    role: str
    model: str
    personality_id: str = "balanced"
    personality: str = ""
    appearance_id: str = "default"
    avatar_prompt: str = ""
    avatar_image_url: str = ""
    profile_id: str | None = None
    tags: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    bidding_rationale: str = ""
    gamestate: GameView | None = None
    known_roles: dict[str, str] = field(default_factory=dict)
    can_vote: bool = True
    revealed_role: bool = False
    witch_antidote_available: bool = False
    witch_poison_available: bool = False
    hunter_can_shoot: bool = False
    is_sheriff: bool = False

    def add_observation(self, observation: str) -> None:
        self.observations.append(observation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "model": self.model,
            "personality_id": self.personality_id,
            "personality": self.personality,
            "appearance_id": self.appearance_id,
            "avatar_prompt": self.avatar_prompt,
            "avatar_image_url": self.avatar_image_url,
            "profile_id": self.profile_id,
            "tags": self.tags,
            "observations": self.observations,
            "bidding_rationale": self.bidding_rationale,
            "gamestate": self.gamestate.to_dict() if self.gamestate else None,
            "known_roles": self.known_roles,
            "can_vote": self.can_vote,
            "revealed_role": self.revealed_role,
            "witch_antidote_available": self.witch_antidote_available,
            "witch_poison_available": self.witch_poison_available,
            "hunter_can_shoot": self.hunter_can_shoot,
            "is_sheriff": self.is_sheriff,
        }


InterruptionTiming = Literal["before_stage", "before_actor", "after_actor"]


@dataclass(frozen=True)
class StageInterruption:
    stage: str
    interrupted_by: str
    actor: str
    timing: InterruptionTiming
    last_completed_speaker: str | None = None
    completed_actors: list[str] = field(default_factory=list)
    pending_actors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "interrupted_by": self.interrupted_by,
            "actor": self.actor,
            "timing": self.timing,
            "last_completed_speaker": self.last_completed_speaker,
            "completed_actors": self.completed_actors.copy(),
            "pending_actors": self.pending_actors.copy(),
        }


SheriffElectionOutcome = Literal["elected", "badge_lost", "postponed"]
SheriffElectionReason = Literal[
    "single_candidate",
    "first_vote_winner",
    "runoff_vote_winner",
    "no_candidates",
    "all_candidates_withdrew",
    "no_off_sheriff_voters",
    "first_vote_empty",
    "runoff_tied",
    "first_pre_election_self_explosion",
    "double_pre_election_self_explosion",
]


@dataclass(frozen=True)
class SheriffElectionResolution:
    schema_version: int
    outcome: SheriffElectionOutcome
    reason_code: SheriffElectionReason
    reason_text: str
    sheriff: str | None
    candidates: list[str]
    withdrawn: list[str]
    final_candidates: list[str]
    voters: list[str]
    votes: dict[str, str]
    pk_candidates: list[str]
    runoff_votes: dict[str, str]
    badge_lost: bool
    election_pending: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SheriffBadgeOutcome = Literal["transferred", "destroyed", "lost_no_target"]


@dataclass(frozen=True)
class SheriffBadgeResolution:
    schema_version: int
    outcome: SheriffBadgeOutcome
    from_player: str
    to_player: str | None
    reason_code: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SheriffVoteEligibilityReason = Literal[
    "eligible_original_voter",
    "candidate_not_eligible",
    "withdrew_candidate_not_original_voter",
    "no_off_sheriff_voters",
    "election_resolved",
    "sheriff_disabled",
]


@dataclass(frozen=True)
class PublicActionEligibility:
    sheriff_election_active: bool
    original_candidates: list[str]
    original_voters: list[str]
    final_candidates: list[str]
    actor_was_candidate: bool
    actor_withdrew: bool
    actor_can_sheriff_vote: bool
    sheriff_vote_reason: SheriffVoteEligibilityReason
    actor_can_exile_vote: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SelfExplosionDecisionContext:
    total_self_explosions: int
    consecutive_self_explosion_rounds: int
    active_wolves_before: int
    actor_is_last_wolf: bool
    active_players_before: int
    current_stage: str
    completed_public_speakers: int
    pending_public_speakers: int
    sheriff_election_open: bool
    pre_election_bomb_count: int
    badge_impact: str
    explosion_would_end_game: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RoundState:
    number: int
    players: list[str]
    attacked: str | None = None
    eliminated: str | None = None
    protected: str | None = None
    investigated: str | None = None
    exiled: str | None = None
    night_deaths: list[DeathEvent] = field(default_factory=list)
    werewolf_discussion: list[dict[str, Any]] = field(default_factory=list)
    werewolf_vote_rounds: list[dict[str, Any]] = field(default_factory=list)
    day_deaths: list[DeathEvent] = field(default_factory=list)
    saved_by_witch: str | None = None
    poisoned: str | None = None
    hunter_shot: str | None = None
    idiot_revealed: str | None = None
    debate: list[DebateEntry] = field(default_factory=list)
    bids: list[dict[str, int]] = field(default_factory=list)
    votes: list[dict[str, str]] = field(default_factory=list)
    exile_pk_candidates: list[str] = field(default_factory=list)
    exile_pk_speeches: list[dict[str, str]] = field(default_factory=list)
    exile_runoff_votes: dict[str, str] = field(default_factory=dict)
    exile_resolution_reason: str | None = None
    summaries: dict[str, str] = field(default_factory=dict)
    private_summaries: dict[str, str] = field(default_factory=dict)
    public_summary: str = ""
    sheriff: str | None = None
    sheriff_candidates: list[str] = field(default_factory=list)
    sheriff_speech_order: list[str] = field(default_factory=list)
    sheriff_speech_direction: str | None = None
    sheriff_speeches: list[dict[str, str]] = field(default_factory=list)
    sheriff_withdrawn: list[str] = field(default_factory=list)
    sheriff_final_candidates: list[str] = field(default_factory=list)
    sheriff_voters: list[str] = field(default_factory=list)
    sheriff_votes: dict[str, str] = field(default_factory=dict)
    sheriff_pk_candidates: list[str] = field(default_factory=list)
    sheriff_pk_speeches: list[dict[str, str]] = field(default_factory=list)
    sheriff_runoff_votes: dict[str, str] = field(default_factory=dict)
    sheriff_elected: str | None = None
    speech_order: list[str] = field(default_factory=list)
    speech_order_choice: str | None = None
    vote_weights: dict[str, float] = field(default_factory=dict)
    sheriff_badge_target: str | None = None
    sheriff_badge_lost: bool = False
    success: bool = False
    werewolf_self_exploded: str | None = None
    day_ended_by_self_explosion: bool = False
    interruption: StageInterruption | None = None
    sheriff_pre_election_bomb_count: int = 0
    sheriff_election_pending: bool = False
    sheriff_badge_lost_reason: str | None = None
    sheriff_election_resolution: SheriffElectionResolution | None = None
    sheriff_badge_resolution: SheriffBadgeResolution | None = None
    public_outcome_events: list[PublicOutcomeEventV1] = field(default_factory=list)
    public_outcome_next_sequence: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "players": self.players,
            "attacked": self.attacked,
            "eliminated": self.eliminated,
            "protected": self.protected,
            "investigated": self.investigated,
            "exiled": self.exiled,
            "night_deaths": [death.to_dict() for death in self.night_deaths],
            "werewolf_discussion": self.werewolf_discussion,
            "werewolf_vote_rounds": self.werewolf_vote_rounds,
            "day_deaths": [death.to_dict() for death in self.day_deaths],
            "saved_by_witch": self.saved_by_witch,
            "poisoned": self.poisoned,
            "hunter_shot": self.hunter_shot,
            "idiot_revealed": self.idiot_revealed,
            "debate": [entry.to_dict() for entry in self.debate],
            "bids": self.bids,
            "votes": self.votes,
            "exile_pk_candidates": self.exile_pk_candidates,
            "exile_pk_speeches": self.exile_pk_speeches,
            "exile_runoff_votes": self.exile_runoff_votes,
            "exile_resolution_reason": self.exile_resolution_reason,
            "summaries": self.summaries,
            "private_summaries": self.private_summaries,
            "public_summary": self.public_summary,
            "sheriff": self.sheriff,
            "sheriff_candidates": self.sheriff_candidates,
            "sheriff_speech_order": self.sheriff_speech_order,
            "sheriff_speech_direction": self.sheriff_speech_direction,
            "sheriff_speeches": self.sheriff_speeches,
            "sheriff_withdrawn": self.sheriff_withdrawn,
            "sheriff_final_candidates": self.sheriff_final_candidates,
            "sheriff_voters": self.sheriff_voters,
            "sheriff_votes": self.sheriff_votes,
            "sheriff_pk_candidates": self.sheriff_pk_candidates,
            "sheriff_pk_speeches": self.sheriff_pk_speeches,
            "sheriff_runoff_votes": self.sheriff_runoff_votes,
            "sheriff_elected": self.sheriff_elected,
            "speech_order": self.speech_order,
            "speech_order_choice": self.speech_order_choice,
            "vote_weights": self.vote_weights,
            "sheriff_badge_target": self.sheriff_badge_target,
            "sheriff_badge_lost": self.sheriff_badge_lost,
            "werewolf_self_exploded": self.werewolf_self_exploded,
            "day_ended_by_self_explosion": self.day_ended_by_self_explosion,
            "interruption": self.interruption.to_dict() if self.interruption else None,
            "sheriff_pre_election_bomb_count": self.sheriff_pre_election_bomb_count,
            "sheriff_election_pending": self.sheriff_election_pending,
            "sheriff_badge_lost_reason": self.sheriff_badge_lost_reason,
            "sheriff_election_resolution": (
                self.sheriff_election_resolution.to_dict()
                if self.sheriff_election_resolution
                else None
            ),
            "sheriff_badge_resolution": (
                self.sheriff_badge_resolution.to_dict() if self.sheriff_badge_resolution else None
            ),
            "public_outcome_events": [
                event.to_dict() for event in self.public_outcome_events
            ],
            "public_outcome_next_sequence": self.public_outcome_next_sequence,
            "success": self.success,
        }


@dataclass
class RoundLog:
    number: int
    eliminate: ActionLog | None = None
    protect: ActionLog | None = None
    investigate: ActionLog | None = None
    witch_save: ActionLog | None = None
    witch_poison: ActionLog | None = None
    hunter_shoot: ActionLog | None = None
    werewolf_discussion: list[ActionLog] = field(default_factory=list)
    werewolf_votes: list[list[ActionLog]] = field(default_factory=list)
    bid: list[list[ActionLog]] = field(default_factory=list)
    debate: list[ActionLog] = field(default_factory=list)
    votes: list[list[ActionLog]] = field(default_factory=list)
    exile_pk_speech: list[ActionLog] = field(default_factory=list)
    exile_runoff_votes: list[ActionLog] = field(default_factory=list)
    summaries: list[ActionLog] = field(default_factory=list)
    sheriff_run: list[ActionLog] = field(default_factory=list)
    sheriff_speech: list[ActionLog] = field(default_factory=list)
    sheriff_withdraw: list[ActionLog] = field(default_factory=list)
    sheriff_pk_speech: list[ActionLog] = field(default_factory=list)
    sheriff_runoff_votes: list[ActionLog] = field(default_factory=list)
    sheriff_votes: list[ActionLog] = field(default_factory=list)
    speech_order: ActionLog | None = None
    sheriff_badge: ActionLog | None = None
    werewolf_self_explosion: ActionLog | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "eliminate": self.eliminate.to_dict() if self.eliminate else None,
            "protect": self.protect.to_dict() if self.protect else None,
            "investigate": self.investigate.to_dict() if self.investigate else None,
            "witch_save": self.witch_save.to_dict() if self.witch_save else None,
            "witch_poison": self.witch_poison.to_dict() if self.witch_poison else None,
            "hunter_shoot": self.hunter_shoot.to_dict() if self.hunter_shoot else None,
            "werewolf_discussion": [log.to_dict() for log in self.werewolf_discussion],
            "werewolf_votes": [
                [log.to_dict() for log in vote_logs] for vote_logs in self.werewolf_votes
            ],
            "bid": [[log.to_dict() for log in turn] for turn in self.bid],
            "debate": [log.to_dict() for log in self.debate],
            "votes": [[log.to_dict() for log in vote_logs] for vote_logs in self.votes],
            "exile_pk_speech": [log.to_dict() for log in self.exile_pk_speech],
            "exile_runoff_votes": [log.to_dict() for log in self.exile_runoff_votes],
            "summaries": [log.to_dict() for log in self.summaries],
            "sheriff_run": [log.to_dict() for log in self.sheriff_run],
            "sheriff_speech": [log.to_dict() for log in self.sheriff_speech],
            "sheriff_withdraw": [log.to_dict() for log in self.sheriff_withdraw],
            "sheriff_pk_speech": [log.to_dict() for log in self.sheriff_pk_speech],
            "sheriff_runoff_votes": [log.to_dict() for log in self.sheriff_runoff_votes],
            "sheriff_votes": [log.to_dict() for log in self.sheriff_votes],
            "speech_order": self.speech_order.to_dict() if self.speech_order else None,
            "sheriff_badge": self.sheriff_badge.to_dict() if self.sheriff_badge else None,
            "werewolf_self_explosion": self.werewolf_self_explosion.to_dict()
            if self.werewolf_self_explosion
            else None,
        }


@dataclass
class GameState:
    session_id: str
    players: list[Player]
    rule_set: dict[str, Any] = field(default_factory=dict)
    rounds: list[RoundState] = field(default_factory=list)
    winner: str = ""
    error_message: str = ""
    sheriff: str | None = None
    sheriff_badge_lost: bool = False
    sheriff_pre_election_bomb_count: int = 0
    sheriff_election_pending: bool = False
    public_facts: list[dict[str, Any]] = field(default_factory=list)
    public_fact_opportunities: list[dict[str, Any]] = field(default_factory=list)
    public_fact_propositions: list[dict[str, Any]] = field(default_factory=list)

    def player_by_name(self) -> dict[str, Player]:
        return {player.name: player for player in self.players}

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "players": [player.to_dict() for player in self.players],
            "rule_set": self.rule_set,
            "rounds": [round_state.to_dict() for round_state in self.rounds],
            "winner": self.winner,
            "error_message": self.error_message,
            "sheriff": self.sheriff,
            "sheriff_badge_lost": self.sheriff_badge_lost,
            "sheriff_pre_election_bomb_count": self.sheriff_pre_election_bomb_count,
            "sheriff_election_pending": self.sheriff_election_pending,
            "public_facts": self.public_facts,
            "public_fact_opportunities": self.public_fact_opportunities,
            "public_fact_propositions": self.public_fact_propositions,
        }
