from __future__ import annotations

import copy
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
from app.werewolf.live import NullEventSink
from app.werewolf.lm import ModelProvider, generate_action
from app.werewolf.models import ActionLog, DebateEntry, GameState, GameView, Player, RoundLog, RoundState


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
    players = [seer, doctor, *werewolves, *villagers]
    current_players = [player.name for player in players]

    for player in players:
        other_wolf = None
        if player.role == WEREWOLF:
            other_wolf = next(wolf.name for wolf in werewolves if wolf.name != player.name)
        player.gamestate = GameView(
            round_number=1,
            current_players=current_players.copy(),
            other_wolf=other_wolf,
        )

    return GameState(session_id=session_id, players=players)


class GameEngine:
    def __init__(
        self,
        *,
        state: GameState,
        provider: ModelProvider,
        max_rounds: int,
        debate_turns: int = DEFAULT_DEBATE_TURNS,
        event_sink: object | None = None,
    ) -> None:
        self.state = state
        self.provider = provider
        self.max_rounds = max_rounds
        self.debate_turns = debate_turns
        self.event_sink = event_sink or NullEventSink()

    def run(self) -> list[RoundLog]:
        logs: list[RoundLog] = []
        active_players = [player.name for player in self.state.players]
        self.state.winner = self._get_winner(active_players)
        self._publish(
            "game_started",
            payload={
                "players": [player.to_dict() for player in self.state.players],
                "active_players": active_players.copy(),
            },
        )

        while not self.state.winner:
            if len(self.state.rounds) >= self.max_rounds:
                raise MaxRoundsExceeded("Maximum rounds exceeded before a winner was found.")

            round_number = len(self.state.rounds) + 1
            self._sync_game_views(active_players, round_number)
            round_state = RoundState(number=round_number, players=active_players.copy())
            round_log = RoundLog(number=round_number)
            self.state.rounds.append(round_state)
            logs.append(round_log)
            self._publish(
                "round_started",
                round_number=round_number,
                payload={"active_players": active_players.copy()},
            )

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
        self._publish(
            "phase_started",
            round_number=round_state.number,
            phase="night",
            payload={"active_players": active_players.copy()},
        )
        players_by_name = self.state.player_by_name()
        active_wolves = [
            name for name in active_players if players_by_name[name].role == WEREWOLF
        ]
        non_wolves = [
            name for name in active_players if players_by_name[name].role != WEREWOLF
        ]

        if active_wolves and non_wolves:
            wolf = players_by_name[active_wolves[0]]
            eliminated, round_log.eliminate = self._player_action(
                player=wolf,
                action="remove",
                options=non_wolves,
                result_key="remove",
                round_state=round_state,
                phase="night",
            )
            round_state.eliminated = eliminated

        if self._is_role_active(DOCTOR, active_players):
            doctor = players_by_name[self._active_player_for_role(DOCTOR, active_players)]
            protected, round_log.protect = self._player_action(
                player=doctor,
                action="protect",
                options=active_players,
                result_key="protect",
                round_state=round_state,
                phase="night",
            )
            round_state.protected = protected

        if self._is_role_active(SEER, active_players):
            seer = players_by_name[self._active_player_for_role(SEER, active_players)]
            investigate_options = [
                name
                for name in active_players
                if name != seer.name and name not in seer.known_roles
            ]
            investigated, round_log.investigate = self._player_action(
                player=seer,
                action="investigate",
                options=investigate_options,
                result_key="investigate",
                round_state=round_state,
                phase="night",
            )
            round_state.investigated = investigated
            if investigated:
                role = players_by_name[investigated].role
                seer.known_roles[investigated] = role
                seer.add_observation(f"第{round_state.number}轮：我查验了{investigated}，身份是{role}。")

        if round_state.eliminated and round_state.eliminated != round_state.protected:
            self._remove_player(active_players, round_state.eliminated)
            self._announce(active_players, f"第{round_state.number}轮：夜晚，{round_state.eliminated}出局。")
        else:
            self._announce(active_players, f"第{round_state.number}轮：夜晚无人出局。")
        self._publish_state_updated(
            round_state=round_state,
            phase="night",
            payload={
                "eliminated": round_state.eliminated,
                "protected": round_state.protected,
                "investigated": round_state.investigated,
                "active_players": active_players.copy(),
            },
        )

    def _run_day_phase(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        self._publish(
            "phase_started",
            round_number=round_state.number,
            phase="day",
            payload={"active_players": active_players.copy()},
        )
        previous_speaker = ""
        for _turn in range(min(self.debate_turns, len(active_players))):
            speaker, bid_logs, bids = self._get_next_speaker(
                active_players=active_players,
                previous_speaker=previous_speaker,
                round_state=round_state,
            )
            round_log.bid.append(bid_logs)
            round_state.bids.append(bids)
            previous_speaker = speaker

            player = self.state.player_by_name()[speaker]
            message, action_log = self._player_action(
                player=player,
                action="debate",
                options=[],
                result_key="say",
                round_state=round_state,
                phase="day",
            )
            if not isinstance(message, str) or not message:
                raise ValueError(f"{speaker} did not return a valid debate message.")

            entry = DebateEntry(speaker=speaker, message=message)
            round_state.debate.append(entry)
            round_log.debate.append(action_log)
            self._record_public_debate(active_players, entry)
            self._publish_state_updated(
                round_state=round_state,
                phase="day",
                actor=speaker,
                action="debate",
                payload={
                    "debate_entry": entry.to_dict(),
                    "debate": [debate_entry.to_dict() for debate_entry in round_state.debate],
                },
            )

        self._publish(
            "phase_started",
            round_number=round_state.number,
            phase="vote",
            payload={"active_players": active_players.copy()},
        )
        votes, vote_logs = self._run_voting(round_state, active_players)
        round_state.votes.append(votes)
        round_log.votes.append(vote_logs)
        self._publish_state_updated(
            round_state=round_state,
            phase="vote",
            action="vote",
            payload={"votes": votes},
        )

        exiled = self._majority_vote(votes, len(active_players))
        if exiled:
            round_state.exiled = exiled
            self._remove_player(active_players, exiled)
            self._announce(active_players, f"第{round_state.number}轮：白天投票，{exiled}被放逐。")
        else:
            self._announce(active_players, f"第{round_state.number}轮：白天投票未形成多数，无人被放逐。")
        self._publish_state_updated(
            round_state=round_state,
            phase="vote",
            payload={
                "exiled": round_state.exiled,
                "active_players": active_players.copy(),
            },
        )

        self._run_summaries(round_state, round_log, active_players)

    def _get_next_speaker(
        self,
        *,
        active_players: list[str],
        previous_speaker: str,
        round_state: RoundState,
    ) -> tuple[str, list[ActionLog], dict[str, int]]:
        bid_logs: list[ActionLog] = []
        bids: dict[str, int] = {}
        players_by_name = self.state.player_by_name()

        for name in active_players:
            if name == previous_speaker:
                continue
            player = players_by_name[name]
            bid, action_log = self._player_action(
                player=player,
                action="bid",
                options=["0", "1", "2", "3", "4"],
                result_key="bid",
                round_state=round_state,
                phase="day",
            )
            bid_value = int(bid)
            bids[name] = bid_value
            player.bidding_rationale = (
                action_log.lm_log.result.get("reasoning", "") if action_log.lm_log.result else ""
            )
            bid_logs.append(action_log)

        speaker = sorted(bids.items(), key=lambda item: (-item[1], item[0]))[0][0]
        return speaker, bid_logs, bids

    def _run_voting(
        self,
        round_state: RoundState,
        active_players: list[str],
    ) -> tuple[dict[str, str], list[ActionLog]]:
        votes: dict[str, str] = {}
        logs: list[ActionLog] = []
        players_by_name = self.state.player_by_name()
        for voter in active_players:
            vote, action_log = self._player_action(
                player=players_by_name[voter],
                action="vote",
                options=[name for name in active_players if name != voter],
                result_key="vote",
                round_state=round_state,
                phase="vote",
            )
            if not isinstance(vote, str) or not vote:
                raise ValueError(f"{voter} did not return a valid vote.")
            votes[voter] = vote
            logs.append(action_log)
        return votes, logs

    def _run_summaries(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        self._publish(
            "phase_started",
            round_number=round_state.number,
            phase="summary",
            payload={"active_players": active_players.copy()},
        )
        players_by_name = self.state.player_by_name()
        for name in active_players:
            player = players_by_name[name]
            summary, action_log = self._player_action(
                player=player,
                action="summarize",
                options=[],
                result_key="summary",
                round_state=round_state,
                phase="summary",
            )
            if isinstance(summary, str) and summary:
                round_state.summaries[name] = summary
                player.add_observation(f"第{round_state.number}轮总结：{summary}")
            round_log.summaries.append(action_log)
            self._publish_state_updated(
                round_state=round_state,
                phase="summary",
                actor=name,
                action="summarize",
                payload={"summaries": round_state.summaries.copy()},
            )

    def _player_action(
        self,
        *,
        player: Player,
        action: str,
        options: list[str],
        result_key: str,
        round_state: RoundState,
        phase: str,
    ) -> tuple[object | None, ActionLog]:
        world_state = self._world_state(player, options, round_state)
        self._publish(
            "action_requested",
            round_number=round_state.number,
            phase=phase,
            actor=player.name,
            action=action,
            payload={"options": options.copy(), "result_key": result_key},
        )
        self._publish(
            "model_request_started",
            round_number=round_state.number,
            phase=phase,
            actor=player.name,
            action=action,
            payload={"model": player.model, "world_state": copy.deepcopy(world_state)},
        )
        value, lm_log = generate_action(
            provider=self.provider,
            action=action,
            world_state=world_state,
            model=player.model,
            allowed_values=options if options else None,
            result_key=result_key,
        )
        action_log = ActionLog(
            actor=player.name,
            action=action,
            options=options,
            choice=str(value) if value is not None else None,
            lm_log=lm_log,
        )
        self._publish(
            "model_response_received",
            round_number=round_state.number,
            phase=phase,
            actor=player.name,
            action=action,
            payload={"prompt": lm_log.prompt, "raw_response": lm_log.raw_response},
        )
        self._publish(
            "action_parsed",
            round_number=round_state.number,
            phase=phase,
            actor=player.name,
            action=action,
            payload={
                "choice": action_log.choice,
                "result": lm_log.result,
                "options": options.copy(),
            },
        )
        if options and value not in options:
            raise ValueError(f"{player.name} returned invalid {action}: {value}")
        return value, action_log

    def _publish(
        self,
        event_type: str,
        *,
        round_number: int | None = None,
        phase: str | None = None,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        self.event_sink.publish(
            event_type,
            round_number=round_number,
            phase=phase,
            actor=actor,
            action=action,
            payload=payload,
        )

    def _publish_state_updated(
        self,
        *,
        round_state: RoundState,
        phase: str,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        self._publish(
            "state_updated",
            round_number=round_state.number,
            phase=phase,
            actor=actor,
            action=action,
            payload=payload,
        )

    def _world_state(
        self,
        player: Player,
        options: list[str],
        round_state: RoundState,
    ) -> dict[str, object]:
        active_players = player.gamestate.current_players if player.gamestate else round_state.players
        debate = [f"{entry.speaker}：{entry.message}" for entry in round_state.debate]
        return {
            "name": player.name,
            "role": player.role,
            "round": round_state.number,
            "observations": player.observations,
            "remaining_players": "、".join(active_players),
            "debate": debate,
            "bidding_rationale": player.bidding_rationale,
            "personality": "",
            "num_players": 8,
            "num_villagers": 4,
            "werewolf_context": self._werewolf_context(player, active_players),
            "debate_turns_left": max(0, self.debate_turns - len(round_state.debate)),
            "options": "、".join(options),
        }

    def _werewolf_context(self, player: Player, active_players: list[str]) -> str:
        if player.role != WEREWOLF or not player.gamestate or not player.gamestate.other_wolf:
            return ""
        other_wolf = player.gamestate.other_wolf
        if other_wolf in active_players:
            return f"你的狼人队友是{other_wolf}。"
        return f"你的狼人队友{other_wolf}已经出局，只剩你独自行动。"

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
            (name for name in active_players if players_by_name[name].role == role),
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
        self._sync_game_views(active_players, len(self.state.rounds))

    def _announce(self, active_players: list[str], announcement: str) -> None:
        players_by_name = self.state.player_by_name()
        for name in active_players:
            players_by_name[name].add_observation(announcement)

    def _record_public_debate(self, active_players: list[str], entry: DebateEntry) -> None:
        players_by_name = self.state.player_by_name()
        for name in active_players:
            if players_by_name[name].gamestate:
                players_by_name[name].gamestate.debate.append(entry)

    def _sync_game_views(self, active_players: list[str], round_number: int) -> None:
        for player in self.state.players:
            if player.gamestate:
                player.gamestate.round_number = round_number
                player.gamestate.current_players = active_players.copy()
                if player.name not in active_players:
                    player.gamestate.debate = []
