from __future__ import annotations

from collections import Counter

from app.werewolf.config import (
    DEFAULT_DEBATE_TURNS,
    DOCTOR,
    SEER,
    VILLAGER,
    WEREWOLF,
    WINNER_VILLAGERS,
    WINNER_WEREWOLVES,
    choose_player_names,
)
from app.werewolf.local_ai import LocalModel
from app.werewolf.models import DebateEntry, GameState, Player, RoundLog, RoundState


class MaxRoundsExceeded(RuntimeError):
    pass


def initialize_game_state(
    *,
    session_id: str,
    villager_model: str,
    werewolf_model: str,
    seed: int | None,
) -> GameState:
    player_names = choose_player_names(seed)
    seer = Player(player_names[0], SEER, villager_model)
    doctor = Player(player_names[1], DOCTOR, villager_model)
    werewolves = [
        Player(player_names[2], WEREWOLF, werewolf_model),
        Player(player_names[3], WEREWOLF, werewolf_model),
    ]
    villagers = [Player(name, VILLAGER, villager_model) for name in player_names[4:]]
    return GameState(session_id=session_id, players=[seer, doctor, *werewolves, *villagers])


class GameEngine:
    def __init__(
        self,
        *,
        state: GameState,
        local_model: LocalModel | None = None,
        max_rounds: int,
        debate_turns: int = DEFAULT_DEBATE_TURNS,
    ) -> None:
        self.state = state
        self.local_model = local_model or LocalModel()
        self.max_rounds = max_rounds
        self.debate_turns = debate_turns
        self._seen_by_seer: set[str] = set()

    def run(self) -> list[RoundLog]:
        logs: list[RoundLog] = []
        active_players = [player.name for player in self.state.players]
        self.state.winner = self._get_winner(active_players)

        while not self.state.winner:
            if len(self.state.rounds) >= self.max_rounds:
                raise MaxRoundsExceeded("Maximum rounds exceeded before a winner was found.")

            round_number = len(self.state.rounds) + 1
            round_state = RoundState(number=round_number, players=active_players.copy())
            round_log = RoundLog(number=round_number)
            self.state.rounds.append(round_state)
            logs.append(round_log)

            self._run_night_phase(round_state, round_log, active_players)
            self.state.winner = self._get_winner(active_players)
            if self.state.winner:
                round_state.success = True
                break

            self._run_day_phase(round_state, round_log, active_players)
            self.state.winner = self._get_winner(active_players)
            round_state.success = True

        return logs

    def _run_night_phase(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        players_by_name = self.state.player_by_name()
        active_wolves = [
            name for name in active_players if players_by_name[name].role == WEREWOLF
        ]
        non_wolves = [
            name for name in active_players if players_by_name[name].role != WEREWOLF
        ]

        if active_wolves and non_wolves:
            eliminated, round_log.eliminate = self.local_model.choose(
                actor=active_wolves[0],
                action="eliminate",
                options=non_wolves,
                round_number=round_state.number,
            )
            round_state.eliminated = eliminated

        if self._is_role_active(DOCTOR, active_players):
            doctor = self._active_player_for_role(DOCTOR, active_players)
            protected, round_log.protect = self.local_model.choose(
                actor=doctor,
                action="protect",
                options=active_players,
                round_number=round_state.number,
            )
            round_state.protected = protected

        if self._is_role_active(SEER, active_players):
            seer = self._active_player_for_role(SEER, active_players)
            investigate_options = [
                name
                for name in active_players
                if name != seer and name not in self._seen_by_seer
            ]
            investigated, round_log.investigate = self.local_model.choose(
                actor=seer,
                action="investigate",
                options=investigate_options,
                round_number=round_state.number,
            )
            round_state.investigated = investigated
            if investigated:
                self._seen_by_seer.add(investigated)

        if round_state.eliminated and round_state.eliminated != round_state.protected:
            self._remove_player(active_players, round_state.eliminated)
            self._announce(active_players, f"{round_state.eliminated} was removed overnight.")
        else:
            self._announce(active_players, "No one was removed overnight.")

    def _run_day_phase(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        for speaker in active_players[: self.debate_turns]:
            message, log = self.local_model.speak(
                actor=speaker,
                options=active_players,
                round_number=round_state.number,
            )
            round_state.debate.append(DebateEntry(speaker=speaker, message=message))
            round_log.debate.append(log)

        votes: dict[str, str] = {}
        for voter in active_players:
            voted_for, vote_log = self.local_model.choose(
                actor=voter,
                action="vote",
                options=[name for name in active_players if name != voter],
                round_number=round_state.number,
            )
            if voted_for:
                votes[voter] = voted_for
            round_log.votes.append(vote_log)

        round_state.votes.append(votes)
        exiled = self._majority_vote(votes, len(active_players))
        if exiled:
            round_state.exiled = exiled
            self._remove_player(active_players, exiled)
            self._announce(active_players, f"{exiled} was exiled by vote.")

    def _get_winner(self, active_players: list[str]) -> str:
        players_by_name = self.state.player_by_name()
        active_wolves = [
            name for name in active_players if players_by_name[name].role == WEREWOLF
        ]
        active_villagers = [name for name in active_players if name not in active_wolves]

        if not active_wolves:
            return WINNER_VILLAGERS
        if len(active_wolves) >= len(active_villagers):
            return WINNER_WEREWOLVES
        return ""

    def _is_role_active(self, role: str, active_players: list[str]) -> bool:
        return bool(self._active_player_for_role(role, active_players))

    def _active_player_for_role(self, role: str, active_players: list[str]) -> str:
        players_by_name = self.state.player_by_name()
        return next(
            (
                name
                for name in active_players
                if players_by_name[name].role == role
            ),
            "",
        )

    def _majority_vote(self, votes: dict[str, str], active_player_count: int) -> str | None:
        if not votes:
            return None

        voted_for, count = sorted(
            Counter(votes.values()).items(),
            key=lambda item: (-item[1], item[0]),
        )[0]
        if count > active_player_count / 2:
            return voted_for
        return None

    def _remove_player(self, active_players: list[str], player: str) -> None:
        if player in active_players:
            active_players.remove(player)

    def _announce(self, active_players: list[str], announcement: str) -> None:
        players_by_name = self.state.player_by_name()
        for name in active_players:
            players_by_name[name].add_observation(announcement)
