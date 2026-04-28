from __future__ import annotations

import copy
from collections import Counter

from app.werewolf.config import (
    DEFAULT_DEBATE_TURNS,
    DOCTOR,
    HUNTER,
    IDIOT,
    SEER,
    WITCH,
    WINNER_VILLAGERS,
    WINNER_WEREWOLVES,
    choose_player_names,
)
from app.werewolf.live import NullEventSink
from app.werewolf.lm import ModelProvider, generate_action
from app.werewolf.models import (
    ActionLog,
    DeathEvent,
    DebateEntry,
    GameState,
    GameView,
    Player,
    RoundLog,
    RoundState,
)
from app.werewolf.rules import (
    ACTION_DEBATE,
    ACTION_SHERIFF_BADGE,
    ACTION_SHERIFF_RUN,
    ACTION_SHERIFF_VOTE,
    ACTION_INVESTIGATE,
    ACTION_HUNTER_SHOOT,
    ACTION_PROTECT,
    ACTION_REMOVE,
    ACTION_SPEECH_ORDER,
    ACTION_WITCH_POISON,
    ACTION_WITCH_SAVE,
    MODEL_GROUP_WEREWOLF,
    ROLE_CATEGORY_CIVILIAN,
    ROLE_CATEGORY_GOD,
    SPEECH_POLICY_SHERIFF_DIRECTED,
    TEAM_WEREWOLVES,
    WIN_CONDITION_SLAUGHTER_SIDE,
    RuleSet,
    render_rule_text,
    role_category,
    rule_set_snapshot,
)


class MaxRoundsExceeded(RuntimeError):
    pass


NO_WITCH_SAVE = "不使用解药"
NO_WITCH_POISON = "不使用毒药"
NO_HUNTER_SHOT = "不发动技能"
SHERIFF_RUN = "上警"
SHERIFF_SKIP = "不上警"
SPEECH_FROM_LEFT = "警左发言"
SPEECH_FROM_RIGHT = "警右发言"
SHERIFF_BADGE_DESTROY = "撕毁警徽"


def initialize_game_state(
    *,
    session_id: str,
    villager_model: str,
    werewolf_model: str,
    seed: int | None,
    rule_set: RuleSet,
) -> GameState:
    player_names = choose_player_names(seed, player_count=rule_set.player_count)
    players: list[Player] = []
    name_index = 0
    for role_spec in rule_set.roles:
        model = werewolf_model if role_spec.model_group == MODEL_GROUP_WEREWOLF else villager_model
        for _ in range(role_spec.count):
            player = Player(player_names[name_index], role_spec.role, model)
            if role_spec.role == WITCH:
                player.witch_antidote_available = True
                player.witch_poison_available = True
            elif role_spec.role == HUNTER:
                player.hunter_can_shoot = True
            players.append(player)
            name_index += 1

    werewolves = [player for player in players if _role_team(rule_set, player.role) == TEAM_WEREWOLVES]
    current_players = [player.name for player in players]

    for player in players:
        wolf_teammates: list[str] = []
        if _role_team(rule_set, player.role) == TEAM_WEREWOLVES and len(werewolves) > 1:
            wolf_teammates = [wolf.name for wolf in werewolves if wolf.name != player.name]
        other_wolf = wolf_teammates[0] if wolf_teammates else None
        player.gamestate = GameView(
            round_number=1,
            current_players=current_players.copy(),
            other_wolf=other_wolf,
            wolf_teammates=wolf_teammates,
        )

    return GameState(session_id=session_id, players=players, rule_set=rule_set_snapshot(rule_set))


def _role_team(rule_set: RuleSet, role: str) -> str:
    return next(role_spec.team for role_spec in rule_set.roles if role_spec.role == role)


