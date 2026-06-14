from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.werewolf.lm import LmLog


@dataclass
class DeathEvent:
    player: str
    cause: str
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"player": self.player, "cause": self.cause, "source": self.source}


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

    def to_dict(self) -> dict[str, Any]:
        return {
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
    sheriff_pre_election_bomb_count: int = 0
    sheriff_election_pending: bool = False
    sheriff_badge_lost_reason: str | None = None

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
            "sheriff_pre_election_bomb_count": self.sheriff_pre_election_bomb_count,
            "sheriff_election_pending": self.sheriff_election_pending,
            "sheriff_badge_lost_reason": self.sheriff_badge_lost_reason,
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
        }
