from __future__ import annotations

import copy
import random
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Protocol

from app.werewolf.action_quality import action_quality_warnings
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
from app.werewolf.debate_realism import debate_guidance_for_turn
from app.werewolf.live import NullEventSink
from app.werewolf.lm import LmLog, ModelProvider, generate_action_with_events
from app.werewolf.streaming import action_visible_stream_field
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
from app.werewolf.player_configs import (
    PlayerConfig,
    validate_unique_effective_player_names,
)
from app.werewolf.public_facts import (
    PublicFact,
    compressed_public_facts,
    public_fact_from_dict,
)
from app.werewolf.rules import (
    ACTION_DEBATE,
    ACTION_SHERIFF_BADGE,
    ACTION_SHERIFF_PK_SPEECH,
    ACTION_SHERIFF_RUN,
    ACTION_SHERIFF_RUNOFF_VOTE,
    ACTION_SHERIFF_SPEECH,
    ACTION_SHERIFF_VOTE,
    ACTION_SHERIFF_WITHDRAW,
    ACTION_WEREWOLF_DISCUSS,
    ACTION_WEREWOLF_KILL_VOTE,
    ACTION_WEREWOLF_SELF_EXPLOSION,
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


MAX_WEREWOLF_KILL_VOTE_ROUNDS = 8


class MaxRoundsExceeded(RuntimeError):
    pass


class GameCheckpointManager(Protocol):
    def start_round(
        self,
        *,
        state: GameState,
        logs: list[RoundLog],
        round_number: int,
        active_players: list[str],
        rng_state: object,
    ) -> None:
        pass

    def record_success(
        self,
        *,
        actor: str,
        action: str,
        phase: str,
        model: str,
        raw_response: str,
        prompt: str | None = None,
    ) -> None:
        pass

    def record_failure(
        self,
        *,
        actor: str,
        action: str,
        phase: str,
        model: str,
        error: str,
    ) -> None:
        pass


@dataclass(frozen=True)
class PlayerActionRequest:
    player: Player
    action: str
    options: list[str]
    public_options: list[str]
    public_choice_to_internal: dict[str, str]
    result_key: str
    round_state: RoundState
    phase: str
    world_state: dict[str, object]
    is_secret_wolf_action: bool


@dataclass(frozen=True)
class PlayerActionResult:
    request: PlayerActionRequest
    value: object | None
    lm_log: LmLog


class _OrderedBatchProvider:
    def __init__(
        self,
        *,
        provider: ModelProvider,
        index: int,
        condition: threading.Condition,
        next_index: dict[str, int],
    ) -> None:
        self._provider = provider
        self._index = index
        self._condition = condition
        self._next_index = next_index
        self._started = False

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        self._await_turn()
        return self._provider.complete_json(
            model=model,
            prompt=prompt,
            temperature=temperature,
        )

    def __getattr__(self, name: str) -> object:
        if name != "stream_json":
            raise AttributeError(name)
        stream_json = getattr(self._provider, "stream_json", None)
        if not callable(stream_json):
            raise AttributeError(name)

        def ordered_stream_json(
            *,
            model: str,
            prompt: str,
            temperature: float,
        ) -> object:
            self._await_turn()
            return stream_json(model=model, prompt=prompt, temperature=temperature)

        return ordered_stream_json

    def _await_turn(self) -> None:
        self.release_turn_if_not_started()

    def release_turn_if_not_started(self) -> None:
        with self._condition:
            if self._started:
                return
            self._condition.wait_for(lambda: self._next_index["value"] == self._index)
            self._started = True
            self._next_index["value"] += 1
            self._condition.notify_all()


NO_WITCH_SAVE = "不使用解药"
NO_WITCH_POISON = "不使用毒药"
NO_HUNTER_SHOT = "不发动技能"
SHERIFF_RUN = "上警"
SHERIFF_SKIP = "不上警"
SHERIFF_WITHDRAW = "退水"
SHERIFF_STAY = "不退水"
SPEECH_FROM_LEFT = "警左发言"
SPEECH_FROM_RIGHT = "警右发言"
SHERIFF_BADGE_DESTROY = "撕毁警徽"
WEREWOLF_SELF_EXPLODE = "自爆"
WEREWOLF_NO_SELF_EXPLODE = "不自爆"
SHERIFF_BADGE_LOST_DOUBLE_BOMB = "双爆吞警徽"
SHERIFF_BADGE_PENDING_FIRST_BOMB = "首爆中断警长竞选"
SHERIFF_SPEECH_CLOCKWISE = "顺时针"
SHERIFF_SPEECH_COUNTERCLOCKWISE = "逆时针"
OPTIONAL_ACTION_FALLBACKS = {
    ACTION_WITCH_SAVE: NO_WITCH_SAVE,
    ACTION_WITCH_POISON: NO_WITCH_POISON,
    ACTION_HUNTER_SHOOT: NO_HUNTER_SHOT,
    ACTION_WEREWOLF_SELF_EXPLOSION: WEREWOLF_NO_SELF_EXPLODE,
    ACTION_SHERIFF_WITHDRAW: SHERIFF_STAY,
}


def initialize_game_state(
    *,
    session_id: str,
    villager_model: str,
    werewolf_model: str,
    seed: int | None,
    rule_set: RuleSet,
    player_configs: list[PlayerConfig] | None = None,
) -> GameState:
    player_names = choose_player_names(seed, player_count=rule_set.player_count)
    validate_unique_effective_player_names(
        default_names=player_names,
        player_configs=player_configs,
    )
    configs_by_seat = {config.seat: config for config in player_configs or []}
    role_cards = [role_spec for role_spec in rule_set.roles for _ in range(role_spec.count)]
    role_rng = random.Random(f"{seed}:roles") if seed is not None else random.Random()
    role_rng.shuffle(role_cards)
    players: list[Player] = []
    for seat, (player_name, role_spec) in enumerate(
        zip(player_names, role_cards, strict=True),
        start=1,
    ):
        player_config = configs_by_seat.get(seat)
        model = werewolf_model if role_spec.model_group == MODEL_GROUP_WEREWOLF else villager_model
        if player_config is not None:
            player_name = player_config.name or player_name
            model = player_config.model or model
        player = Player(
            player_name,
            role_spec.role,
            model,
            personality_id=player_config.personality_id if player_config else "balanced",
            personality=player_config.personality if player_config else "",
            appearance_id=player_config.appearance_id if player_config else "default",
            avatar_prompt=player_config.avatar_prompt if player_config else "",
            avatar_image_url=player_config.avatar_image_url if player_config else "",
            profile_id=player_config.profile_id if player_config else None,
            tags=list(player_config.tags) if player_config else [],
        )
        if role_spec.role == WITCH:
            player.witch_antidote_available = True
            player.witch_poison_available = True
        elif role_spec.role == HUNTER:
            player.hunter_can_shoot = True
        players.append(player)

    werewolves = [
        player for player in players if _role_team(rule_set, player.role) == TEAM_WEREWOLVES
    ]
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
        rng: random.Random | None = None,
        starting_active_players: list[str] | None = None,
        checkpoint_manager: GameCheckpointManager | None = None,
    ) -> None:
        self.state = state
        self.provider = provider
        self.max_rounds = max_rounds
        self.rule_set = rule_set
        self.debate_turns = debate_turns
        self.event_sink = event_sink or NullEventSink()
        self.rng = rng or random.Random()
        self.starting_active_players = starting_active_players
        self.checkpoint_manager = checkpoint_manager
        self.logs: list[RoundLog] = []

    def run(self) -> list[RoundLog]:
        logs: list[RoundLog] = []
        self.logs = logs
        active_players = (
            self.starting_active_players.copy()
            if self.starting_active_players is not None
            else [player.name for player in self.state.players]
        )
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
            self._checkpoint_round_start(
                round_number=round_number,
                active_players=active_players,
                logs=logs,
            )
            self.state.rounds.append(round_state)
            logs.append(round_log)
            self._publish(
                "round_started",
                round_number=round_number,
                payload={"active_players": active_players.copy()},
            )

            pending_deaths = self._run_night_phase(round_state, round_log, active_players)
            if round_state.night_deaths:
                self.state.winner = self._get_winner(active_players)
                if self.state.winner:
                    round_state.success = True
                    break

            self._run_day_phase(round_state, round_log, active_players, pending_deaths)
            self.state.winner = self._get_winner(active_players)
            round_state.success = True

        return logs

    def _run_night_phase(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> list[DeathEvent] | None:
        self._publish(
            "phase_started",
            round_number=round_state.number,
            phase="night",
            payload={"active_players": active_players.copy()},
        )
        players_by_name = self.state.player_by_name()
        active_wolves = [
            name for name in active_players if self._is_werewolf(players_by_name[name])
        ]
        non_wolves = [
            name for name in active_players if not self._is_werewolf(players_by_name[name])
        ]

        if ACTION_REMOVE in self.rule_set.night_actions:
            round_state.attacked = self._run_werewolf_kill_consensus(
                round_state,
                round_log,
                active_players,
                active_wolves,
                non_wolves,
            )

        if ACTION_PROTECT in self.rule_set.night_actions and self._is_role_active(
            DOCTOR, active_players
        ):
            doctor = players_by_name[self._active_player_for_role(DOCTOR, active_players)]
            self._publish_night_judge_cue(
                round_state,
                "guard_wake",
                "守卫请睁眼。",
            )
            protected, round_log.protect = self._player_action(
                player=doctor,
                action=ACTION_PROTECT,
                options=active_players,
                result_key=ACTION_PROTECT,
                round_state=round_state,
                phase="night",
            )
            round_state.protected = protected
            self._publish_night_judge_cue(
                round_state,
                "guard_sleep",
                "守卫请闭眼。",
            )

        if ACTION_INVESTIGATE in self.rule_set.night_actions and self._is_role_active(
            SEER, active_players
        ):
            seer = players_by_name[self._active_player_for_role(SEER, active_players)]
            investigate_options = [
                name
                for name in active_players
                if name != seer.name and name not in seer.known_roles
            ]
            if investigate_options:
                self._publish_night_judge_cue(
                    round_state,
                    "seer_wake",
                    "预言家请睁眼。",
                )
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
                    alignment = self._investigation_alignment(players_by_name[investigated].role)
                    seer.known_roles[investigated] = alignment
                    seer.add_observation(
                        f"第{round_state.number}轮：我查验了{investigated}，阵营是{alignment}。"
                    )
                self._publish_night_judge_cue(
                    round_state,
                    "seer_sleep",
                    "预言家请闭眼。",
                )

        self._run_witch_phase(round_state, round_log, active_players)
        pending_deaths = self._pending_night_deaths(round_state, active_players)
        should_defer_deaths = (
            self.rule_set.sheriff_enabled and round_state.number == 1 and not self.state.sheriff
        )
        if should_defer_deaths:
            return pending_deaths

        self._announce_night_deaths(pending_deaths, round_state, round_log, active_players)

        if round_state.night_deaths:
            eliminated_names = "、".join(death.player for death in round_state.night_deaths)
            self._announce(
                active_players, f"第{round_state.number}轮：夜晚，{eliminated_names}出局。"
            )
            self._add_public_fact(
                round_state.number,
                "death",
                f"第{round_state.number}轮：夜晚，{eliminated_names}出局。",
            )
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

        return None

    def _run_werewolf_kill_consensus(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        active_wolves: list[str],
        non_wolves: list[str],
    ) -> str | None:
        if not active_wolves or not non_wolves:
            return None

        self._publish_night_judge_cue(
            round_state,
            "werewolves_wake",
            "狼人请睁眼，请互相确认队友。",
        )
        self._publish(
            "action_requested",
            round_number=round_state.number,
            phase="night",
            actor=None,
            action=ACTION_REMOVE,
            payload={},
        )
        players_by_name = self.state.player_by_name()
        candidates = non_wolves.copy()
        previous_vote_round: dict[str, object] | None = None

        for vote_round in range(1, MAX_WEREWOLF_KILL_VOTE_ROUNDS + 1):
            if len(active_wolves) > 1:
                self._run_werewolf_discussion_round(
                    round_state=round_state,
                    round_log=round_log,
                    active_wolves=active_wolves,
                    candidates=candidates,
                    vote_round=vote_round,
                    previous_vote_round=previous_vote_round,
                )

            votes: dict[str, str] = {}
            vote_logs: list[ActionLog] = []
            discussion_context = self._werewolf_discussion_context(round_state)
            previous_vote_context = self._werewolf_vote_round_context(previous_vote_round)
            vote_requests = [
                self._build_player_action_request(
                    player=players_by_name[wolf_name],
                    action=ACTION_WEREWOLF_KILL_VOTE,
                    options=candidates,
                    result_key="target",
                    round_state=round_state,
                    phase="night",
                    extra_world_state={
                        "werewolf_discussion": discussion_context,
                        "werewolf_previous_vote_round": previous_vote_context,
                        "werewolf_kill_vote_round": vote_round,
                    },
                )
                for wolf_name in active_wolves
            ]
            for wolf_name, (target, action_log) in zip(
                active_wolves,
                self._player_actions_batch(vote_requests),
                strict=True,
            ):
                votes[wolf_name] = str(target)
                vote_logs.append(action_log)

            round_log.werewolf_votes.append(vote_logs)
            vote_record = self._record_werewolf_vote_round(vote_round, candidates, votes)
            round_state.werewolf_vote_rounds.append(vote_record)
            for wolf_name, target in votes.items():
                public_target = self._public_player_reference(target)
                public_result = {"target": public_target}
                self._publish(
                    "action_parsed",
                    round_number=round_state.number,
                    phase="night",
                    actor=wolf_name,
                    action=ACTION_WEREWOLF_KILL_VOTE,
                    payload={
                        "choice": public_target,
                        "result": public_result,
                        "visible_result": public_result,
                        "vote_round": vote_round,
                    },
                )
            previous_vote_round = vote_record
            if vote_record["unanimous"]:
                round_log.eliminate = vote_logs[0] if vote_logs else None
                final_target = str(vote_record["result"])
                public_target = self._public_player_reference(final_target)
                public_result = {"target": public_target}
                self._publish(
                    "action_parsed",
                    round_number=round_state.number,
                    phase="night",
                    actor=None,
                    action=ACTION_REMOVE,
                    payload={
                        "choice": public_target,
                        "result": public_result,
                        "visible_result": public_result,
                        "vote_round": vote_round,
                        "final_target": True,
                    },
                )
                self._publish_night_judge_cue(
                    round_state,
                    "werewolves_sleep",
                    "狼人请闭眼。",
                )
                return final_target

            candidates = list(dict.fromkeys(votes.values()))

        raise RuntimeError("狼人夜晚投票未能达成一致")

    def _run_werewolf_discussion_round(
        self,
        *,
        round_state: RoundState,
        round_log: RoundLog,
        active_wolves: list[str],
        candidates: list[str],
        vote_round: int,
        previous_vote_round: dict[str, object] | None,
    ) -> None:
        players_by_name = self.state.player_by_name()
        previous_vote_context = self._werewolf_vote_round_context(previous_vote_round)
        for wolf_name in active_wolves:
            discussion_context = self._werewolf_discussion_context(round_state)
            wolf = players_by_name[wolf_name]
            target, action_log = self._player_action(
                player=wolf,
                action=ACTION_WEREWOLF_DISCUSS,
                options=candidates,
                result_key="target",
                round_state=round_state,
                phase="night",
                extra_world_state={
                    "werewolf_discussion": discussion_context,
                    "werewolf_previous_vote_round": previous_vote_context,
                    "werewolf_kill_vote_round": vote_round,
                },
            )
            message = ""
            if action_log.lm_log.result:
                message = str(action_log.lm_log.result.get("message") or "")
            round_state.werewolf_discussion.append(
                {
                    "round": vote_round,
                    "speaker": wolf.name,
                    "target": str(target),
                    "message": message,
                }
            )
            round_log.werewolf_discussion.append(action_log)

    def _record_werewolf_vote_round(
        self,
        vote_round: int,
        candidates: list[str],
        votes: dict[str, str],
    ) -> dict[str, object]:
        tally: dict[str, int] = {}
        for target in votes.values():
            tally[target] = tally.get(target, 0) + 1
        voted_targets = list(dict.fromkeys(votes.values()))
        unanimous = len(voted_targets) == 1
        return {
            "round": vote_round,
            "candidates": candidates.copy(),
            "votes": votes.copy(),
            "tally": tally,
            "unanimous": unanimous,
            "result": voted_targets[0] if unanimous else None,
        }

    def _werewolf_discussion_context(self, round_state: RoundState) -> list[str]:
        return [
            (
                f"第{entry.get('round')}轮沟通，{entry.get('speaker')}建议"
                f"{entry.get('target')}：{entry.get('message')}"
            )
            for entry in round_state.werewolf_discussion
        ]

    def _werewolf_vote_round_context(
        self,
        vote_round: dict[str, object] | None,
    ) -> str:
        if not vote_round:
            return "暂无。"
        votes = vote_round.get("votes")
        if not isinstance(votes, dict):
            return "暂无。"
        vote_text = "；".join(f"{wolf} -> {target}" for wolf, target in votes.items())
        return f"第{vote_round.get('round')}轮票型：{vote_text}。"

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

        poison_options = [
            name for name in active_players if name != witch.name and name != round_state.attacked
        ] + [NO_WITCH_POISON]
        can_offer_save = (
            ACTION_WITCH_SAVE in self.rule_set.night_actions
            and bool(round_state.attacked)
            and witch.witch_antidote_available
        )
        can_offer_poison = (
            ACTION_WITCH_POISON in self.rule_set.night_actions
            and witch.witch_poison_available
            and poison_options != [NO_WITCH_POISON]
        )
        if not can_offer_save and not can_offer_poison:
            return

        self._publish_night_judge_cue(
            round_state,
            "witch_wake",
            "女巫请睁眼。",
        )
        if round_state.attacked:
            public_target = self._public_player_reference(round_state.attacked)
            self._publish_night_judge_cue(
                round_state,
                "witch_death",
                f"今晚被狼人袭击的玩家是{public_target}。",
                target=public_target,
            )

        used_antidote = False
        if can_offer_save:
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

        if not used_antidote and can_offer_poison:
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

        self._publish_night_judge_cue(
            round_state,
            "witch_sleep",
            "女巫请闭眼。",
        )

    def _pending_night_deaths(
        self, round_state: RoundState, active_players: list[str]
    ) -> list[DeathEvent]:
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

        seen: set[str] = set()
        unique_deaths: list[DeathEvent] = []
        for death in deaths:
            if death.player in seen:
                continue
            seen.add(death.player)
            unique_deaths.append(death)
        return unique_deaths

    def _announce_night_deaths(
        self,
        deaths: list[DeathEvent],
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        pending_night_deaths = self._record_night_deaths(deaths, round_state, active_players)
        self._resolve_night_death_aftermath(
            deaths,
            pending_night_deaths,
            round_state,
            round_log,
            active_players,
        )

    def _record_night_deaths(
        self,
        deaths: list[DeathEvent],
        round_state: RoundState,
        active_players: list[str],
    ) -> set[str]:
        existing_dead_players = {
            death.player for death in [*round_state.night_deaths, *round_state.day_deaths]
        }
        recorded_night_deaths: set[str] = set()
        for death in deaths:
            if death.player in existing_dead_players:
                continue
            round_state.night_deaths.append(death)
            existing_dead_players.add(death.player)
            recorded_night_deaths.add(death.player)
            self._remove_player(active_players, death.player)

        round_state.eliminated = (
            round_state.night_deaths[0].player if round_state.night_deaths else None
        )
        return recorded_night_deaths

    def _resolve_night_death_aftermath(
        self,
        deaths: list[DeathEvent],
        pending_night_deaths: set[str],
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        transfer_sheriff_badge: bool = True,
    ) -> None:
        for death in deaths:
            self._maybe_run_hunter_shot(
                dead_player=death.player,
                death_cause=death.cause,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase="night",
                excluded_shot_targets=pending_night_deaths,
                excluded_badge_targets=pending_night_deaths,
                transfer_sheriff_badge=transfer_sheriff_badge,
            )
            if transfer_sheriff_badge:
                self._maybe_transfer_sheriff_badge(
                    dead_player=death.player,
                    round_state=round_state,
                    round_log=round_log,
                    active_players=active_players,
                    phase="night",
                    excluded_badge_targets=pending_night_deaths,
                )

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
        transfer_sheriff_badge: bool = True,
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
            if transfer_sheriff_badge:
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
        pending_night_deaths: list[DeathEvent] | None = None,
    ) -> None:
        self._publish(
            "phase_started",
            round_number=round_state.number,
            phase="day",
            payload={"active_players": active_players.copy()},
        )
        if self._run_sheriff_election_if_needed(round_state, round_log, active_players):
            self._finish_deferred_night_deaths_if_needed(
                pending_night_deaths,
                round_state,
                round_log,
                active_players,
            )
            self._publish_self_explosion_update(round_state, active_players)
            return

        self._finish_deferred_night_deaths_if_needed(
            pending_night_deaths,
            round_state,
            round_log,
            active_players,
        )
        if self.state.winner:
            return

        if self._run_debate_phase(round_state, round_log, active_players):
            self._publish_self_explosion_update(round_state, active_players)
            return

        self._publish(
            "phase_started",
            round_number=round_state.number,
            phase="vote",
            payload={"active_players": active_players.copy()},
        )
        votes, vote_logs = self._run_voting(round_state, active_players)
        round_state.votes.append(votes)
        round_log.votes.append(vote_logs)
        if votes:
            self._add_public_fact(
                round_state.number,
                "vote",
                f"第{round_state.number}轮票型："
                + "；".join(f"{voter}->{target}" for voter, target in votes.items()),
            )
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
            self._announce(
                active_players, f"第{round_state.number}轮：白天投票未形成多数，无人被放逐。"
            )
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

    def _finish_deferred_night_deaths_if_needed(
        self,
        pending_night_deaths: list[DeathEvent] | None,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        if pending_night_deaths is None:
            return

        pending_night_death_players = self._record_night_deaths(
            pending_night_deaths,
            round_state,
            active_players,
        )
        self._resolve_night_death_aftermath(
            pending_night_deaths,
            pending_night_death_players,
            round_state,
            round_log,
            active_players,
            transfer_sheriff_badge=False,
        )
        if round_state.night_deaths:
            eliminated_names = "、".join(death.player for death in round_state.night_deaths)
            self._announce(
                active_players, f"第{round_state.number}轮：夜晚，{eliminated_names}出局。"
            )
            self._add_public_fact(
                round_state.number,
                "death",
                f"第{round_state.number}轮：夜晚，{eliminated_names}出局。",
            )
        else:
            self._announce(active_players, f"第{round_state.number}轮：夜晚无人出局。")

        night_death_players = {death.player for death in round_state.night_deaths}
        for death in list(round_state.night_deaths):
            self._maybe_transfer_sheriff_badge(
                dead_player=death.player,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase="night",
                excluded_badge_targets=night_death_players,
            )

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
        self.state.winner = self._get_winner(active_players)

    def _publish_self_explosion_update(
        self,
        round_state: RoundState,
        active_players: list[str],
    ) -> None:
        self._publish_state_updated(
            round_state=round_state,
            phase="day",
            actor=round_state.werewolf_self_exploded,
            action=ACTION_WEREWOLF_SELF_EXPLOSION,
            payload={
                "werewolf_self_exploded": round_state.werewolf_self_exploded,
                "day_ended_by_self_explosion": round_state.day_ended_by_self_explosion,
                "day_deaths": [death.to_dict() for death in round_state.day_deaths],
                "sheriff_pre_election_bomb_count": round_state.sheriff_pre_election_bomb_count,
                "sheriff_election_pending": round_state.sheriff_election_pending,
                "sheriff_badge_lost": round_state.sheriff_badge_lost,
                "sheriff_badge_lost_reason": round_state.sheriff_badge_lost_reason,
                "active_players": active_players.copy(),
            },
        )

    def _run_debate_phase(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> bool:
        speech_order = self._speech_order(round_state, round_log, active_players)
        round_state.speech_order = speech_order
        players_by_name = self.state.player_by_name()

        for speaker in speech_order:
            if self._maybe_run_werewolf_self_explosion(
                round_state,
                round_log,
                active_players,
                f"{speaker} 发言前",
            ):
                return True
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
            self._publish_action_quality_warnings(
                round_state=round_state,
                phase="day",
                actor=speaker,
                action=ACTION_DEBATE,
                text=message,
                prior_texts=[entry.message for entry in round_state.debate],
                personality=player.personality,
            )

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
            if self._maybe_run_werewolf_self_explosion(
                round_state,
                round_log,
                active_players,
                f"{speaker} 发言后",
            ):
                return True
        return False

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

    def _maybe_run_werewolf_self_explosion(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
        stage: str,
    ) -> bool:
        if not self.rule_set.werewolf_self_explosion_enabled:
            return False
        if self.state.winner:
            return False

        players_by_name = self.state.player_by_name()
        active_wolves = [
            name for name in active_players if self._is_werewolf(players_by_name[name])
        ]
        requests = [
            self._build_player_action_request(
                player=players_by_name[name],
                action=ACTION_WEREWOLF_SELF_EXPLOSION,
                options=[WEREWOLF_SELF_EXPLODE, WEREWOLF_NO_SELF_EXPLODE],
                result_key="self_explode",
                round_state=round_state,
                phase="day",
                extra_world_state={"self_explosion_stage": stage},
            )
            for name in active_wolves
        ]
        for name, (choice, action_log) in zip(
            active_wolves,
            self._player_actions_batch(requests),
            strict=True,
        ):
            if choice != WEREWOLF_SELF_EXPLODE:
                continue

            round_log.werewolf_self_explosion = action_log
            self._resolve_werewolf_self_explosion(
                wolf=name,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
            )
            return True
        return False

    def _resolve_werewolf_self_explosion(
        self,
        *,
        wolf: str,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        players_by_name = self.state.player_by_name()
        players_by_name[wolf].revealed_role = True
        round_state.werewolf_self_exploded = wolf
        round_state.day_ended_by_self_explosion = True
        round_state.day_deaths.append(DeathEvent(wolf, "werewolf_self_explosion", wolf))
        self._remove_player(active_players, wolf)
        self._announce(
            active_players, f"第{round_state.number}轮：{wolf}自爆为狼人，白天立即结束。"
        )
        self._add_public_fact(
            round_state.number,
            "reveal",
            f"第{round_state.number}轮：{wolf}自爆为狼人，白天立即结束。",
        )

        if self.state.sheriff == wolf:
            self._maybe_transfer_sheriff_badge(
                dead_player=wolf,
                round_state=round_state,
                round_log=round_log,
                active_players=active_players,
                phase="day",
            )
            return

        if self.state.sheriff or self.state.sheriff_badge_lost:
            return

        self.state.sheriff_pre_election_bomb_count += 1
        round_state.sheriff_pre_election_bomb_count = self.state.sheriff_pre_election_bomb_count
        if (
            self.rule_set.sheriff_badge_bomb_policy == "double"
            and self.state.sheriff_pre_election_bomb_count >= 2
        ):
            round_state.sheriff_badge_lost_reason = SHERIFF_BADGE_LOST_DOUBLE_BOMB
            self.state.sheriff_election_pending = False
            round_state.sheriff_election_pending = False
            self._lose_sheriff_badge(round_state, active_players, SHERIFF_BADGE_LOST_DOUBLE_BOMB)
            return

        self.state.sheriff_election_pending = True
        round_state.sheriff_election_pending = True
        round_state.sheriff_badge_lost_reason = SHERIFF_BADGE_PENDING_FIRST_BOMB

    def _run_sheriff_election_if_needed(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> bool:
        round_state.sheriff = self.state.sheriff
        if not self._should_run_sheriff_election(round_state):
            return False

        self._publish(
            "judge_cue",
            round_number=round_state.number,
            phase="day",
            actor=None,
            action="sheriff_raise_hands",
            payload={
                "cue": "sheriff_raise_hands",
                "visible_text": "想要竞选警长的玩家请举手。",
            },
        )
        players_by_name = self.state.player_by_name()
        candidates: list[str] = []
        voters: list[str] = []
        run_requests = [
            self._build_player_action_request(
                player=players_by_name[name],
                action=ACTION_SHERIFF_RUN,
                options=[SHERIFF_RUN, SHERIFF_SKIP],
                result_key="run",
                round_state=round_state,
                phase="day",
            )
            for name in active_players
        ]
        for name, (run_choice, action_log) in zip(
            active_players,
            self._player_actions_batch(run_requests),
            strict=True,
        ):
            round_log.sheriff_run.append(action_log)
            if run_choice == SHERIFF_RUN:
                candidates.append(name)
            else:
                voters.append(name)

        round_state.sheriff_candidates = candidates
        round_state.sheriff_voters = voters
        if not candidates:
            round_state.sheriff_final_candidates = []
            self._lose_sheriff_badge(round_state, active_players, "无人上警")
            return False

        sheriff_speech_order = self._choose_sheriff_speech_order(
            round_state,
            active_players,
            candidates,
        )
        if self._maybe_run_werewolf_self_explosion(
            round_state,
            round_log,
            active_players,
            "警上发言前",
        ):
            return True

        for name in sheriff_speech_order:
            message, action_log = self._player_action(
                player=players_by_name[name],
                action=ACTION_SHERIFF_SPEECH,
                options=[],
                result_key="say",
                round_state=round_state,
                phase="day",
            )
            round_log.sheriff_speech.append(action_log)
            if not isinstance(message, str) or not message:
                raise ValueError(f"{name} did not return a valid sheriff speech.")
            round_state.sheriff_speeches.append({"speaker": name, "message": message})
            self._publish_action_quality_warnings(
                round_state=round_state,
                phase="day",
                actor=name,
                action=ACTION_SHERIFF_SPEECH,
                text=message,
            )
            self._add_public_fact(
                round_state.number,
                "claim",
                f"第{round_state.number}轮警上发言：{name}：{message}",
            )
            if self._maybe_run_werewolf_self_explosion(
                round_state,
                round_log,
                active_players,
                f"{name} 警上发言后",
            ):
                return True

        if self._maybe_run_werewolf_self_explosion(
            round_state,
            round_log,
            active_players,
            "退水前",
        ):
            return True

        withdrawn: list[str] = []
        withdraw_requests = [
            self._build_player_action_request(
                player=players_by_name[name],
                action=ACTION_SHERIFF_WITHDRAW,
                options=[SHERIFF_WITHDRAW, SHERIFF_STAY],
                result_key="withdraw",
                round_state=round_state,
                phase="day",
            )
            for name in candidates
        ]
        for name, (withdraw_choice, action_log) in zip(
            candidates,
            self._player_actions_batch(withdraw_requests),
            strict=True,
        ):
            round_log.sheriff_withdraw.append(action_log)
            if withdraw_choice == SHERIFF_WITHDRAW:
                withdrawn.append(name)

        round_state.sheriff_withdrawn = withdrawn
        final_candidates = [name for name in candidates if name not in set(withdrawn)]
        round_state.sheriff_final_candidates = final_candidates

        if not final_candidates:
            self._lose_sheriff_badge(round_state, active_players, "警上候选全部退水")
            return False

        if len(final_candidates) == 1:
            self._elect_sheriff(final_candidates[0], round_state, active_players)
            return False

        if not voters:
            self._lose_sheriff_badge(round_state, active_players, "警下无人可投票")
            return False

        if self._maybe_run_werewolf_self_explosion(
            round_state,
            round_log,
            active_players,
            "警下投票前",
        ):
            return True

        vote_requests = [
            self._build_player_action_request(
                player=players_by_name[name],
                action=ACTION_SHERIFF_VOTE,
                options=final_candidates,
                result_key="sheriff_vote",
                round_state=round_state,
                phase="day",
            )
            for name in voters
        ]
        for name, (vote, action_log) in zip(
            voters,
            self._player_actions_batch(vote_requests),
            strict=True,
        ):
            round_log.sheriff_votes.append(action_log)
            if isinstance(vote, str) and vote in final_candidates:
                round_state.sheriff_votes[name] = vote

        first_round_winners = self._plurality_winners(round_state.sheriff_votes)
        if not first_round_winners:
            self._lose_sheriff_badge(round_state, active_players, "警长投票无人得票")
            return False

        if len(first_round_winners) == 1:
            self._elect_sheriff(first_round_winners[0], round_state, active_players)
            return False

        tied_candidates = set(first_round_winners)
        pk_candidates = [name for name in final_candidates if name in tied_candidates]
        round_state.sheriff_pk_candidates = pk_candidates

        if self._maybe_run_werewolf_self_explosion(
            round_state,
            round_log,
            active_players,
            "PK 发言前",
        ):
            return True

        for name in pk_candidates:
            message, action_log = self._player_action(
                player=players_by_name[name],
                action=ACTION_SHERIFF_PK_SPEECH,
                options=[],
                result_key="say",
                round_state=round_state,
                phase="day",
            )
            round_log.sheriff_pk_speech.append(action_log)
            if not isinstance(message, str) or not message:
                raise ValueError(f"{name} did not return a valid sheriff PK speech.")
            round_state.sheriff_pk_speeches.append({"speaker": name, "message": message})
            if self._maybe_run_werewolf_self_explosion(
                round_state,
                round_log,
                active_players,
                f"{name} PK 发言后",
            ):
                return True

        if self._maybe_run_werewolf_self_explosion(
            round_state,
            round_log,
            active_players,
            "二轮警下投票前",
        ):
            return True

        runoff_vote_requests = [
            self._build_player_action_request(
                player=players_by_name[name],
                action=ACTION_SHERIFF_RUNOFF_VOTE,
                options=pk_candidates,
                result_key="sheriff_vote",
                round_state=round_state,
                phase="day",
            )
            for name in voters
        ]
        for name, (vote, action_log) in zip(
            voters,
            self._player_actions_batch(runoff_vote_requests),
            strict=True,
        ):
            round_log.sheriff_runoff_votes.append(action_log)
            if isinstance(vote, str) and vote in pk_candidates:
                round_state.sheriff_runoff_votes[name] = vote

        sheriff = self._plurality_winner(round_state.sheriff_runoff_votes)
        if sheriff is None:
            self._lose_sheriff_badge(round_state, active_players, "警长二轮投票未产生唯一领先者")
            return False

        self._elect_sheriff(sheriff, round_state, active_players)
        return False

    def _should_run_sheriff_election(self, round_state: RoundState) -> bool:
        return (
            self.rule_set.sheriff_enabled
            and not self.state.sheriff
            and not self.state.sheriff_badge_lost
            and (round_state.number == 1 or self.state.sheriff_election_pending)
        )

    def _choose_sheriff_speech_order(
        self,
        round_state: RoundState,
        active_players: list[str],
        candidates: list[str],
    ) -> list[str]:
        if len(candidates) <= 1:
            round_state.sheriff_speech_order = candidates.copy()
            round_state.sheriff_speech_direction = None
            return candidates.copy()

        start = candidates[self.rng.randrange(len(candidates))]
        direction = self.rng.choice([SHERIFF_SPEECH_CLOCKWISE, SHERIFF_SPEECH_COUNTERCLOCKWISE])
        seated_players = (
            list(reversed(active_players))
            if direction == SHERIFF_SPEECH_COUNTERCLOCKWISE
            else active_players.copy()
        )
        start_index = seated_players.index(start)
        rotated_players = seated_players[start_index:] + seated_players[:start_index]
        candidate_names = set(candidates)
        speech_order = [name for name in rotated_players if name in candidate_names]
        round_state.sheriff_speech_order = speech_order
        round_state.sheriff_speech_direction = direction
        return speech_order

    def _elect_sheriff(
        self,
        sheriff: str,
        round_state: RoundState,
        active_players: list[str],
    ) -> None:
        self._set_sheriff(sheriff)
        self.state.sheriff_election_pending = False
        round_state.sheriff = sheriff
        round_state.sheriff_elected = sheriff
        round_state.sheriff_badge_lost = False
        round_state.sheriff_election_pending = False
        self._announce(
            active_players,
            f"第{round_state.number}轮：警长竞选，{sheriff}当选警长，投票计为{self.rule_set.sheriff_vote_weight:g}票。",
        )
        self._add_public_fact(
            round_state.number,
            "sheriff",
            f"第{round_state.number}轮：警长竞选，{sheriff}当选警长，投票计为{self.rule_set.sheriff_vote_weight:g}票。",
        )
        self._publish_state_updated(
            round_state=round_state,
            phase="day",
            actor=sheriff,
            payload={
                "sheriff": sheriff,
                "sheriff_elected": sheriff,
                "sheriff_candidates": round_state.sheriff_candidates.copy(),
                "sheriff_final_candidates": round_state.sheriff_final_candidates.copy(),
                "sheriff_voters": round_state.sheriff_voters.copy(),
                "sheriff_votes": round_state.sheriff_votes.copy(),
                "sheriff_runoff_votes": round_state.sheriff_runoff_votes.copy(),
                "sheriff_badge_lost": False,
                "active_players": active_players.copy(),
            },
        )

    def _lose_sheriff_badge(
        self,
        round_state: RoundState,
        active_players: list[str],
        reason: str,
    ) -> None:
        self._set_sheriff(None)
        self.state.sheriff_badge_lost = True
        self.state.sheriff_election_pending = False
        round_state.sheriff = None
        round_state.sheriff_badge_lost = True
        round_state.sheriff_election_pending = False
        round_state.sheriff_badge_lost_reason = reason
        self._announce(active_players, f"第{round_state.number}轮：{reason}，警徽流失。")

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
        winners = self._plurality_winners(votes)
        return winners[0] if len(winners) == 1 else None

    def _plurality_winners(self, votes: dict[str, str]) -> list[str]:
        if not votes:
            return []
        tally = Counter(votes.values())
        top_count = max(tally.values())
        return [name for name, count in tally.items() if count == top_count]

    def _set_sheriff(self, sheriff: str | None) -> None:
        players_by_name = self.state.player_by_name()
        for player in players_by_name.values():
            player.is_sheriff = player.name == sheriff
        self.state.sheriff = sheriff
        if sheriff:
            self.state.sheriff_badge_lost = False

    def _run_voting(
        self,
        round_state: RoundState,
        active_players: list[str],
    ) -> tuple[dict[str, str], list[ActionLog]]:
        votes: dict[str, str] = {}
        logs: list[ActionLog] = []
        players_by_name = self.state.player_by_name()
        voters = self._eligible_voters(active_players)
        vote_requests = [
            self._build_player_action_request(
                player=players_by_name[voter],
                action="vote",
                options=[name for name in active_players if name != voter],
                result_key="vote",
                round_state=round_state,
                phase="vote",
            )
            for voter in voters
        ]
        for voter, (vote, action_log) in zip(
            voters,
            self._player_actions_batch(vote_requests),
            strict=True,
        ):
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
            or dead_player in active_players
            or not self._is_recorded_round_death(dead_player, round_state)
        ):
            return

        if not active_players:
            self._set_sheriff(None)
            self.state.sheriff_badge_lost = True
            round_state.sheriff_badge_lost = True
            round_state.sheriff = None
            return

        excluded_badge_targets = excluded_badge_targets or set()
        badge_options = [name for name in active_players if name not in excluded_badge_targets]
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
            self._announce(
                active_players,
                f"第{round_state.number}轮：{dead_player}出局，将警徽移交给{choice}。",
            )
            return

        self._set_sheriff(None)
        self.state.sheriff_badge_lost = True
        round_state.sheriff_badge_lost = True
        round_state.sheriff = None
        self._announce(active_players, f"第{round_state.number}轮：{dead_player}出局，警徽被撕毁。")

    def _is_recorded_round_death(self, player: str, round_state: RoundState) -> bool:
        return any(
            death.player == player for death in [*round_state.night_deaths, *round_state.day_deaths]
        )

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
                round_state.private_summaries[name] = summary
                player.add_observation(f"第{round_state.number}轮总结：{summary}")
            round_log.summaries.append(action_log)

        round_state.public_summary = self._public_round_brief(round_state)
        self._publish_state_updated(
            round_state=round_state,
            phase="summary",
            action="summarize",
            payload={"public_summary": round_state.public_summary},
        )

    def _public_round_brief(self, round_state: RoundState) -> str:
        parts = [f"第{round_state.number}轮"]
        if round_state.night_deaths:
            deaths = "、".join(death.player for death in round_state.night_deaths)
            parts.append(f"夜晚{deaths}出局")
        if round_state.werewolf_self_exploded:
            parts.append(f"{round_state.werewolf_self_exploded}自爆，白天结束")
        if round_state.exiled:
            parts.append(f"{round_state.exiled}被放逐")
        if round_state.hunter_shot:
            parts.append(f"猎人带走{round_state.hunter_shot}")
        if round_state.idiot_revealed:
            parts.append(f"{round_state.idiot_revealed}翻牌免死")
        if len(parts) == 1:
            parts.append("没有公开出局")
        return "；".join(parts) + "。"

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
        extra_world_state: dict[str, object] | None = None,
    ) -> tuple[object | None, ActionLog]:
        request = self._build_player_action_request(
            player=player,
            action=action,
            options=options,
            result_key=result_key,
            round_state=round_state,
            phase=phase,
            extra_world_state=extra_world_state,
        )
        return self._player_action_single(request)

    def _build_player_action_request(
        self,
        *,
        player: Player,
        action: str,
        options: list[str],
        result_key: str,
        round_state: RoundState,
        phase: str,
        extra_world_state: dict[str, object] | None = None,
    ) -> PlayerActionRequest:
        options_snapshot = options.copy()
        public_options = [self._public_player_reference(option) for option in options_snapshot]
        public_choice_to_internal = dict(zip(public_options, options_snapshot, strict=True))
        world_state = self._world_state(player, options_snapshot, round_state)
        if extra_world_state:
            world_state.update(extra_world_state)
        world_state = self._public_model_world_state(copy.deepcopy(world_state))
        world_state["options"] = "、".join(public_options)
        is_secret_wolf_action = self._is_secret_werewolf_action(phase, action)
        return PlayerActionRequest(
            player=player,
            action=action,
            options=options_snapshot,
            public_options=public_options,
            public_choice_to_internal=public_choice_to_internal,
            result_key=result_key,
            round_state=round_state,
            phase=phase,
            world_state=world_state,
            is_secret_wolf_action=is_secret_wolf_action,
        )

    def _execute_player_action_request(
        self,
        request: PlayerActionRequest,
        provider: ModelProvider | None = None,
    ) -> PlayerActionResult:
        action_provider = provider or self.provider
        try:
            value, lm_log = generate_action_with_events(
                provider=action_provider,
                action=request.action,
                world_state=request.world_state,
                model=request.player.model,
                allowed_values=request.public_options if request.public_options else None,
                result_key=request.result_key,
                event_sink=NullEventSink() if request.is_secret_wolf_action else self.event_sink,
                event_context={
                    "round_number": request.round_state.number,
                    "phase": request.phase,
                    "actor": request.player.name,
                    "action": request.action,
                },
            )
        except Exception:
            release_turn = getattr(action_provider, "release_turn_if_not_started", None)
            if callable(release_turn):
                release_turn()
            raise
        if isinstance(value, str) and request.public_choice_to_internal:
            value = request.public_choice_to_internal.get(value, value)
        return PlayerActionResult(request=request, value=value, lm_log=lm_log)

    def _finalize_player_action_result(
        self,
        result: PlayerActionResult,
        *,
        checkpoint: bool = True,
    ) -> tuple[object | None, ActionLog]:
        request = result.request
        player = request.player
        value = result.value
        lm_log = result.lm_log
        action_log = ActionLog(
            actor=player.name,
            action=request.action,
            options=request.options,
            choice=str(value) if value is not None else None,
            lm_log=lm_log,
        )
        if checkpoint:
            self._checkpoint_player_action_success(result)
        invalid_error = self._invalid_player_action_error(result)
        if invalid_error is not None:
            fallback_choice = self._optional_fallback_choice(request)
            if fallback_choice is None:
                raise invalid_error
            invalid_value = self._invalid_value_from_result(result)
            value = fallback_choice
            action_log.choice = str(fallback_choice)
            action_log.invalid_value = invalid_value
            action_log.fallback_choice = fallback_choice
            action_log.fallback_reason = "optional_action_invalid"
            action_log.attempt_count = max(1, len(lm_log.invalid_attempts))
            if not request.is_secret_wolf_action:
                self._publish_optional_fallback_warning(
                    request=request,
                    invalid_value=invalid_value,
                    fallback_choice=fallback_choice,
                )
        if not request.is_secret_wolf_action:
            self._publish(
                "model_response_received",
                round_number=request.round_state.number,
                phase=request.phase,
                actor=player.name,
                action=request.action,
                payload={
                    "request_id": lm_log.request_id,
                    "model": player.model,
                    "message": "模型返回已接收，正在解析行动",
                },
            )
            visible_result = _visible_action_result(request.action, lm_log.result)
            parsed_payload = {
                "choice": self._public_action_value(action_log.choice),
                "result": visible_result,
                "visible_result": visible_result,
                "options": request.public_options.copy(),
            }
            if action_log.fallback_choice is not None:
                parsed_payload.update(
                    {
                        "invalid_value": action_log.invalid_value,
                        "fallback_choice": self._public_action_value(
                            action_log.fallback_choice,
                        ),
                        "fallback_reason": action_log.fallback_reason,
                        "attempt_count": action_log.attempt_count,
                    }
                )
            self._publish(
                "action_parsed",
                round_number=request.round_state.number,
                phase=request.phase,
                actor=player.name,
                action=request.action,
                payload=parsed_payload,
            )
        return value, action_log

    def _player_actions_batch(
        self,
        requests: list[PlayerActionRequest],
    ) -> list[tuple[object | None, ActionLog]]:
        if not requests:
            return []
        if len(requests) == 1:
            return [self._player_action_single(requests[0])]

        for request in requests:
            self._publish_player_action_requested(request)

        results: list[PlayerActionResult | None] = [None] * len(requests)
        exceptions: dict[int, Exception] = {}
        condition = threading.Condition()
        next_index = {"value": 0}
        with ThreadPoolExecutor(max_workers=len(requests)) as executor:
            futures = {
                executor.submit(
                    self._execute_player_action_request,
                    request,
                    _OrderedBatchProvider(
                        provider=self.provider,
                        index=index,
                        condition=condition,
                        next_index=next_index,
                    ),
                ): index
                for index, request in enumerate(requests)
            }
            for future in as_completed(futures):
                index = futures[future]
                try:
                    results[index] = future.result()
                except Exception as exc:
                    exceptions[index] = exc

        if exceptions:
            self._checkpoint_player_action_results(results)
            first_failed_index = min(exceptions)
            request = requests[first_failed_index]
            exc = exceptions[first_failed_index]
            self._checkpoint_player_action_failure(request, exc)
            raise exc

        self._checkpoint_player_action_results(results)
        finalized: list[tuple[object | None, ActionLog]] = []
        for result in results:
            if result is None:
                raise RuntimeError("Player action batch completed without a result.")
            try:
                finalized.append(self._finalize_player_action_result(result, checkpoint=False))
            except Exception as exc:
                self._checkpoint_player_action_failure(result.request, exc)
                raise
        return finalized

    def _player_action_single(
        self,
        request: PlayerActionRequest,
    ) -> tuple[object | None, ActionLog]:
        self._publish_player_action_requested(request)
        try:
            result = self._execute_player_action_request(request)
        except Exception as exc:
            self._checkpoint_player_action_failure(request, exc)
            raise
        try:
            return self._finalize_player_action_result(result)
        except Exception as exc:
            self._checkpoint_player_action_failure(request, exc)
            raise

    def _checkpoint_player_action_success(self, result: PlayerActionResult) -> None:
        request = result.request
        self._checkpoint_model_success(
            actor=request.player.name,
            action=request.action,
            phase=request.phase,
            model=request.player.model,
            raw_response=result.lm_log.raw_response,
            prompt=result.lm_log.prompt,
        )

    def _checkpoint_player_action_results(
        self,
        results: list[PlayerActionResult | None],
    ) -> None:
        for result in results:
            if result is not None:
                self._checkpoint_player_action_success(result)

    def _publish_player_action_requested(self, request: PlayerActionRequest) -> None:
        if request.is_secret_wolf_action:
            return
        self._publish(
            "action_requested",
            round_number=request.round_state.number,
            phase=request.phase,
            actor=request.player.name,
            action=request.action,
            payload={"options": request.public_options.copy(), "result_key": request.result_key},
        )

    def _checkpoint_player_action_failure(
        self,
        request: PlayerActionRequest,
        exc: Exception,
    ) -> None:
        self._checkpoint_model_failure(
            actor=request.player.name,
            action=request.action,
            phase=request.phase,
            model=request.player.model,
            error=str(exc),
        )

    def _invalid_player_action_error(self, result: PlayerActionResult) -> ValueError | None:
        request = result.request
        if request.options and result.value not in request.options:
            return ValueError(
                f"{request.player.name} returned invalid {request.action}: {result.value}"
            )
        return None

    def _optional_fallback_choice(self, request: PlayerActionRequest) -> object | None:
        fallback = OPTIONAL_ACTION_FALLBACKS.get(request.action)
        if fallback is not None and fallback in request.options:
            return fallback
        return None

    def _invalid_value_from_result(self, result: PlayerActionResult) -> object | None:
        if result.value is not None:
            return result.value
        if result.lm_log.invalid_attempts:
            return result.lm_log.invalid_attempts[-1].get("value")
        return None

    def _publish_optional_fallback_warning(
        self,
        *,
        request: PlayerActionRequest,
        invalid_value: object | None,
        fallback_choice: object,
    ) -> None:
        self._publish(
            "action_quality_warning",
            round_number=request.round_state.number,
            phase=request.phase,
            actor=request.player.name,
            action=request.action,
            payload={
                "warnings": ["off_option_fallback"],
                "invalid_value": invalid_value,
                "fallback_choice": self._public_action_value(fallback_choice),
                "allowed_values": request.public_options.copy(),
            },
        )

    def _checkpoint_round_start(
        self,
        *,
        round_number: int,
        active_players: list[str],
        logs: list[RoundLog],
    ) -> None:
        if self.checkpoint_manager is None:
            return
        self.checkpoint_manager.start_round(
            state=copy.deepcopy(self.state),
            logs=copy.deepcopy(logs),
            round_number=round_number,
            active_players=active_players.copy(),
            rng_state=self.rng.getstate(),
        )

    def _checkpoint_model_success(
        self,
        *,
        actor: str,
        action: str,
        phase: str,
        model: str,
        raw_response: str,
        prompt: str | None = None,
    ) -> None:
        if self.checkpoint_manager is None:
            return
        self.checkpoint_manager.record_success(
            actor=actor,
            action=action,
            phase=phase,
            model=model,
            raw_response=raw_response,
            prompt=prompt,
        )

    def _checkpoint_model_failure(
        self,
        *,
        actor: str,
        action: str,
        phase: str,
        model: str,
        error: str,
    ) -> None:
        if self.checkpoint_manager is None:
            return
        self.checkpoint_manager.record_failure(
            actor=actor,
            action=action,
            phase=phase,
            model=model,
            error=error,
        )

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

    def _publish_night_judge_cue(
        self,
        round_state: RoundState,
        cue: str,
        visible_text: str,
        *,
        target: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "cue": cue,
            "visible_text": visible_text,
        }
        if target:
            payload["target"] = target
        self._publish(
            "judge_cue",
            round_number=round_state.number,
            phase="night",
            actor=None,
            action=cue,
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

    def _publish_action_quality_warnings(
        self,
        *,
        round_state: RoundState,
        phase: str,
        actor: str,
        action: str,
        text: str,
        prior_texts: list[str] | tuple[str, ...] = (),
        personality: str = "",
    ) -> None:
        warnings = action_quality_warnings(
            action=action,
            text=text,
            actor=actor,
            endgame=len(round_state.players) <= 4,
            prior_texts=prior_texts,
            personality=personality,
        )
        if not warnings:
            return
        self._publish(
            "action_quality_warning",
            round_number=round_state.number,
            phase=phase,
            actor=actor,
            action=action,
            payload={"warnings": warnings, "text": text},
        )

    def _is_secret_werewolf_action(self, phase: str, action: str) -> bool:
        if action == ACTION_WEREWOLF_SELF_EXPLOSION:
            return True
        if phase == "night" and action in {
            ACTION_WEREWOLF_DISCUSS,
            ACTION_WEREWOLF_KILL_VOTE,
        }:
            return True
        return False

    def _world_state(
        self,
        player: Player,
        options: list[str],
        round_state: RoundState,
    ) -> dict[str, object]:
        active_players = (
            player.gamestate.current_players if player.gamestate else round_state.players
        )
        debate = [f"{entry.speaker}：{entry.message}" for entry in round_state.debate]
        return {
            "name": player.name,
            "role": player.role,
            "round": round_state.number,
            "observations": player.observations,
            "public_facts": self._public_fact_lines(),
            "endgame_context": self._endgame_context(active_players),
            "remaining_players": "、".join(active_players),
            "debate": debate,
            "debate_guidance": self._debate_guidance(player, active_players, round_state),
            "personality": player.personality,
            "rule_text": render_rule_text(self.rule_set),
            "rule_set_snapshot": copy.deepcopy(self.state.rule_set),
            "werewolf_context": self._werewolf_context(player, active_players),
            "sheriff_election": self._sheriff_election_context(round_state),
            "sheriff": self.state.sheriff,
            "sheriff_election_open": self._should_run_sheriff_election(round_state),
            "sheriff_pre_election_bomb_count": self.state.sheriff_pre_election_bomb_count,
            "debate_turns_left": max(0, self.debate_turns - len(round_state.debate)),
            "options": "、".join(options),
        }

    def _public_model_world_state(self, world_state: dict[str, object]) -> dict[str, object]:
        public_state = self._public_model_value(world_state)
        if not isinstance(public_state, dict):
            raise TypeError("world state must remain a dictionary")
        return public_state

    def _public_model_value(self, value: object) -> object:
        if isinstance(value, str):
            return self._public_text(value)
        if isinstance(value, list):
            return [self._public_model_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._public_model_value(item) for item in value)
        if isinstance(value, dict):
            return {
                self._public_text(str(key)): self._public_model_value(item)
                for key, item in value.items()
            }
        return value

    def _public_action_value(self, value: object | None) -> object | None:
        if isinstance(value, str):
            return self._public_player_reference(value)
        return value

    def _public_player_reference(self, name: str | None) -> str:
        if not name:
            return ""
        labels = self._player_public_labels()
        return labels.get(name, name)

    def _public_text(self, text: str) -> str:
        normalized_text = text
        for name, label in sorted(
            self._player_public_labels().items(),
            key=lambda item: len(item[0]),
            reverse=True,
        ):
            if name and name != label:
                normalized_text = normalized_text.replace(name, label)
        return normalized_text

    def _player_public_labels(self) -> dict[str, str]:
        return {
            player.name: f"{index}号玩家"
            for index, player in enumerate(self.state.players, start=1)
        }

    def _debate_guidance(
        self,
        player: Player,
        active_players: list[str],
        round_state: RoundState,
    ) -> list[str]:
        speech_order = round_state.speech_order or active_players
        return debate_guidance_for_turn(
            speaker=player.name,
            active_players=speech_order,
            prior_messages=[f"{entry.speaker}：{entry.message}" for entry in round_state.debate],
            personality=player.personality,
        )

    def _add_public_fact(self, round_number: int, category: str, text: str) -> None:
        self.state.public_facts.append(
            PublicFact(
                round_number=round_number,
                category=category,
                text=text,
            ).to_dict()
        )

    def _public_fact_lines(self) -> list[str]:
        facts = [public_fact_from_dict(item) for item in self.state.public_facts]
        return compressed_public_facts(facts)

    def _endgame_context(self, active_players: list[str]) -> list[str]:
        total_wolves = sum(
            role_spec.count
            for role_spec in self.rule_set.roles
            if role_spec.team == TEAM_WEREWOLVES
        )
        revealed_wolves = [
            player.name
            for player in self.state.players
            if self._is_werewolf(player)
            and player.revealed_role
            and player.name not in active_players
        ]
        max_remaining_wolves = max(0, total_wolves - len(revealed_wolves))
        lines = [
            f"当前存活 {len(active_players)} 人，公开已出 {len(revealed_wolves)} 名狼人，最多可能还剩 {max_remaining_wolves} 狼。",
        ]
        if len(active_players) <= 4 and max_remaining_wolves > 0:
            lines.append("本轮错误放逐可能导致狼人夜晚获胜。")
        return lines

    def _sheriff_election_context(self, round_state: RoundState) -> list[str]:
        lines: list[str] = []
        if round_state.sheriff_candidates:
            lines.append(f"上警名单：{'、'.join(round_state.sheriff_candidates)}")
        if round_state.sheriff_voters:
            lines.append(f"警下名单：{'、'.join(round_state.sheriff_voters)}")
        if round_state.sheriff_speeches:
            speech_lines = [
                f"{entry.get('speaker', '')}：{entry.get('message', '')}"
                for entry in round_state.sheriff_speeches
                if entry.get("speaker") and entry.get("message")
            ]
            if speech_lines:
                lines.append(f"警上发言：{'；'.join(speech_lines)}")
        if round_state.sheriff_withdrawn:
            lines.append(f"退水名单：{'、'.join(round_state.sheriff_withdrawn)}")
        if round_state.sheriff_final_candidates:
            lines.append(f"最终候选：{'、'.join(round_state.sheriff_final_candidates)}")
        if round_state.sheriff_pk_candidates:
            lines.append(f"PK 候选：{'、'.join(round_state.sheriff_pk_candidates)}")
        if round_state.sheriff_pk_speeches:
            pk_speech_lines = [
                f"{entry.get('speaker', '')}：{entry.get('message', '')}"
                for entry in round_state.sheriff_pk_speeches
                if entry.get("speaker") and entry.get("message")
            ]
            if pk_speech_lines:
                lines.append(f"PK 发言：{'；'.join(pk_speech_lines)}")
        if round_state.sheriff_elected:
            lines.append(f"已当选警长：{round_state.sheriff_elected}")
        elif round_state.sheriff_badge_lost:
            lines.append("警徽流失")
        return lines

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

    def _investigation_alignment(self, role: str) -> str:
        if _role_team(self.rule_set, role) == TEAM_WEREWOLVES:
            return WINNER_WEREWOLVES
        return WINNER_VILLAGERS

    def _get_winner(self, active_players: list[str]) -> str:
        players_by_name = self.state.player_by_name()
        active_wolves = [
            name for name in active_players if self._is_werewolf(players_by_name[name])
        ]
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


def _visible_action_result(
    action: str,
    result: dict[str, object] | None,
) -> dict[str, object]:
    if result is None:
        return {}
    visible_field = action_visible_stream_field(action)
    if visible_field is None:
        return {}
    visible_value = result.get(visible_field)
    if isinstance(visible_value, str):
        return {visible_field: visible_value}
    return {}