class GameEngine:
    def __init__(
        self,
        *,
        state: GameState,
        provider: ModelProvider,
        max_rounds: int,
        rule_set: RuleSet,
        debate_turns: int = DEFAULT_DEBATE_TURNS,
        event_sink: object | None = None,
    ) -> None:
        self.state = state
        self.provider = provider
        self.max_rounds = max_rounds
        self.rule_set = rule_set
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
        active_wolves = [name for name in active_players if self._is_werewolf(players_by_name[name])]
        non_wolves = [
            name for name in active_players if not self._is_werewolf(players_by_name[name])
        ]

        if ACTION_REMOVE in self.rule_set.night_actions and active_wolves and non_wolves:
            wolf = players_by_name[active_wolves[0]]
            attacked, round_log.eliminate = self._player_action(
                player=wolf,
                action=ACTION_REMOVE,
                options=non_wolves,
                result_key=ACTION_REMOVE,
                round_state=round_state,
                phase="night",
            )
            round_state.attacked = str(attacked) if attacked is not None else None

        if ACTION_PROTECT in self.rule_set.night_actions and self._is_role_active(DOCTOR, active_players):
            doctor = players_by_name[self._active_player_for_role(DOCTOR, active_players)]
            protected, round_log.protect = self._player_action(
                player=doctor,
                action=ACTION_PROTECT,
                options=active_players,
                result_key=ACTION_PROTECT,
                round_state=round_state,
                phase="night",
            )
            round_state.protected = protected

        if ACTION_INVESTIGATE in self.rule_set.night_actions and self._is_role_active(SEER, active_players):
            seer = players_by_name[self._active_player_for_role(SEER, active_players)]
            investigate_options = [
                name
                for name in active_players
                if name != seer.name and name not in seer.known_roles
            ]
            if investigate_options:
                investigated, round_log.investigate = self._player_action(
                    player=seer,
                    action=ACTION_INVESTIGATE,
                    options=investigate_options,
                    result_key=ACTION_INVESTIGATE,
                    round_state=round_state,
                    phase="night",
                )
                round_state.investigated = investigated
                if investigated:
                    role = players_by_name[investigated].role
                    seer.known_roles[investigated] = role
                    seer.add_observation(f"第{round_state.number}轮：我查验了{investigated}，身份是{role}。")

        self._run_witch_phase(round_state, round_log, active_players)
        self._resolve_night_deaths(round_state, round_log, active_players)

        if round_state.night_deaths:
            eliminated_names = "、".join(death.player for death in round_state.night_deaths)
            self._announce(active_players, f"第{round_state.number}轮：夜晚，{eliminated_names}出局。")
        else:
            self._announce(active_players, f"第{round_state.number}轮：夜晚无人出局。")
        self._publish_state_updated(
            round_state=round_state,
            phase="night",
            payload={
                "attacked": round_state.attacked,
                "eliminated": round_state.eliminated,
                "protected": round_state.protected,
                "investigated": round_state.investigated,
                "saved_by_witch": round_state.saved_by_witch,
                "poisoned": round_state.poisoned,
                "night_deaths": [death.to_dict() for death in round_state.night_deaths],
                "active_players": active_players.copy(),
            },
        )

    def _run_witch_phase(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        if (
            ACTION_WITCH_SAVE not in self.rule_set.night_actions
            and ACTION_WITCH_POISON not in self.rule_set.night_actions
        ):
            return

        players_by_name = self.state.player_by_name()
        witch_name = self._active_player_for_role(WITCH, active_players)
        if not witch_name:
            return
        witch = players_by_name[witch_name]

        used_antidote = False
        if (
            ACTION_WITCH_SAVE in self.rule_set.night_actions
            and round_state.attacked
            and witch.witch_antidote_available
        ):
            save_choice, round_log.witch_save = self._player_action(
                player=witch,
                action=ACTION_WITCH_SAVE,
                options=[round_state.attacked, NO_WITCH_SAVE],
                result_key="save",
                round_state=round_state,
                phase="night",
            )
            if save_choice == round_state.attacked:
                round_state.saved_by_witch = round_state.attacked
                witch.witch_antidote_available = False
                used_antidote = True

        if (
            used_antidote
            or ACTION_WITCH_POISON not in self.rule_set.night_actions
            or not witch.witch_poison_available
        ):
            return

        poison_options = [
            name
            for name in active_players
            if name != witch.name and name != round_state.attacked
        ] + [NO_WITCH_POISON]
        if poison_options == [NO_WITCH_POISON]:
            return

        poison_choice, round_log.witch_poison = self._player_action(
            player=witch,
            action=ACTION_WITCH_POISON,
            options=poison_options,
            result_key="poison",
            round_state=round_state,
            phase="night",
        )
        if poison_choice and poison_choice != NO_WITCH_POISON:
            round_state.poisoned = str(poison_choice)
            witch.witch_poison_available = False

    def _resolve_night_deaths(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        deaths: list[DeathEvent] = []
        if (
            round_state.attacked
            and round_state.attacked != round_state.protected
            and round_state.attacked != round_state.saved_by_witch
        ):
            deaths.append(DeathEvent(round_state.attacked, "werewolf_attack", "狼人"))

        witch_name = self._active_player_for_role(WITCH, active_players)
        if round_state.poisoned:
            deaths.append(DeathEvent(round_state.poisoned, "witch_poison", witch_name or None))

        pending_night_deaths = {death.player for death in deaths}
        seen: set[str] = set()
        for death in deaths:
            if death.player in seen:
                continue
            seen.add(death.player)
            round_state.night_deaths.append(death)
            self._remove_player(active_players, death.player)
            self._maybe_run_hunter_shot(
                dead_player=death.player,
                death_cause=death.cause,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase="night",
                excluded_shot_targets=pending_night_deaths,
                excluded_badge_targets=pending_night_deaths,
            )
            self._maybe_transfer_sheriff_badge(
                dead_player=death.player,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase="night",
                excluded_badge_targets=pending_night_deaths,
            )

        round_state.eliminated = round_state.night_deaths[0].player if round_state.night_deaths else None

    def _maybe_run_hunter_shot(
        self,
        *,
        dead_player: str,
        death_cause: str,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        phase: str,
        excluded_shot_targets: set[str] | None = None,
        excluded_badge_targets: set[str] | None = None,
    ) -> None:
        players_by_name = self.state.player_by_name()
        hunter = players_by_name[dead_player]
        if hunter.role != HUNTER or not hunter.hunter_can_shoot:
            return
        if death_cause == "witch_poison":
            return

        excluded_shot_targets = excluded_shot_targets or set()
        options = [
            name
            for name in active_players
            if name != hunter.name and name not in excluded_shot_targets
        ] + [NO_HUNTER_SHOT]
        if options == [NO_HUNTER_SHOT]:
            return

        shot, action_log = self._player_action(
            player=hunter,
            action=ACTION_HUNTER_SHOOT,
            options=options,
            result_key="shoot",
            round_state=round_state,
            phase=phase,
        )
        round_log.hunter_shoot = action_log
        hunter.hunter_can_shoot = False
        if shot and shot != NO_HUNTER_SHOT:
            shot_player = str(shot)
            round_state.hunter_shot = shot_player
            self._remove_player(active_players, shot_player)
            death = DeathEvent(shot_player, "hunter_shot", hunter.name)
            if phase == "night":
                round_state.night_deaths.append(death)
            else:
                round_state.day_deaths.append(death)
            self._maybe_transfer_sheriff_badge(
                dead_player=shot_player,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase=phase,
                excluded_badge_targets=excluded_badge_targets,
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
        self._run_sheriff_election_if_needed(round_state, round_log, active_players)
        self._run_debate_phase(round_state, round_log, active_players)

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

        exiled = self._majority_vote(votes, active_players, round_state.vote_weights)
        if exiled:
            self._resolve_day_exile(exiled, round_state, round_log, active_players)
        else:
            self._announce(active_players, f"第{round_state.number}轮：白天投票未形成多数，无人被放逐。")
        self._publish_state_updated(
            round_state=round_state,
            phase="vote",
            payload={
                "exiled": round_state.exiled,
                "day_deaths": [death.to_dict() for death in round_state.day_deaths],
                "hunter_shot": round_state.hunter_shot,
                "idiot_revealed": round_state.idiot_revealed,
                "active_players": active_players.copy(),
            },
        )

        self._run_summaries(round_state, round_log, active_players)

    def _run_debate_phase(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        speech_order = self._speech_order(round_state, round_log, active_players)
        round_state.speech_order = speech_order
        players_by_name = self.state.player_by_name()

        for speaker in speech_order:
            player = players_by_name[speaker]
            message, action_log = self._player_action(
                player=player,
                action=ACTION_DEBATE,
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
                action=ACTION_DEBATE,
                payload={
                    "debate_entry": entry.to_dict(),
                    "debate": [debate_entry.to_dict() for debate_entry in round_state.debate],
                    "speech_order": round_state.speech_order.copy(),
                },
            )

    def _speech_order(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> list[str]:
        if (
            self.rule_set.speech_policy == SPEECH_POLICY_SHERIFF_DIRECTED
            and self.state.sheriff
            and self.state.sheriff in active_players
        ):
            return self._sheriff_directed_speech_order(round_state, round_log, active_players)
        return active_players.copy()

    def _run_sheriff_election_if_needed(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        round_state.sheriff = self.state.sheriff
        if not self.rule_set.sheriff_enabled or round_state.number != 1 or self.state.sheriff:
            return

        players_by_name = self.state.player_by_name()
        candidates: list[str] = []
        for name in active_players:
            run_choice, action_log = self._player_action(
                player=players_by_name[name],
                action=ACTION_SHERIFF_RUN,
                options=[SHERIFF_RUN, SHERIFF_SKIP],
                result_key="run",
                round_state=round_state,
                phase="day",
            )
            round_log.sheriff_run.append(action_log)
            if run_choice == SHERIFF_RUN:
                candidates.append(name)

        round_state.sheriff_candidates = candidates
        if not candidates:
            self._announce(active_players, f"第{round_state.number}轮：无人上警，本局暂时没有警长。")
            return

        for name in active_players:
            vote, action_log = self._player_action(
                player=players_by_name[name],
                action=ACTION_SHERIFF_VOTE,
                options=candidates,
                result_key="sheriff_vote",
                round_state=round_state,
                phase="day",
            )
            round_log.sheriff_votes.append(action_log)
            if isinstance(vote, str) and vote in candidates:
                round_state.sheriff_votes[name] = vote

        sheriff = self._plurality_winner(round_state.sheriff_votes)
        if sheriff is None:
            self._announce(active_players, f"第{round_state.number}轮：警长投票未产生唯一领先者，本局暂时没有警长。")
            return

        self._set_sheriff(sheriff)
        round_state.sheriff = sheriff
        self._announce(
            active_players,
            f"第{round_state.number}轮：警长竞选，{sheriff}当选警长，投票计为{self.rule_set.sheriff_vote_weight:g}票。",
        )

    def _sheriff_directed_speech_order(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> list[str]:
        sheriff = self.state.sheriff
        if sheriff not in active_players:
            return active_players.copy()

        players_by_name = self.state.player_by_name()
        choice, action_log = self._player_action(
            player=players_by_name[sheriff],
            action=ACTION_SPEECH_ORDER,
            options=[SPEECH_FROM_LEFT, SPEECH_FROM_RIGHT],
            result_key="speech_order",
            round_state=round_state,
            phase="day",
        )
        round_log.speech_order = action_log
        round_state.speech_order_choice = str(choice) if choice else None

        sheriff_index = active_players.index(sheriff)
        before_sheriff = active_players[:sheriff_index]
        after_sheriff = active_players[sheriff_index + 1 :]
        if choice == SPEECH_FROM_RIGHT:
            return list(reversed(before_sheriff)) + list(reversed(after_sheriff)) + [sheriff]
        return after_sheriff + before_sheriff + [sheriff]

    def _plurality_winner(self, votes: dict[str, str]) -> str | None:
        if not votes:
            return None
        tally = Counter(votes.values())
        top_count = max(tally.values())
        winners = [name for name, count in tally.items() if count == top_count]
        return winners[0] if len(winners) == 1 else None

    def _set_sheriff(self, sheriff: str | None) -> None:
        players_by_name = self.state.player_by_name()
        for player in players_by_name.values():
            player.is_sheriff = player.name == sheriff
        self.state.sheriff = sheriff
        if sheriff:
            self.state.sheriff_badge_lost = False

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
        for voter in self._eligible_voters(active_players):
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
            round_state.vote_weights[voter] = self._vote_weight(voter)
            logs.append(action_log)
        return votes, logs

    def _vote_weight(self, voter: str) -> float:
        if self.rule_set.sheriff_enabled and voter == self.state.sheriff:
            return self.rule_set.sheriff_vote_weight
        return 1.0

    def _resolve_day_exile(
        self,
        exiled: str,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        player = self.state.player_by_name()[exiled]
        if player.role == IDIOT and not player.revealed_role:
            player.revealed_role = True
            player.can_vote = False
            round_state.idiot_revealed = exiled
            self._announce(
                active_players,
                f"第{round_state.number}轮：白天投票，{exiled}翻开白痴身份，免于出局但失去投票权。",
            )
            return

        round_state.exiled = exiled
        self._remove_player(active_players, exiled)
        round_state.day_deaths.append(DeathEvent(exiled, "vote_exile", "投票"))
        self._announce(active_players, f"第{round_state.number}轮：白天投票，{exiled}被放逐。")
        self._maybe_run_hunter_shot(
            dead_player=exiled,
            death_cause="vote_exile",
            round_state=round_state,
            round_log=round_log,
            active_players=active_players,
            phase="vote",
        )
        self._maybe_transfer_sheriff_badge(
            dead_player=exiled,
            round_state=round_state,
            round_log=round_log,
            active_players=active_players,
            phase="vote",
        )

    def _maybe_transfer_sheriff_badge(
        self,
        *,
        dead_player: str,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        phase: str,
        excluded_badge_targets: set[str] | None = None,
    ) -> None:
        if (
            not self.rule_set.sheriff_enabled
            or dead_player != self.state.sheriff
            or self.state.sheriff_badge_lost
        ):
            return

        if not active_players:
            self._set_sheriff(None)
            self.state.sheriff_badge_lost = True
            round_state.sheriff_badge_lost = True
            round_state.sheriff = None
            return

        excluded_badge_targets = excluded_badge_targets or set()
        badge_options = [
            name for name in active_players if name not in excluded_badge_targets
        ]
        old_sheriff = self.state.player_by_name()[dead_player]
        choice, action_log = self._player_action(
            player=old_sheriff,
            action=ACTION_SHERIFF_BADGE,
            options=badge_options + [SHERIFF_BADGE_DESTROY],
            result_key="badge",
            round_state=round_state,
            phase=phase,
        )
        round_log.sheriff_badge = action_log

        if isinstance(choice, str) and choice in badge_options:
            self._set_sheriff(choice)
            round_state.sheriff_badge_target = choice
            round_state.sheriff = choice
            self._announce(active_players, f"第{round_state.number}轮：{dead_player}出局，将警徽移交给{choice}。")
            return

        self._set_sheriff(None)
        self.state.sheriff_badge_lost = True
        round_state.sheriff_badge_lost = True
        round_state.sheriff = None
        self._announce(active_players, f"第{round_state.number}轮：{dead_player}出局，警徽被撕毁。")

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

    def _eligible_voters(self, active_players: list[str]) -> list[str]:
        players_by_name = self.state.player_by_name()
        return [name for name in active_players if players_by_name[name].can_vote]

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
            "rule_text": render_rule_text(self.rule_set),
            "werewolf_context": self._werewolf_context(player, active_players),
            "debate_turns_left": max(0, self.debate_turns - len(round_state.debate)),
            "options": "、".join(options),
        }

    def _werewolf_context(self, player: Player, active_players: list[str]) -> str:
        if not self._is_werewolf(player) or not player.gamestate:
            return ""
        teammates = player.gamestate.wolf_teammates
        if not teammates and player.gamestate.other_wolf:
            teammates = [player.gamestate.other_wolf]
        if not teammates:
            return ""

        living_teammates = [name for name in teammates if name in active_players]
        if living_teammates:
            return f"你的狼人队友是{'、'.join(living_teammates)}。"
        return f"你的狼人队友{'、'.join(teammates)}已经出局，只剩你独自行动。"

    def _get_winner(self, active_players: list[str]) -> str:
        players_by_name = self.state.player_by_name()
        active_wolves = [name for name in active_players if self._is_werewolf(players_by_name[name])]
        active_villagers = [name for name in active_players if name not in active_wolves]

        if self.rule_set.win_condition == WIN_CONDITION_SLAUGHTER_SIDE:
            active_gods = [
                name
                for name in active_players
                if role_category(self.rule_set, players_by_name[name].role) == ROLE_CATEGORY_GOD
            ]
            active_civilians = [
                name
                for name in active_players
                if role_category(self.rule_set, players_by_name[name].role)
                == ROLE_CATEGORY_CIVILIAN
            ]
            if not active_wolves:
                return WINNER_VILLAGERS
            if not active_gods or not active_civilians:
                return WINNER_WEREWOLVES
            return ""

        if not active_wolves:
            return WINNER_VILLAGERS
        if len(active_wolves) >= len(active_villagers):
            return WINNER_WEREWOLVES
        return ""

    def _is_werewolf(self, player: Player) -> bool:
        return _role_team(self.rule_set, player.role) == TEAM_WEREWOLVES

    def _is_role_active(self, role: str, active_players: list[str]) -> bool:
        return bool(self._active_player_for_role(role, active_players))

    def _active_player_for_role(self, role: str, active_players: list[str]) -> str:
        players_by_name = self.state.player_by_name()
        return next(
            (name for name in active_players if players_by_name[name].role == role),
            "",
        )

    def _majority_vote(
        self,
        votes: dict[str, str],
        active_players: list[str],
        vote_weights: dict[str, float],
    ) -> str | None:
        if not votes:
            return None

        tally: dict[str, float] = {}
        for voter, target in votes.items():
            weight = vote_weights.get(voter, 1.0)
            tally[target] = tally.get(target, 0.0) + weight
        players_by_name = self.state.player_by_name()
        total_weight = sum(
            vote_weights.get(player, 1.0)
            for player in active_players
            if players_by_name[player].can_vote
        )
        if total_weight <= 0:
            return None

        top_weight = max(tally.values())
        winners = [name for name, weight in tally.items() if weight == top_weight]
        if len(winners) == 1 and top_weight > total_weight / 2:
            return winners[0]
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
