from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ActionLog:
    actor: str
    action: str
    options: list[str]
    choice: str | None
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DebateEntry:
    speaker: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class Player:
    name: str
    role: str
    model: str
    observations: list[str] = field(default_factory=list)

    def add_observation(self, observation: str) -> None:
        self.observations.append(observation)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RoundState:
    number: int
    players: list[str]
    eliminated: str | None = None
    protected: str | None = None
    investigated: str | None = None
    exiled: str | None = None
    debate: list[DebateEntry] = field(default_factory=list)
    votes: list[dict[str, str]] = field(default_factory=list)
    success: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "players": self.players,
            "eliminated": self.eliminated,
            "protected": self.protected,
            "investigated": self.investigated,
            "exiled": self.exiled,
            "debate": [entry.to_dict() for entry in self.debate],
            "votes": self.votes,
            "success": self.success,
        }


@dataclass
class RoundLog:
    number: int
    eliminate: ActionLog | None = None
    protect: ActionLog | None = None
    investigate: ActionLog | None = None
    debate: list[ActionLog] = field(default_factory=list)
    votes: list[ActionLog] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "eliminate": self.eliminate.to_dict() if self.eliminate else None,
            "protect": self.protect.to_dict() if self.protect else None,
            "investigate": self.investigate.to_dict() if self.investigate else None,
            "debate": [log.to_dict() for log in self.debate],
            "votes": [log.to_dict() for log in self.votes],
        }


@dataclass
class GameState:
    session_id: str
    players: list[Player]
    rounds: list[RoundState] = field(default_factory=list)
    winner: str = ""
    error_message: str = ""

    def player_by_name(self) -> dict[str, Player]:
        return {player.name: player for player in self.players}

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "players": [player.to_dict() for player in self.players],
            "rounds": [round_state.to_dict() for round_state in self.rounds],
            "winner": self.winner,
            "error_message": self.error_message,
        }
