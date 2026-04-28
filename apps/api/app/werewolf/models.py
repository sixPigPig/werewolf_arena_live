from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from app.werewolf.lm import LmLog


@dataclass
class ActionLog:
    actor: str
    action: str
    options: list[str]
    choice: str | None
    lm_log: LmLog

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "action": self.action,
            "options": self.options,
            "choice": self.choice,
            "lm_log": self.lm_log.to_dict(),
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "round_number": self.round_number,
            "current_players": self.current_players,
            "debate": [entry.to_dict() for entry in self.debate],
            "other_wolf": self.other_wolf,
        }


@dataclass
class Player:
    name: str
    role: str
    model: str
    observations: list[str] = field(default_factory=list)
    bidding_rationale: str = ""
    gamestate: GameView | None = None
    known_roles: dict[str, str] = field(default_factory=dict)

    def add_observation(self, observation: str) -> None:
        self.observations.append(observation)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "model": self.model,
            "observations": self.observations,
            "bidding_rationale": self.bidding_rationale,
            "gamestate": self.gamestate.to_dict() if self.gamestate else None,
            "known_roles": self.known_roles,
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
    debate: list[DebateEntry] = field(default_factory=list)
    bids: list[dict[str, int]] = field(default_factory=list)
    votes: list[dict[str, str]] = field(default_factory=list)
    summaries: dict[str, str] = field(default_factory=dict)
    success: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "players": self.players,
            "attacked": self.attacked,
            "eliminated": self.eliminated,
            "protected": self.protected,
            "investigated": self.investigated,
            "exiled": self.exiled,
            "debate": [entry.to_dict() for entry in self.debate],
            "bids": self.bids,
            "votes": self.votes,
            "summaries": self.summaries,
            "success": self.success,
        }


@dataclass
class RoundLog:
    number: int
    eliminate: ActionLog | None = None
    protect: ActionLog | None = None
    investigate: ActionLog | None = None
    bid: list[list[ActionLog]] = field(default_factory=list)
    debate: list[ActionLog] = field(default_factory=list)
    votes: list[list[ActionLog]] = field(default_factory=list)
    summaries: list[ActionLog] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "eliminate": self.eliminate.to_dict() if self.eliminate else None,
            "protect": self.protect.to_dict() if self.protect else None,
            "investigate": self.investigate.to_dict() if self.investigate else None,
            "bid": [[log.to_dict() for log in turn] for turn in self.bid],
            "debate": [log.to_dict() for log in self.debate],
            "votes": [[log.to_dict() for log in vote_logs] for vote_logs in self.votes],
            "summaries": [log.to_dict() for log in self.summaries],
        }


@dataclass
class GameState:
    session_id: str
    players: list[Player]
    rule_set: dict[str, Any] = field(default_factory=dict)
    rounds: list[RoundState] = field(default_factory=list)
    winner: str = ""
    error_message: str = ""

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
        }
