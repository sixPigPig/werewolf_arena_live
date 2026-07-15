from __future__ import annotations

import copy
import hashlib
import random
import threading
import time
from collections import Counter
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from typing import Literal, Protocol

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
from app.werewolf.debate_realism import (
    SpeechQualityReportV1,
    assign_speech_mission,
    debate_guidance_for_turn,
    evaluate_speech_quality,
    speech_mission_from_dict,
)
from app.werewolf.execution_budget import (
    ActionExecutionBudgetV1,
    ModelCallOptions,
    ModelDeadlineExceeded,
)
from app.werewolf.execution_telemetry import (
    record_action_batch,
    record_action_execution,
    record_model_progress_event,
)
from app.werewolf.live import NullEventSink
from app.werewolf.judge_narration import (
    JudgeCueSpec,
    cue_spec,
    dawn_result_cue,
    exile_result_cue,
    hunter_result_cue,
    hunter_start_cues,
    idiot_reveal_cues,
    self_explosion_cues,
    seat_asset_id,
    sheriff_badge_cues,
    sheriff_election_cues,
    sheriff_tie_cues,
)
from app.werewolf.lm import LmLog, ModelProvider, generate_action_with_events
from app.werewolf.streaming import action_visible_stream_field
from app.werewolf.models import (
    ActionLog,
    DeathEvent,
    DebateEntry,
    GameState,
    GameView,
    Player,
    PublicActionEligibility,
    PublicOutcomeEventV1,
    PublicOutcomeKind,
    RoundLog,
    RoundState,
    SelfExplosionDecisionContext,
    SheriffBadgeOutcome,
    SheriffBadgeResolution,
    SheriffElectionOutcome,
    SheriffElectionReason,
    SheriffElectionResolution,
    StageInterruption,
)
from app.werewolf.player_configs import (
    PlayerConfig,
    validate_unique_effective_player_names,
)
from app.werewolf.public_facts import (
    FactRetention,
    PublicFact,
    PublicFactOpportunityV1,
    compressed_public_facts,
    fact_prompt_coverage,
    public_fact_from_dict,
)
from app.werewolf.public_outcomes import (
    append_public_outcome,
    latest_player_outcome_event,
    render_public_round_summary,
)
from app.werewolf.quality_telemetry import record_speech_quality
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
WEREWOLF_KILL_DECISION_TIMEOUT_SECONDS = 90.0
WEREWOLF_KILL_VOTE_ROUND_TIMEOUT_SECONDS = 15.0
EventVisibility = Literal["public", "private"]
HARD_ACTION_QUALITY_CODES = frozenset(
    {
        "appeals_to_missing_sheriff_voters",
        "promises_ineligible_sheriff_vote",
        "sheriff_speech_investigation_plan_without_seer_claim",
        "assumes_future_round_in_endgame",
        "ignores_terminal_risk",
    }
)
BUFFERED_QUALITY_ACTIONS = frozenset(
    {ACTION_SHERIFF_SPEECH, ACTION_SHERIFF_PK_SPEECH, ACTION_DEBATE}
)
REQUIRED_PUBLIC_SPEECH_FALLBACK = "本轮暂不追加判断，投票时我会给出明确选择。"
SHERIFF_SPEECH_CONTEXT_MAX_CHARS = 180
SELF_EXPLOSION_BENEFIT_TYPES = frozenset(
    {
        "immediate_win",
        "secure_badge_denial",
        "protect_last_hidden_wolf",
        "deny_confirmed_public_information",
        "force_valuable_night",
        "none",
    }
)


def _compact_sheriff_speech_context(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) <= SHERIFF_SPEECH_CONTEXT_MAX_CHARS:
        return compact
    return compact[: SHERIFF_SPEECH_CONTEXT_MAX_CHARS - 1].rstrip() + "…"


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
    event_visibility: EventVisibility
    fact_prompt_coverage: dict[str, object]


@dataclass(frozen=True)
class PlayerActionResult:
    request: PlayerActionRequest
    value: object | None
    lm_log: LmLog
    execution_status: Literal["completed", "timed_out", "fallback", "failed"] = "completed"
    duration_ms: int = 0
    budget_ms: int | None = None
    fallback_reason: str | None = None


@dataclass(frozen=True)
class PendingSelfExplosionBatch:
    round_number: int
    active_wolves: tuple[str, ...]
    requests: tuple[PlayerActionRequest, ...]
    futures: tuple[Future[PlayerActionResult], ...]
    started_at: float


@dataclass(frozen=True)
class PublicStageCursor:
    stage: str
    ordered_actors: tuple[str, ...] = ()
    completed_actors: tuple[str, ...] = ()
    current_actor: str | None = None
    timing: Literal["before_stage", "before_actor", "after_actor"] = "before_stage"

    @property
    def pending_actors(self) -> list[str]:
        completed = set(self.completed_actors)
        return [actor for actor in self.ordered_actors if actor not in completed]


class _BufferedEventSink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def publish(self, event_type: str, **kwargs: object) -> None:
        self.events.append((event_type, kwargs))

    def flush_to(self, event_sink: object) -> None:
        publish = getattr(event_sink, "publish")
        for event_type, kwargs in self.events:
            publish(event_type, **kwargs)


class _PublishGateSink:
    def __init__(self, destination: object) -> None:
        self._destination = destination
        self._active = True
        self._lock = threading.Lock()

    def publish(self, event_type: str, **kwargs: object) -> None:
        with self._lock:
            if not self._active:
                return
            publish = getattr(self._destination, "publish")
            publish(event_type, **kwargs)

    def close(self) -> None:
        with self._lock:
            self._active = False


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

    def complete_json(
        self,
        *,
        model: str,
        prompt: str,
        temperature: float,
        call_options: ModelCallOptions | None = None,
    ) -> str:
        self._await_turn()
        return self._call_provider_method(
            self._provider.complete_json,
            model=model,
            prompt=prompt,
            temperature=temperature,
            call_options=call_options,
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
            call_options: ModelCallOptions | None = None,
        ) -> object:
            self._await_turn()
            return self._call_provider_method(
                stream_json,
                model=model,
                prompt=prompt,
                temperature=temperature,
                call_options=call_options,
            )

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

    def _call_provider_method(
        self,
        method: Callable[..., object],
        *,
        model: str,
        prompt: str,
        temperature: float,
        call_options: ModelCallOptions | None,
    ) -> object:
        try:
            return method(
                model=model,
                prompt=prompt,
                temperature=temperature,
                call_options=call_options,
            )
        except TypeError as exc:
            if "call_options" not in str(exc):
                raise
            return method(model=model, prompt=prompt, temperature=temperature)


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
SELF_EXPLOSION_HANDOFF_TIMEOUT_SECONDS = 0.005
SHERIFF_ELECTION_REASON_TEXT: dict[SheriffElectionReason, str] = {
    "single_candidate": "仅剩一名候选人",
    "first_vote_winner": "首轮投票产生唯一领先者",
    "runoff_vote_winner": "二轮投票产生唯一领先者",
    "no_candidates": "无人上警",
    "all_candidates_withdrew": "警上候选全部退水",
    "no_off_sheriff_voters": "警下无人可投票",
    "first_vote_empty": "警长投票无人得票",
    "runoff_tied": "警长二轮投票未产生唯一领先者",
    "first_pre_election_self_explosion": SHERIFF_BADGE_PENDING_FIRST_BOMB,
    "double_pre_election_self_explosion": SHERIFF_BADGE_LOST_DOUBLE_BOMB,
}
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
        speech_quality_retry_enabled: bool = False,
        action_budgets_enabled: bool = False,
        action_execution_budget: ActionExecutionBudgetV1 | None = None,
        fallback_seed: int | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        execution_mode: Literal["new", "resume"] = "new",
        resume_from_round: int | None = None,
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
        self.speech_quality_retry_enabled = speech_quality_retry_enabled
        self.action_budgets_enabled = action_budgets_enabled
        self.action_execution_budget = action_execution_budget or ActionExecutionBudgetV1()
        self.fallback_seed = fallback_seed
        self.monotonic = monotonic
        self.execution_mode = execution_mode
        self.resume_from_round = resume_from_round
        self.logs: list[RoundLog] = []
        self._self_explosion_executor: ThreadPoolExecutor | None = None
        self._pending_self_explosion: PendingSelfExplosionBatch | None = None

    def run(self) -> list[RoundLog]:
        logs: list[RoundLog] = []
        self.logs = logs
        active_players = (
            self.starting_active_players.copy()
            if self.starting_active_players is not None
            else [player.name for player in self.state.players]
        )
        self._refresh_winner(active_players)
        start_event_type = "game_resumed" if self.execution_mode == "resume" else "game_started"
        start_payload: dict[str, object] = {
            "players": [player.to_dict() for player in self.state.players],
            "active_players": active_players.copy(),
        }
        if self.execution_mode == "resume":
            start_payload["resume_from_round"] = self.resume_from_round
        self._publish(start_event_type, payload=start_payload)

        try:
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
                if self.state.winner:
                    round_state.success = True
                    break

                self._run_day_phase(round_state, round_log, active_players, pending_deaths)
                self._refresh_winner(active_players)
                round_state.success = True

            return logs
        finally:
            self._shutdown_self_explosion_worker()

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
                stage="night_resolution",
                retention="critical",
                details={
                    "players": [death.player for death in round_state.night_deaths],
                },
            )
        else:
            self._announce(active_players, f"第{round_state.number}轮：夜晚无人出局。")
        self._publish_state_updated(
            round_state=round_state,
            phase="night",
            action="night_resolved",
            payload={
                "narration_mode": "explicit_v1",
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
        self._publish_dawn_result(round_state)
        self._refresh_winner(active_players)

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
        current_votes: dict[str, str] = {}
        latest_vote_logs: dict[str, ActionLog] = {}
        decision_deadline = self.monotonic() + WEREWOLF_KILL_DECISION_TIMEOUT_SECONDS

        for vote_round in range(1, MAX_WEREWOLF_KILL_VOTE_ROUNDS + 1):
            vote_logs: list[ActionLog] = []
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
                        "werewolf_previous_vote_round": previous_vote_context,
                        "werewolf_kill_vote_round": vote_round,
                    },
                )
                for wolf_name in active_wolves
            ]
            round_deadline = min(
                decision_deadline,
                self.monotonic() + WEREWOLF_KILL_VOTE_ROUND_TIMEOUT_SECONDS,
            )
            vote_results = self._run_werewolf_vote_round(
                vote_requests,
                deadline_at_monotonic=round_deadline,
            )
            for wolf_name, target, action_log in vote_results:
                current_votes[wolf_name] = target
                latest_vote_logs[wolf_name] = action_log
                vote_logs.append(action_log)

            round_log.werewolf_votes.append(vote_logs)
            vote_record = self._record_werewolf_vote_round(
                vote_round,
                candidates,
                current_votes,
                expected_voters=len(active_wolves),
            )
            round_state.werewolf_vote_rounds.append(vote_record)
            for wolf_name, target, _action_log in vote_results:
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
                final_target = str(vote_record["result"])
                round_log.eliminate = next(
                    (
                        latest_vote_logs[wolf_name]
                        for wolf_name in active_wolves
                        if current_votes.get(wolf_name) == final_target
                        and wolf_name in latest_vote_logs
                    ),
                    None,
                )
                self._publish_final_werewolf_target(
                    round_state=round_state,
                    target=final_target,
                    vote_round=vote_round,
                )
                return final_target

            if self.monotonic() >= decision_deadline:
                break

        final_target = self._werewolf_majority_target(current_votes)
        if final_target is not None and round_state.werewolf_vote_rounds:
            round_state.werewolf_vote_rounds[-1]["result"] = final_target
            round_log.eliminate = next(
                (
                    latest_vote_logs[wolf_name]
                    for wolf_name in active_wolves
                    if current_votes.get(wolf_name) == final_target
                    and wolf_name in latest_vote_logs
                ),
                None,
            )
            self._publish_final_werewolf_target(
                round_state=round_state,
                target=final_target,
                vote_round=len(round_state.werewolf_vote_rounds),
            )
            return final_target

        self._publish_night_judge_cue(
            round_state,
            "werewolves_sleep",
            "狼人请闭眼。",
        )
        return None

    def _run_werewolf_vote_round(
        self,
        requests: list[PlayerActionRequest],
        *,
        deadline_at_monotonic: float,
    ) -> list[tuple[str, str, ActionLog]]:
        if not requests:
            return []

        condition = threading.Condition()
        next_index = {"value": 0}
        executor = ThreadPoolExecutor(max_workers=len(requests))
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
                NullEventSink(),
                deadline_at_monotonic=deadline_at_monotonic,
                timeout_fallback=False,
            ): index
            for index, request in enumerate(requests)
        }
        wait_seconds = max(0.0, deadline_at_monotonic - self.monotonic())
        done, pending = wait(futures, timeout=wait_seconds)
        results: list[PlayerActionResult | None] = [None] * len(requests)
        failures: set[int] = set()
        for future in done:
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception:
                failures.add(index)
        for future in pending:
            future.cancel()
            failures.add(futures[future])
        executor.shutdown(wait=not pending, cancel_futures=bool(pending))

        completed: list[tuple[str, str, ActionLog]] = []
        for index, request in enumerate(requests):
            if index in failures:
                continue
            result = results[index]
            if result is None:
                continue
            try:
                target, action_log = self._finalize_player_action_result(result)
            except Exception:
                continue
            if isinstance(target, str) and target in request.options:
                completed.append((request.player.name, target, action_log))
        return completed

    def _publish_final_werewolf_target(
        self,
        *,
        round_state: RoundState,
        target: str,
        vote_round: int,
    ) -> None:
        public_target = self._public_player_reference(target)
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

    def _record_werewolf_vote_round(
        self,
        vote_round: int,
        candidates: list[str],
        votes: dict[str, str],
        *,
        expected_voters: int,
    ) -> dict[str, object]:
        tally: dict[str, int] = {}
        for target in votes.values():
            tally[target] = tally.get(target, 0) + 1
        voted_targets = list(dict.fromkeys(votes.values()))
        unanimous = len(votes) == expected_voters and len(voted_targets) == 1
        return {
            "round": vote_round,
            "candidates": candidates.copy(),
            "votes": votes.copy(),
            "tally": tally,
            "unanimous": unanimous,
            "result": voted_targets[0] if unanimous else None,
        }

    def _werewolf_vote_round_context(
        self,
        vote_round: dict[str, object] | None,
    ) -> str:
        if not vote_round:
            return "暂无。"
        tally = vote_round.get("tally")
        if not isinstance(tally, dict) or not tally:
            return "暂无。"
        vote_text = "；".join(f"{target}：{count}票" for target, count in tally.items())
        return f"第{vote_round.get('round')}轮匿名刀口：{vote_text}。"

    def _werewolf_majority_target(self, votes: dict[str, str]) -> str | None:
        tally = Counter(votes.values())
        if not tally:
            return None
        highest_count = max(tally.values())
        leaders = [target for target, count in tally.items() if count == highest_count]
        return leaders[0] if len(leaders) == 1 else None

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
            self._append_public_outcome(
                round_state=round_state,
                kind="night_death",
                target_player=death.player,
                outcome="eliminated",
                phase="night",
            )
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

        self._publish_judge_cues(
            round_state,
            phase,
            hunter_start_cues(self._public_player_reference(hunter.name)),
        )
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
            hunter_outcome = self._append_public_outcome(
                round_state=round_state,
                kind="hunter_shot",
                actor_player=hunter.name,
                target_player=shot_player,
                outcome="eliminated",
                phase=phase,
                caused_by_event=self._latest_player_outcome(
                    round_state,
                    hunter.name,
                ),
            )
            self._add_public_fact(
                round_state.number,
                "death",
                f"第{round_state.number}轮：{hunter.name}发动猎人技能，{shot_player}出局。",
                stage="hunter_shot",
                actor=hunter.name,
                retention="critical",
                details={"target": shot_player},
            )
            if transfer_sheriff_badge:
                self._maybe_transfer_sheriff_badge(
                    dead_player=shot_player,
                    round_state=round_state,
                    round_log=round_log,
                    active_players=active_players,
                    phase=phase,
                    excluded_badge_targets=excluded_badge_targets,
                )
            self._publish_state_updated(
                round_state=round_state,
                phase=phase,
                actor=hunter.name,
                action="hunter_shot_resolved",
                payload={
                    "narration_mode": "explicit_v1",
                    "hunter_shot": round_state.hunter_shot,
                    "night_deaths": [death.to_dict() for death in round_state.night_deaths],
                    "day_deaths": [death.to_dict() for death in round_state.day_deaths],
                    "active_players": active_players.copy(),
                },
            )
            self._publish_judge_cue(
                round_state,
                phase,
                hunter_result_cue(hunter_outcome.target_player_id),
            )
            return
        self._publish_judge_cue(round_state, phase, hunter_result_cue(None))

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
            payload={
                "active_players": active_players.copy(),
                "narration_mode": "explicit_v1",
            },
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
                stage="vote",
                retention="important",
                details={"votes": votes.copy()},
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
            action="day_resolution_completed",
            payload={
                "narration_mode": "explicit_v1",
                "exiled": round_state.exiled,
                "day_deaths": [death.to_dict() for death in round_state.day_deaths],
                "hunter_shot": round_state.hunter_shot,
                "idiot_revealed": round_state.idiot_revealed,
                "active_players": active_players.copy(),
            },
        )
        is_terminal = self._refresh_winner(active_players)
        self._publish_public_round_brief(round_state, active_players)
        if is_terminal:
            return
        self._run_private_round_memories(round_state, round_log, active_players)

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
                stage="night_resolution",
                retention="critical",
                details={
                    "players": [death.player for death in round_state.night_deaths],
                },
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
            action="night_resolved",
            payload={
                "narration_mode": "explicit_v1",
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
        self._publish_dawn_result(round_state)
        self._refresh_winner(active_players)

    def _publish_dawn_result(self, round_state: RoundState) -> None:
        public_players = [
            event.target_player_id
            for event in round_state.public_outcome_events
            if event.kind == "night_death" and event.target_player_id
        ]
        self._publish_judge_cue(round_state, "day", dawn_result_cue(public_players))

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
                "narration_mode": "explicit_v1",
                "werewolf_self_exploded": round_state.werewolf_self_exploded,
                "day_ended_by_self_explosion": round_state.day_ended_by_self_explosion,
                "day_deaths": [death.to_dict() for death in round_state.day_deaths],
                "sheriff_pre_election_bomb_count": round_state.sheriff_pre_election_bomb_count,
                "sheriff_election_pending": round_state.sheriff_election_pending,
                "sheriff_badge_lost": round_state.sheriff_badge_lost,
                "sheriff_badge_lost_reason": round_state.sheriff_badge_lost_reason,
                "interruption": (
                    round_state.interruption.to_dict() if round_state.interruption else None
                ),
                "active_players": active_players.copy(),
            },
        )
        self_explosion_outcome = next(
            (
                event
                for event in reversed(round_state.public_outcome_events)
                if event.kind == "self_explosion"
            ),
            None,
        )
        if self_explosion_outcome and self_explosion_outcome.actor_player_id:
            interruption = round_state.interruption
            self._publish_judge_cues(
                round_state,
                "day",
                self_explosion_cues(
                    self_explosion_outcome.actor_player_id,
                    stage=interruption.stage if interruption else "day",
                    completed_actors=(
                        [
                            self._public_player_reference(name)
                            for name in interruption.completed_actors
                        ]
                        if interruption
                        else []
                    ),
                    pending_actors=(
                        [
                            self._public_player_reference(name)
                            for name in interruption.pending_actors
                        ]
                        if interruption
                        else []
                    ),
                ),
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
        completed_speakers: list[str] = []

        for speaker in speech_order:
            if self._maybe_run_werewolf_self_explosion(
                round_state,
                round_log,
                active_players,
                PublicStageCursor(
                    stage="debate",
                    ordered_actors=tuple(speech_order),
                    completed_actors=tuple(completed_speakers),
                    current_actor=speaker,
                    timing="before_actor",
                ),
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
            completed_speakers.append(speaker)
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
                PublicStageCursor(
                    stage="debate",
                    ordered_actors=tuple(speech_order),
                    completed_actors=tuple(completed_speakers),
                    current_actor=speaker,
                    timing="after_actor",
                ),
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
        cursor: PublicStageCursor,
    ) -> bool:
        if not self.rule_set.werewolf_self_explosion_enabled:
            return False
        if self.state.winner:
            return False

        pending = self._pending_self_explosion
        if pending is not None and pending.round_number != round_state.number:
            self._cancel_pending_self_explosion()
            pending = None

        if pending is not None:
            if not all(future.done() for future in pending.futures):
                wait(pending.futures, timeout=SELF_EXPLOSION_HANDOFF_TIMEOUT_SECONDS)
                if not all(future.done() for future in pending.futures):
                    return False
            self._pending_self_explosion = None
            decisions = self._finish_pending_self_explosion(pending)
            players_by_name = self.state.player_by_name()
            for name, (choice, action_log) in zip(
                pending.active_wolves,
                decisions,
                strict=True,
            ):
                if (
                    choice != WEREWOLF_SELF_EXPLODE
                    or name not in active_players
                    or not self._is_werewolf(players_by_name[name])
                ):
                    continue

                round_log.werewolf_self_explosion = action_log
                round_state.interruption = self._stage_interruption_from_cursor(
                    cursor,
                    actor=name,
                )
                self._resolve_werewolf_self_explosion(
                    wolf=name,
                    round_state=round_state,
                    round_log=round_log,
                    active_players=active_players,
                )
                interruption_text = self._stage_interruption_text(
                    round_state.number,
                    round_state.interruption,
                )
                self._add_public_fact(
                    round_state.number,
                    "interruption",
                    interruption_text,
                    stage=cursor.stage,
                    actor=name,
                    retention="critical",
                    details=round_state.interruption.to_dict(),
                )
                self._refresh_winner(active_players)
                return True

        players_by_name = self.state.player_by_name()
        active_wolves = [
            name for name in active_players if self._is_werewolf(players_by_name[name])
        ]
        requests = tuple(
            self._build_player_action_request(
                player=players_by_name[name],
                action=ACTION_WEREWOLF_SELF_EXPLOSION,
                options=[WEREWOLF_SELF_EXPLODE, WEREWOLF_NO_SELF_EXPLODE],
                result_key="self_explode",
                round_state=round_state,
                phase="day",
                extra_world_state={
                    "self_explosion_stage": self._self_explosion_stage_description(cursor),
                    "self_explosion_decision_context": (
                        self._self_explosion_decision_context(
                            actor=name,
                            round_state=round_state,
                            active_players=active_players,
                            active_wolves=active_wolves,
                            cursor=cursor,
                        ).to_dict()
                    ),
                    "self_explosion_stage_context": {
                        "stage": cursor.stage,
                        "timing": cursor.timing,
                        "current_actor": cursor.current_actor,
                        "completed_actors": list(cursor.completed_actors),
                        "pending_actors": cursor.pending_actors,
                    },
                },
            )
            for name in active_wolves
        )
        self._start_pending_self_explosion(
            round_number=round_state.number,
            active_wolves=tuple(active_wolves),
            requests=requests,
        )
        return False

    def _start_pending_self_explosion(
        self,
        *,
        round_number: int,
        active_wolves: tuple[str, ...],
        requests: tuple[PlayerActionRequest, ...],
    ) -> None:
        if not requests:
            return
        if self._self_explosion_executor is None:
            self._self_explosion_executor = ThreadPoolExecutor(
                max_workers=max(1, len(self.state.players)),
                thread_name_prefix="werewolf-self-explosion",
            )

        condition = threading.Condition()
        next_index = {"value": 0}
        futures = tuple(
            self._self_explosion_executor.submit(
                self._execute_player_action_request,
                request,
                _OrderedBatchProvider(
                    provider=self.provider,
                    index=index,
                    condition=condition,
                    next_index=next_index,
                ),
                NullEventSink(),
            )
            for index, request in enumerate(requests)
        )
        self._pending_self_explosion = PendingSelfExplosionBatch(
            round_number=round_number,
            active_wolves=active_wolves,
            requests=requests,
            futures=futures,
            started_at=self.monotonic(),
        )

    def _finish_pending_self_explosion(
        self,
        pending: PendingSelfExplosionBatch,
    ) -> list[tuple[object | None, ActionLog]]:
        results: list[PlayerActionResult | None] = [None] * len(pending.futures)
        exceptions: dict[int, Exception] = {}
        for index, future in enumerate(pending.futures):
            try:
                results[index] = future.result()
            except Exception as exc:
                exceptions[index] = exc

        if self.action_budgets_enabled:
            record_action_batch(
                action_kind=self.action_execution_budget.for_action(
                    ACTION_WEREWOLF_SELF_EXPLOSION
                ).kind,
                result="failed" if exceptions else "completed",
                duration_ms=max(
                    0,
                    round((self.monotonic() - pending.started_at) * 1000),
                ),
            )
        self._checkpoint_player_action_results(results)
        if exceptions:
            first_failed_index = min(exceptions)
            request = pending.requests[first_failed_index]
            exc = exceptions[first_failed_index]
            self._checkpoint_player_action_failure(request, exc)
            raise exc

        finalized: list[tuple[object | None, ActionLog]] = []
        for result in results:
            if result is None:
                raise RuntimeError("Self-explosion batch completed without a result.")
            try:
                finalized.append(self._finalize_player_action_result(result, checkpoint=False))
            except Exception as exc:
                self._checkpoint_player_action_failure(result.request, exc)
                raise
        return finalized

    def _cancel_pending_self_explosion(self) -> None:
        pending = self._pending_self_explosion
        self._pending_self_explosion = None
        if pending is None:
            return
        for future in pending.futures:
            future.cancel()

    def _shutdown_self_explosion_worker(self) -> None:
        self._cancel_pending_self_explosion()
        executor = self._self_explosion_executor
        self._self_explosion_executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def _self_explosion_decision_context(
        self,
        *,
        actor: str,
        round_state: RoundState,
        active_players: list[str],
        active_wolves: list[str],
        cursor: PublicStageCursor,
    ) -> SelfExplosionDecisionContext:
        prior_rounds = [
            existing for existing in self.state.rounds if existing.number < round_state.number
        ]
        total_self_explosions = sum(
            existing.werewolf_self_exploded is not None for existing in prior_rounds
        )
        explosions_by_round = {
            existing.number: existing.werewolf_self_exploded is not None
            for existing in prior_rounds
        }
        consecutive_self_explosions = 0
        prior_number = round_state.number - 1
        while explosions_by_round.get(prior_number) is True:
            consecutive_self_explosions += 1
            prior_number -= 1

        speech_stage = cursor.stage in {"debate", "sheriff_speech", "sheriff_pk_speech"}
        active_after = [name for name in active_players if name != actor]
        return SelfExplosionDecisionContext(
            total_self_explosions=total_self_explosions,
            consecutive_self_explosion_rounds=consecutive_self_explosions,
            active_wolves_before=len(active_wolves),
            actor_is_last_wolf=len(active_wolves) == 1 and actor in active_wolves,
            active_players_before=len(active_players),
            current_stage=cursor.stage,
            completed_public_speakers=(len(cursor.completed_actors) if speech_stage else 0),
            pending_public_speakers=(len(cursor.pending_actors) if speech_stage else 0),
            sheriff_election_open=self._should_run_sheriff_election(round_state),
            pre_election_bomb_count=self.state.sheriff_pre_election_bomb_count,
            badge_impact=self._self_explosion_badge_impact(actor, round_state),
            explosion_would_end_game=bool(self._get_winner(active_after)),
        )

    def _self_explosion_badge_impact(
        self,
        actor: str,
        round_state: RoundState,
    ) -> str:
        if not self.rule_set.sheriff_enabled:
            return "none"
        if self.state.sheriff == actor:
            return "owner_must_transfer_or_destroy"
        if self.state.sheriff:
            return "none"
        if not self._should_run_sheriff_election(round_state):
            return "none"
        if self.rule_set.sheriff_badge_bomb_policy == "double":
            if self.state.sheriff_pre_election_bomb_count >= 1:
                return "badge_will_be_lost"
            return "election_postponed"
        return "election_interrupted"

    def _stage_interruption_from_cursor(
        self,
        cursor: PublicStageCursor,
        *,
        actor: str,
    ) -> StageInterruption:
        speech_stages = {"debate", "sheriff_speech", "sheriff_pk_speech"}
        last_completed_speaker = (
            cursor.completed_actors[-1]
            if cursor.stage in speech_stages and cursor.completed_actors
            else None
        )
        return StageInterruption(
            stage=cursor.stage,
            interrupted_by="werewolf_self_explosion",
            actor=actor,
            timing=cursor.timing,
            last_completed_speaker=last_completed_speaker,
            completed_actors=list(cursor.completed_actors),
            pending_actors=cursor.pending_actors,
        )

    def _stage_interruption_text(
        self,
        round_number: int,
        interruption: StageInterruption,
    ) -> str:
        stage_labels = {
            "debate": "白天发言",
            "sheriff_speech": "警上发言",
            "sheriff_withdraw": "退水",
            "sheriff_vote": "警下投票",
            "sheriff_pk_speech": "警长PK发言",
            "sheriff_runoff_vote": "二轮警下投票",
        }
        label = stage_labels.get(interruption.stage, interruption.stage)
        parts = [f"第{round_number}轮{label}因{interruption.actor}自爆而中断"]
        is_speech = interruption.stage in {
            "debate",
            "sheriff_speech",
            "sheriff_pk_speech",
        }
        if interruption.completed_actors:
            completed_label = "已完成发言" if is_speech else "已完成动作"
            parts.append(f"{completed_label}：{'、'.join(interruption.completed_actors)}")
        if interruption.pending_actors:
            if is_speech:
                parts.append(
                    f"{'、'.join(interruption.pending_actors)}尚未获得发言机会，"
                    "不能将其视为主动沉默"
                )
            else:
                parts.append(f"尚未完成动作：{'、'.join(interruption.pending_actors)}")
        return "；".join(parts) + "。"

    def _self_explosion_stage_description(self, cursor: PublicStageCursor) -> str:
        stage_labels = {
            "debate": "发言",
            "sheriff_speech": "警上发言",
            "sheriff_withdraw": "退水",
            "sheriff_vote": "警下投票",
            "sheriff_pk_speech": "PK 发言",
            "sheriff_runoff_vote": "二轮警下投票",
        }
        label = stage_labels.get(cursor.stage, cursor.stage)
        if cursor.timing == "before_actor" and cursor.current_actor:
            return f"{cursor.current_actor} {label}前"
        if cursor.timing == "after_actor" and cursor.current_actor:
            return f"{cursor.current_actor} {label}后"
        return f"{label}前"

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
        self._append_public_outcome(
            round_state=round_state,
            kind="self_explosion",
            actor_player=wolf,
            outcome="self_exploded",
            phase="day",
        )
        self._remove_player(active_players, wolf)
        self._announce(
            active_players, f"第{round_state.number}轮：{wolf}自爆为狼人，白天立即结束。"
        )
        self._add_public_fact(
            round_state.number,
            "reveal",
            f"第{round_state.number}轮：{wolf}自爆为狼人，白天立即结束。",
            stage="werewolf_self_explosion",
            actor=wolf,
            retention="critical",
            details={"player": wolf},
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
            self._lose_sheriff_badge(
                round_state,
                active_players,
                "double_pre_election_self_explosion",
            )
            return

        self._resolve_sheriff_election(
            round_state,
            active_players,
            outcome="postponed",
            reason_code="first_pre_election_self_explosion",
        )

    def _run_sheriff_election_if_needed(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> bool:
        round_state.sheriff = self.state.sheriff
        if not self._should_run_sheriff_election(round_state):
            return False

        self._publish_judge_cue(
            round_state,
            "day",
            cue_spec(
                "sheriff_raise_hands",
                static_asset_id="sheriff_raise_hands",
            ),
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
            self._lose_sheriff_badge(round_state, active_players, "no_candidates")
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
            PublicStageCursor(
                stage="sheriff_speech",
                ordered_actors=tuple(sheriff_speech_order),
                timing="before_stage",
            ),
        ):
            return True

        completed_sheriff_speakers: list[str] = []
        for name in sheriff_speech_order:
            if self._maybe_run_werewolf_self_explosion(
                round_state,
                round_log,
                active_players,
                PublicStageCursor(
                    stage="sheriff_speech",
                    ordered_actors=tuple(sheriff_speech_order),
                    completed_actors=tuple(completed_sheriff_speakers),
                    current_actor=name,
                    timing="before_actor",
                ),
            ):
                return True
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
                stage="sheriff_speech",
                actor=name,
                retention="important",
            )
            completed_sheriff_speakers.append(name)
            if self._maybe_run_werewolf_self_explosion(
                round_state,
                round_log,
                active_players,
                PublicStageCursor(
                    stage="sheriff_speech",
                    ordered_actors=tuple(sheriff_speech_order),
                    completed_actors=tuple(completed_sheriff_speakers),
                    current_actor=name,
                    timing="after_actor",
                ),
            ):
                return True

        if self._maybe_run_werewolf_self_explosion(
            round_state,
            round_log,
            active_players,
            PublicStageCursor(
                stage="sheriff_withdraw",
                ordered_actors=tuple(candidates),
                timing="before_stage",
            ),
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
            self._lose_sheriff_badge(
                round_state,
                active_players,
                "all_candidates_withdrew",
            )
            return False

        if len(final_candidates) == 1:
            self._elect_sheriff(
                final_candidates[0],
                round_state,
                active_players,
                reason_code="single_candidate",
            )
            return False

        if not voters:
            self._lose_sheriff_badge(
                round_state,
                active_players,
                "no_off_sheriff_voters",
            )
            return False

        if self._maybe_run_werewolf_self_explosion(
            round_state,
            round_log,
            active_players,
            PublicStageCursor(
                stage="sheriff_vote",
                ordered_actors=tuple(voters),
                timing="before_stage",
            ),
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
            self._lose_sheriff_badge(round_state, active_players, "first_vote_empty")
            return False

        if len(first_round_winners) == 1:
            self._elect_sheriff(
                first_round_winners[0],
                round_state,
                active_players,
                reason_code="first_vote_winner",
            )
            return False

        tied_candidates = set(first_round_winners)
        pk_candidates = [name for name in final_candidates if name in tied_candidates]
        round_state.sheriff_pk_candidates = pk_candidates
        self._publish_state_updated(
            round_state=round_state,
            phase="day",
            action="sheriff_pk_started",
            payload={
                "narration_mode": "explicit_v1",
                "sheriff_pk_candidates": pk_candidates.copy(),
                "sheriff_voters": round_state.sheriff_voters.copy(),
                "sheriff_votes": round_state.sheriff_votes.copy(),
            },
        )
        tie_cues = sheriff_tie_cues([self._public_player_reference(name) for name in pk_candidates])
        self._publish_judge_cues(round_state, "day", tie_cues[:2])

        if self._maybe_run_werewolf_self_explosion(
            round_state,
            round_log,
            active_players,
            PublicStageCursor(
                stage="sheriff_pk_speech",
                ordered_actors=tuple(pk_candidates),
                timing="before_stage",
            ),
        ):
            return True

        completed_pk_speakers: list[str] = []
        for name in pk_candidates:
            if self._maybe_run_werewolf_self_explosion(
                round_state,
                round_log,
                active_players,
                PublicStageCursor(
                    stage="sheriff_pk_speech",
                    ordered_actors=tuple(pk_candidates),
                    completed_actors=tuple(completed_pk_speakers),
                    current_actor=name,
                    timing="before_actor",
                ),
            ):
                return True
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
            self._publish_action_quality_warnings(
                round_state=round_state,
                phase="day",
                actor=name,
                action=ACTION_SHERIFF_PK_SPEECH,
                text=message,
            )
            self._add_public_fact(
                round_state.number,
                "claim",
                f"第{round_state.number}轮警长PK发言：{name}：{message}",
                stage="sheriff_pk_speech",
                actor=name,
                retention="critical",
            )
            completed_pk_speakers.append(name)
            if self._maybe_run_werewolf_self_explosion(
                round_state,
                round_log,
                active_players,
                PublicStageCursor(
                    stage="sheriff_pk_speech",
                    ordered_actors=tuple(pk_candidates),
                    completed_actors=tuple(completed_pk_speakers),
                    current_actor=name,
                    timing="after_actor",
                ),
            ):
                return True

        if self._maybe_run_werewolf_self_explosion(
            round_state,
            round_log,
            active_players,
            PublicStageCursor(
                stage="sheriff_runoff_vote",
                ordered_actors=tuple(voters),
                timing="before_stage",
            ),
        ):
            return True

        self._publish_judge_cue(round_state, "day", tie_cues[2])

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
            self._lose_sheriff_badge(round_state, active_players, "runoff_tied")
            return False

        self._elect_sheriff(
            sheriff,
            round_state,
            active_players,
            reason_code="runoff_vote_winner",
        )
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
        *,
        reason_code: SheriffElectionReason,
    ) -> None:
        self._resolve_sheriff_election(
            round_state,
            active_players,
            outcome="elected",
            reason_code=reason_code,
            sheriff=sheriff,
        )

    def _lose_sheriff_badge(
        self,
        round_state: RoundState,
        active_players: list[str],
        reason_code: SheriffElectionReason,
    ) -> None:
        self._resolve_sheriff_election(
            round_state,
            active_players,
            outcome="badge_lost",
            reason_code=reason_code,
        )

    def _resolve_sheriff_election(
        self,
        round_state: RoundState,
        active_players: list[str],
        *,
        outcome: SheriffElectionOutcome,
        reason_code: SheriffElectionReason,
        sheriff: str | None = None,
    ) -> None:
        reason_text = SHERIFF_ELECTION_REASON_TEXT[reason_code]
        badge_lost = outcome == "badge_lost"
        election_pending = outcome == "postponed"
        self._set_sheriff(sheriff if outcome == "elected" else None)
        self.state.sheriff_badge_lost = badge_lost
        self.state.sheriff_election_pending = election_pending
        round_state.sheriff = sheriff if outcome == "elected" else None
        round_state.sheriff_elected = sheriff if outcome == "elected" else None
        round_state.sheriff_badge_lost = badge_lost
        round_state.sheriff_election_pending = election_pending
        round_state.sheriff_badge_lost_reason = reason_text if outcome != "elected" else None
        resolution = SheriffElectionResolution(
            schema_version=1,
            outcome=outcome,
            reason_code=reason_code,
            reason_text=reason_text,
            sheriff=sheriff if outcome == "elected" else None,
            candidates=round_state.sheriff_candidates.copy(),
            withdrawn=round_state.sheriff_withdrawn.copy(),
            final_candidates=round_state.sheriff_final_candidates.copy(),
            voters=round_state.sheriff_voters.copy(),
            votes=round_state.sheriff_votes.copy(),
            pk_candidates=round_state.sheriff_pk_candidates.copy(),
            runoff_votes=round_state.sheriff_runoff_votes.copy(),
            badge_lost=badge_lost,
            election_pending=election_pending,
        )
        round_state.sheriff_election_resolution = resolution
        public_outcome: PublicOutcomeEventV1 | None = None
        if outcome == "elected" and sheriff:
            public_outcome = self._append_public_outcome(
                round_state=round_state,
                kind="badge_transferred",
                target_player=sheriff,
                outcome="elected",
                phase="day",
            )
        elif outcome == "badge_lost":
            public_outcome = self._append_public_outcome(
                round_state=round_state,
                kind="badge_lost",
                outcome=reason_code,
                phase="day",
                caused_by_event=(
                    round_state.public_outcome_events[-1]
                    if reason_code == "double_pre_election_self_explosion"
                    and round_state.public_outcome_events
                    and round_state.public_outcome_events[-1].kind == "self_explosion"
                    else None
                ),
            )
        if outcome == "elected":
            text = (
                f"第{round_state.number}轮：警长竞选，{sheriff}当选警长，"
                f"投票计为{self.rule_set.sheriff_vote_weight:g}票。"
            )
            stage = "sheriff_elected"
            details: dict[str, object] = {
                "sheriff": sheriff,
                "vote_weight": self.rule_set.sheriff_vote_weight,
                "reason_code": reason_code,
            }
        elif outcome == "postponed":
            text = f"第{round_state.number}轮：{reason_text}，警长竞选顺延。"
            stage = "sheriff_election_postponed"
            details = {"reason": reason_text, "reason_code": reason_code}
        else:
            text = f"第{round_state.number}轮：{reason_text}，警徽流失。"
            stage = "sheriff_badge_lost"
            details = {"reason": reason_text, "reason_code": reason_code}
        self._announce(active_players, text)
        self._add_public_fact(
            round_state.number,
            "sheriff",
            text,
            stage=stage,
            actor=sheriff,
            retention="critical",
            details=details,
        )
        self._publish_state_updated(
            round_state=round_state,
            phase="day",
            actor=sheriff,
            action="sheriff_election_resolved",
            payload={
                "narration_mode": "explicit_v1",
                "sheriff_election": resolution.to_dict(),
                "sheriff": resolution.sheriff,
                "sheriff_elected": resolution.sheriff,
                "sheriff_candidates": resolution.candidates.copy(),
                "sheriff_final_candidates": resolution.final_candidates.copy(),
                "sheriff_voters": resolution.voters.copy(),
                "sheriff_votes": resolution.votes.copy(),
                "sheriff_runoff_votes": resolution.runoff_votes.copy(),
                "sheriff_badge_lost": resolution.badge_lost,
                "sheriff_badge_lost_reason": round_state.sheriff_badge_lost_reason,
                "sheriff_election_pending": resolution.election_pending,
                "active_players": active_players.copy(),
            },
        )
        public_resolution = SheriffElectionResolution(
            **{
                **resolution.to_dict(),
                "sheriff": (
                    public_outcome.target_player_id
                    if public_outcome and public_outcome.kind == "badge_transferred"
                    else None
                ),
                "candidates": [
                    self._public_player_reference(name) for name in resolution.candidates
                ],
                "withdrawn": [self._public_player_reference(name) for name in resolution.withdrawn],
                "final_candidates": [
                    self._public_player_reference(name) for name in resolution.final_candidates
                ],
                "voters": [self._public_player_reference(name) for name in resolution.voters],
                "votes": {
                    self._public_player_reference(voter): self._public_player_reference(target)
                    for voter, target in resolution.votes.items()
                },
                "pk_candidates": [
                    self._public_player_reference(name) for name in resolution.pk_candidates
                ],
                "runoff_votes": {
                    self._public_player_reference(voter): self._public_player_reference(target)
                    for voter, target in resolution.runoff_votes.items()
                },
            }
        )
        self._publish_judge_cues(
            round_state,
            "day",
            sheriff_election_cues(public_resolution),
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
            idiot_outcome = self._append_public_outcome(
                round_state=round_state,
                kind="idiot_reveal",
                actor_player=exiled,
                outcome="survived",
                phase="vote",
            )
            self._announce(
                active_players,
                f"第{round_state.number}轮：白天投票，{exiled}翻开白痴身份，免于出局但失去投票权。",
            )
            self._publish_state_updated(
                round_state=round_state,
                phase="vote",
                actor=exiled,
                action="idiot_revealed",
                payload={
                    "narration_mode": "explicit_v1",
                    "idiot_revealed": exiled,
                    "active_players": active_players.copy(),
                },
            )
            self._publish_judge_cues(
                round_state,
                "vote",
                idiot_reveal_cues(idiot_outcome.actor_player_id or ""),
            )
            return

        round_state.exiled = exiled
        self._remove_player(active_players, exiled)
        round_state.day_deaths.append(DeathEvent(exiled, "vote_exile", "投票"))
        exile_outcome = self._append_public_outcome(
            round_state=round_state,
            kind="exile",
            target_player=exiled,
            outcome="eliminated",
            phase="vote",
        )
        exile_text = f"第{round_state.number}轮：白天投票，{exiled}被放逐。"
        self._announce(active_players, exile_text)
        self._add_public_fact(
            round_state.number,
            "death",
            exile_text,
            stage="vote_exile",
            actor=exiled,
            retention="critical",
            details={"player": exiled},
        )
        self._publish_state_updated(
            round_state=round_state,
            phase="vote",
            actor=exiled,
            action="exile_resolved",
            payload={
                "narration_mode": "explicit_v1",
                "exiled": exiled,
                "day_deaths": [death.to_dict() for death in round_state.day_deaths],
                "active_players": active_players.copy(),
            },
        )
        self._publish_judge_cue(
            round_state,
            "vote",
            exile_result_cue(exile_outcome.target_player_id or ""),
        )
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

        self._publish_judge_cue(
            round_state,
            phase,
            cue_spec(
                "badge_owner_out",
                static_asset_id="badge_owner_out",
                params={"from_player": self._public_player_reference(dead_player)},
            ),
        )
        if not active_players:
            self._resolve_sheriff_badge(
                round_state=round_state,
                active_players=active_players,
                phase=phase,
                from_player=dead_player,
                outcome="lost_no_target",
                to_player=None,
                reason_code="no_eligible_target",
            )
            return

        excluded_badge_targets = excluded_badge_targets or set()
        badge_options = [name for name in active_players if name not in excluded_badge_targets]
        if not badge_options:
            self._resolve_sheriff_badge(
                round_state=round_state,
                active_players=active_players,
                phase=phase,
                from_player=dead_player,
                outcome="lost_no_target",
                to_player=None,
                reason_code="no_eligible_target",
            )
            return
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
            self._resolve_sheriff_badge(
                round_state=round_state,
                active_players=active_players,
                phase=phase,
                from_player=dead_player,
                outcome="transferred",
                to_player=choice,
                reason_code="owner_selected_target",
            )
            return

        self._resolve_sheriff_badge(
            round_state=round_state,
            active_players=active_players,
            phase=phase,
            from_player=dead_player,
            outcome="destroyed",
            to_player=None,
            reason_code="destroyed_by_owner",
        )

    def _resolve_sheriff_badge(
        self,
        *,
        round_state: RoundState,
        active_players: list[str],
        phase: str,
        from_player: str,
        outcome: SheriffBadgeOutcome,
        to_player: str | None,
        reason_code: str,
    ) -> None:
        transferred = outcome == "transferred" and to_player is not None
        self._set_sheriff(to_player if transferred else None)
        self.state.sheriff_badge_lost = not transferred
        round_state.sheriff = to_player if transferred else None
        round_state.sheriff_badge_target = to_player if transferred else None
        round_state.sheriff_badge_lost = not transferred
        resolution = SheriffBadgeResolution(
            schema_version=1,
            outcome=outcome,
            from_player=from_player,
            to_player=to_player if transferred else None,
            reason_code=reason_code,
        )
        round_state.sheriff_badge_resolution = resolution
        public_outcome = self._append_public_outcome(
            round_state=round_state,
            kind="badge_transferred" if transferred else "badge_lost",
            actor_player=from_player,
            target_player=to_player if transferred else None,
            outcome=outcome,
            phase=phase,
            caused_by_event=self._latest_player_outcome(
                round_state,
                from_player,
            ),
        )
        if transferred:
            text = f"第{round_state.number}轮：{from_player}出局，将警徽移交给{to_player}。"
            stage = "sheriff_badge_transfer"
            details: dict[str, object] = {"target": to_player, "reason_code": reason_code}
        elif outcome == "lost_no_target":
            text = f"第{round_state.number}轮：{from_player}出局，无可移交目标，警徽流失。"
            stage = "sheriff_badge_lost"
            details = {"reason": "no_eligible_target", "reason_code": reason_code}
        else:
            text = f"第{round_state.number}轮：{from_player}出局，警徽被撕毁。"
            stage = "sheriff_badge_destroyed"
            details = {"reason": "destroyed", "reason_code": reason_code}
        self._announce(active_players, text)
        self._add_public_fact(
            round_state.number,
            "sheriff",
            text,
            stage=stage,
            actor=from_player,
            retention="critical",
            details=details,
        )
        self._publish_state_updated(
            round_state=round_state,
            phase=phase,
            actor=from_player,
            action="sheriff_badge_resolved",
            payload={
                "narration_mode": "explicit_v1",
                "sheriff_badge": resolution.to_dict(),
                "sheriff": round_state.sheriff,
                "sheriff_badge_target": round_state.sheriff_badge_target,
                "sheriff_badge_lost": round_state.sheriff_badge_lost,
                "active_players": active_players.copy(),
            },
        )
        public_resolution = SheriffBadgeResolution(
            schema_version=resolution.schema_version,
            outcome=resolution.outcome,
            from_player=public_outcome.actor_player_id or "",
            to_player=public_outcome.target_player_id,
            reason_code=resolution.reason_code,
        )
        self._publish_judge_cues(
            round_state,
            phase,
            sheriff_badge_cues(public_resolution)[1:],
        )

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
        self._publish_public_round_brief(round_state, active_players)
        self._run_private_round_memories(round_state, round_log, active_players)

    def _publish_public_round_brief(
        self,
        round_state: RoundState,
        active_players: list[str],
    ) -> None:
        self._publish(
            "phase_started",
            round_number=round_state.number,
            phase="summary",
            payload={"active_players": active_players.copy()},
        )
        round_state.public_summary = self._public_round_brief(round_state)
        self._publish_state_updated(
            round_state=round_state,
            phase="summary",
            action="public_round_brief",
            payload={"public_summary": round_state.public_summary},
        )

    def _run_private_round_memories(
        self,
        round_state: RoundState,
        round_log: RoundLog,
        active_players: list[str],
    ) -> None:
        players_by_name = self.state.player_by_name()
        requests = [
            self._build_player_action_request(
                player=players_by_name[name],
                action="summarize",
                options=[],
                result_key="summary",
                round_state=round_state,
                phase="summary",
            )
            for name in active_players
        ]
        if not requests:
            return

        condition = threading.Condition()
        next_index = {"value": 0}
        executor = ThreadPoolExecutor(max_workers=len(requests))
        futures = [
            executor.submit(
                self._execute_player_action_request,
                request,
                _OrderedBatchProvider(
                    provider=self.provider,
                    index=index,
                    condition=condition,
                    next_index=next_index,
                ),
            )
            for index, request in enumerate(requests)
        ]
        try:
            for index, (name, request, future) in enumerate(
                zip(active_players, requests, futures, strict=True)
            ):
                try:
                    result = future.result()
                    summary, action_log = self._finalize_player_action_result(result)
                except Exception as exc:
                    self._checkpoint_player_action_failure(request, exc)
                    for pending_future in futures[index + 1 :]:
                        pending_future.cancel()
                    raise
                player = players_by_name[name]
                if isinstance(summary, str) and summary:
                    round_state.private_summaries[name] = summary
                    player.add_observation(f"第{round_state.number}轮总结：{summary}")
                round_log.summaries.append(action_log)
        finally:
            executor.shutdown(wait=True, cancel_futures=True)

    def _public_round_brief(self, round_state: RoundState) -> str:
        if round_state.public_outcome_events:
            return (
                f"第{round_state.number}轮；"
                f"{render_public_round_summary(round_state.public_outcome_events)}"
            )
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
        self._require_non_terminal_player_action()
        options_snapshot = options.copy()
        public_options = [self._public_player_reference(option) for option in options_snapshot]
        public_choice_to_internal = dict(zip(public_options, options_snapshot, strict=True))
        world_state = self._world_state(player, options_snapshot, round_state)
        if action == ACTION_SHERIFF_SPEECH:
            world_state["public_facts"] = self._public_fact_lines(
                sheriff_speech_context_round=round_state.number,
            )
            world_state["sheriff_election"] = self._sheriff_election_context(
                round_state,
                compact_prior_speeches=True,
            )
            world_state["compact_sheriff_speech_context"] = True
        if extra_world_state:
            world_state.update(extra_world_state)
        if action in BUFFERED_QUALITY_ACTIONS:
            prior_speeches, speech_order = self._speech_stage_context(
                action,
                round_state,
                player,
            )
            public_prior_speeches = [self._public_text(message) for message in prior_speeches]
            mission = assign_speech_mission(
                round_number=round_state.number,
                stage=action,
                speaker=player.name,
                speech_order=speech_order,
                prior_messages=public_prior_speeches,
                personality_id=player.personality_id,
                has_public_evidence=bool(
                    public_prior_speeches
                    or self.state.public_facts
                    or round_state.night_deaths
                    or round_state.day_deaths
                ),
            )
            world_state["speech_mission"] = mission.to_dict()
            world_state["speech_prior_texts"] = public_prior_speeches
        world_state = self._public_model_world_state(copy.deepcopy(world_state))
        world_state["options"] = "、".join(public_options)
        facts = [
            replace(
                public_fact_from_dict(item),
                text=self._public_text(str(item.get("text") or "")),
            )
            for item in self.state.public_facts
            if isinstance(item, dict)
        ]
        coverage = fact_prompt_coverage(
            facts,
            [str(item) for item in world_state.get("public_facts", [])],
        )
        event_visibility = self._player_action_event_visibility(phase, action)
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
            event_visibility=event_visibility,
            fact_prompt_coverage=coverage,
        )

    def _execute_player_action_request(
        self,
        request: PlayerActionRequest,
        provider: ModelProvider | None = None,
        event_sink: object | None = None,
        deadline_at_monotonic: float | None = None,
        timeout_fallback: bool = True,
    ) -> PlayerActionResult:
        self._require_non_terminal_player_action()
        action_provider = provider or self.provider
        public_event_sink = event_sink or self.event_sink
        started_at = self.monotonic()
        budget_spec = self.action_execution_budget.for_action(request.action)
        call_options = budget_spec.call_options(started_at) if self.action_budgets_enabled else None
        if deadline_at_monotonic is not None:
            remaining_seconds = max(0.0, deadline_at_monotonic - started_at)
            if remaining_seconds <= 0:
                if not timeout_fallback:
                    raise ModelDeadlineExceeded("model action deadline exceeded")
                return self._timeout_fallback_result(
                    request,
                    started_at=started_at,
                    budget_ms=0,
                )
            if call_options is None:
                call_options = ModelCallOptions(
                    deadline_at_monotonic=deadline_at_monotonic,
                    request_timeout_seconds=remaining_seconds,
                )
            else:
                effective_deadline = min(
                    call_options.deadline_at_monotonic,
                    deadline_at_monotonic,
                )
                effective_remaining = max(0.0, effective_deadline - started_at)
                call_options = replace(
                    call_options,
                    deadline_at_monotonic=effective_deadline,
                    request_timeout_seconds=min(
                        call_options.request_timeout_seconds,
                        effective_remaining,
                    ),
                )
        try:
            if self._should_buffer_quality_action(request):
                value, lm_log = self._generate_buffered_quality_action(
                    request,
                    action_provider,
                    call_options=call_options,
                    event_sink=public_event_sink,
                )
            else:
                value, lm_log = self._generate_action_for_request(
                    request,
                    action_provider,
                    event_sink=(
                        public_event_sink
                        if request.event_visibility == "public"
                        else NullEventSink()
                    ),
                    call_options=call_options,
                )
        except ModelDeadlineExceeded:
            if not timeout_fallback:
                raise
            return self._timeout_fallback_result(
                request,
                started_at=started_at,
                budget_ms=(
                    round(budget_spec.total_budget_seconds * 1000)
                    if self.action_budgets_enabled
                    else None
                ),
            )
        except Exception:
            release_turn = getattr(action_provider, "release_turn_if_not_started", None)
            if callable(release_turn):
                release_turn()
            raise
        if isinstance(value, str) and request.public_choice_to_internal:
            value = request.public_choice_to_internal.get(value, value)
        return PlayerActionResult(
            request=request,
            value=value,
            lm_log=lm_log,
            duration_ms=(
                max(0, round((self.monotonic() - started_at) * 1000))
                if self.action_budgets_enabled
                else 0
            ),
            budget_ms=(
                round(budget_spec.total_budget_seconds * 1000)
                if self.action_budgets_enabled
                else None
            ),
        )

    def _generate_action_for_request(
        self,
        request: PlayerActionRequest,
        provider: ModelProvider,
        *,
        event_sink: object,
        world_state: dict[str, object] | None = None,
        call_options: ModelCallOptions | None = None,
    ) -> tuple[object | None, LmLog]:
        return generate_action_with_events(
            provider=provider,
            action=request.action,
            world_state=world_state or request.world_state,
            model=request.player.model,
            allowed_values=request.public_options if request.public_options else None,
            result_key=request.result_key,
            event_sink=event_sink,
            event_context={
                "round_number": request.round_state.number,
                "phase": request.phase,
                "actor": request.player.name,
                "action": request.action,
            },
            call_options=call_options,
        )

    def _should_buffer_quality_action(self, request: PlayerActionRequest) -> bool:
        if request.event_visibility != "public" or request.action not in BUFFERED_QUALITY_ACTIONS:
            return False
        if self.speech_quality_retry_enabled:
            return True
        if request.action != ACTION_DEBATE:
            return True
        active_players = (
            request.player.gamestate.current_players
            if request.player.gamestate
            else request.round_state.players
        )
        return len(active_players) <= 4

    def _generate_buffered_quality_action(
        self,
        request: PlayerActionRequest,
        provider: ModelProvider,
        *,
        call_options: ModelCallOptions | None,
        event_sink: object,
    ) -> tuple[object | None, LmLog]:
        world_state = copy.deepcopy(request.world_state)
        initial_codes: list[str] = []
        for quality_attempt in range(2):
            buffer = _BufferedEventSink()
            value, lm_log = self._generate_action_for_request(
                request,
                provider,
                event_sink=buffer,
                world_state=world_state,
                call_options=call_options,
            )
            quality_report = self._speech_quality_report(request, lm_log)
            hard_warnings = self._hard_quality_warnings(request, lm_log)
            if self.speech_quality_retry_enabled and quality_report is not None:
                hard_warnings = list(
                    dict.fromkeys([*hard_warnings, *quality_report.hard_failure_codes])
                )
            if not hard_warnings or quality_attempt == 1:
                self._attach_speech_quality_metadata(
                    request=request,
                    lm_log=lm_log,
                    report=quality_report,
                    attempt_count=quality_attempt + 1,
                    retry_exhausted=bool(hard_warnings and quality_attempt == 1),
                    initial_codes=initial_codes,
                )
                buffer.flush_to(event_sink)
                return value, lm_log
            initial_codes = hard_warnings.copy()
            publish = getattr(event_sink, "publish")
            record_model_progress_event("model_retry_scheduled")
            publish(
                "model_retry_scheduled",
                round_number=request.round_state.number,
                phase=request.phase,
                actor=request.player.name,
                action=request.action,
                payload={
                    "request_id": lm_log.request_id,
                    "model": request.player.model,
                    "attempt": quality_attempt + 2,
                    "quality_codes": hard_warnings,
                    "message": "发言质量未通过，正在带反馈重写一次。",
                },
            )
            world_state["quality_feedback"] = self._quality_feedback(hard_warnings)
        raise RuntimeError("buffered quality retry loop ended unexpectedly")

    def _hard_quality_warnings(
        self,
        request: PlayerActionRequest,
        lm_log: LmLog,
    ) -> list[str]:
        result = lm_log.result or {}
        text = result.get(request.result_key)
        if not isinstance(text, str):
            return []
        active_players = (
            request.player.gamestate.current_players
            if request.player.gamestate
            else request.round_state.players
        )
        eligibility = request.world_state.get("public_action_eligibility")
        warnings = action_quality_warnings(
            action=request.action,
            text=text,
            actor=request.player.name,
            endgame=len(active_players) <= 4,
            prior_texts=[entry.message for entry in request.round_state.debate],
            personality=request.player.personality,
            eligibility=eligibility if isinstance(eligibility, dict) else None,
            role=request.player.role,
        )
        return [warning for warning in warnings if warning in HARD_ACTION_QUALITY_CODES]

    def _quality_feedback(self, warnings: list[str]) -> str:
        guidance = {
            "appeals_to_missing_sheriff_voters": "本轮没有警下投票者，不要向警下拉票。",
            "promises_ineligible_sheriff_vote": "你没有警长投票资格，不要承诺自己的警长票。",
            "sheriff_speech_investigation_plan_without_seer_claim": (
                "只有预言家或明确公开跳预言家的玩家才能给出查验式警徽流；"
                "否则请改为说明发言方向、归票和警徽移交原则，不要承诺先验、再验或今晚验人。"
            ),
            "assumes_future_round_in_endgame": "不能假定一定存在明天或下一轮。",
            "ignores_terminal_risk": "说明本轮错误放逐可能立即结束游戏。",
            "repeated_debate_phrase": "不要复述已有长句，加入一个新的公开事实、票型变化或具体反问。",
            "low_proposition_novelty": "给出一个此前没有出现过的明确判断，并说明可验证依据。",
            "group_agreement_without_evidence": "不要继续无依据附和；提出当前多数结论的反例或风险。",
            "catchphrase_dominates_speech": "减少个人口头禅，用具体事实和结论替代。",
        }
        return "；".join(guidance[warning] for warning in warnings if warning in guidance)

    def _speech_stage_context(
        self,
        action: str,
        round_state: RoundState,
        player: Player,
    ) -> tuple[list[str], list[str]]:
        active_players = (
            player.gamestate.current_players if player.gamestate else round_state.players
        )
        if action == ACTION_SHERIFF_SPEECH:
            return (
                [
                    str(entry.get("message") or "")
                    for entry in round_state.sheriff_speeches
                    if isinstance(entry, dict) and entry.get("message")
                ],
                round_state.sheriff_speech_order
                or round_state.sheriff_candidates
                or active_players,
            )
        if action == ACTION_SHERIFF_PK_SPEECH:
            return (
                [
                    str(entry.get("message") or "")
                    for entry in round_state.sheriff_pk_speeches
                    if isinstance(entry, dict) and entry.get("message")
                ],
                round_state.sheriff_pk_candidates or active_players,
            )
        return (
            [entry.message for entry in round_state.debate],
            round_state.speech_order or active_players,
        )

    def _speech_quality_report(
        self,
        request: PlayerActionRequest,
        lm_log: LmLog,
    ) -> SpeechQualityReportV1 | None:
        result = lm_log.result or {}
        text = result.get(request.result_key)
        if not isinstance(text, str) or not text.strip():
            return None
        prior_texts = request.world_state.get("speech_prior_texts")
        return evaluate_speech_quality(
            text=text,
            mission=speech_mission_from_dict(request.world_state.get("speech_mission")),
            prior_texts=(
                [str(item) for item in prior_texts] if isinstance(prior_texts, list) else []
            ),
            personality=request.player.personality,
        )

    def _attach_speech_quality_metadata(
        self,
        *,
        request: PlayerActionRequest,
        lm_log: LmLog,
        report: SpeechQualityReportV1 | None,
        attempt_count: int,
        retry_exhausted: bool,
        initial_codes: list[str],
    ) -> None:
        if request.action not in BUFFERED_QUALITY_ACTIONS:
            return
        mission = request.world_state.get("speech_mission")
        lm_log.speech_mission = copy.deepcopy(mission) if isinstance(mission, dict) else None
        lm_log.speech_quality_report = report.to_dict() if report else None
        lm_log.speech_quality_attempt_count = attempt_count
        lm_log.speech_quality_retry_exhausted = retry_exhausted
        lm_log.speech_quality_initial_codes = initial_codes.copy()

    def _timeout_fallback_result(
        self,
        request: PlayerActionRequest,
        *,
        started_at: float,
        budget_ms: int | None,
        timeout_source: Literal["action", "batch"] = "action",
    ) -> PlayerActionResult:
        result: dict[str, object]
        if request.action in BUFFERED_QUALITY_ACTIONS:
            value: object | None = REQUIRED_PUBLIC_SPEECH_FALLBACK
            result = {request.result_key: value}
            reason = "timeout_neutral_public_speech"
        else:
            optional_fallback = self._optional_fallback_choice(request)
            if optional_fallback is not None:
                value = optional_fallback
                result = {request.result_key: self._public_action_value(value)}
                reason = "timeout_optional_abstain"
            elif request.options:
                value = self._deterministic_timeout_choice(request)
                result = {request.result_key: self._public_action_value(value)}
                if request.action == ACTION_WEREWOLF_DISCUSS:
                    result["message"] = ""
                reason = "timeout_deterministic_legal_choice"
            else:
                value = ""
                result = {request.result_key: value}
                reason = "timeout_empty_private_text"
        if timeout_source == "batch":
            reason = reason.replace("timeout_", "batch_deadline_", 1)
        return PlayerActionResult(
            request=request,
            value=value,
            lm_log=LmLog(
                prompt="",
                raw_response="",
                result=result,
            ),
            execution_status="fallback",
            duration_ms=max(
                0,
                round((self.monotonic() - started_at) * 1000),
            ),
            budget_ms=budget_ms,
            fallback_reason=reason,
        )

    def _deterministic_timeout_choice(
        self,
        request: PlayerActionRequest,
    ) -> str:
        material = ":".join(
            [
                str(self.fallback_seed),
                str(request.round_state.number),
                request.phase,
                request.player.name,
                request.action,
            ]
        )
        return min(
            request.options,
            key=lambda option: hashlib.sha256(f"{material}:{option}".encode()).hexdigest(),
        )

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
        if request.action in BUFFERED_QUALITY_ACTIONS and lm_log.speech_quality_report is None:
            self._attach_speech_quality_metadata(
                request=request,
                lm_log=lm_log,
                report=self._speech_quality_report(request, lm_log),
                attempt_count=1,
                retry_exhausted=False,
                initial_codes=[],
            )
        action_log = ActionLog(
            actor=player.name,
            action=request.action,
            options=request.options,
            choice=str(value) if value is not None else None,
            lm_log=lm_log,
            raw_choice=lm_log.raw_choice,
            choice_normalization_kind=lm_log.choice_normalization_kind,
            speech_mission=copy.deepcopy(lm_log.speech_mission),
            speech_quality_report=copy.deepcopy(lm_log.speech_quality_report),
            speech_quality_attempt_count=lm_log.speech_quality_attempt_count,
            speech_quality_retry_exhausted=lm_log.speech_quality_retry_exhausted,
            speech_quality_initial_codes=lm_log.speech_quality_initial_codes.copy(),
            execution_status=result.execution_status,
            duration_ms=result.duration_ms,
            budget_ms=result.budget_ms,
            first_token_ms=(lm_log.first_token_ms if self.action_budgets_enabled else None),
            fact_prompt_coverage=copy.deepcopy(request.fact_prompt_coverage),
        )
        if result.fallback_reason is not None:
            action_log.fallback_reason = result.fallback_reason
            action_log.fallback_choice = value
        if lm_log.speech_quality_report is not None:
            record_speech_quality(
                phase=request.phase,
                report=lm_log.speech_quality_report,
                attempt_count=lm_log.speech_quality_attempt_count,
                retry_exhausted=lm_log.speech_quality_retry_exhausted,
            )
        if request.action == ACTION_WEREWOLF_SELF_EXPLOSION:
            (
                action_log.decision_schema,
                action_log.decision_audit,
            ) = _self_explosion_decision_audit(lm_log.result)
        invalid_error = self._invalid_player_action_error(result)
        if invalid_error is not None:
            fallback_choice = self._optional_fallback_choice(request)
            fallback_reason = "optional_action_invalid"
            if request.action in BUFFERED_QUALITY_ACTIONS:
                fallback_choice = REQUIRED_PUBLIC_SPEECH_FALLBACK
                fallback_reason = "required_public_speech_invalid"
            if fallback_choice is None:
                raise invalid_error
            invalid_value = self._invalid_value_from_result(result)
            value = fallback_choice
            fallback_result = dict(lm_log.result or {})
            fallback_result[request.result_key] = fallback_choice
            lm_log.result = fallback_result
            action_log.choice = str(fallback_choice)
            action_log.invalid_value = invalid_value
            action_log.fallback_choice = fallback_choice
            action_log.fallback_reason = fallback_reason
            action_log.execution_status = "fallback"
            action_log.attempt_count = max(1, len(lm_log.invalid_attempts))
            if request.event_visibility == "public":
                self._publish_invalid_action_fallback_warning(
                    request=request,
                    invalid_value=invalid_value,
                    fallback_choice=fallback_choice,
                    warning=(
                        "required_speech_fallback"
                        if request.action in BUFFERED_QUALITY_ACTIONS
                        else "off_option_fallback"
                    ),
                )
        elif checkpoint and self._is_checkpointable_player_action_result(result):
            self._checkpoint_player_action_success(result)
        if self.action_budgets_enabled:
            record_action_execution(
                action_kind=self.action_execution_budget.for_action(request.action).kind,
                model=player.model,
                result=action_log.execution_status,
                duration_ms=action_log.duration_ms,
                first_token_ms=action_log.first_token_ms,
                fallback_reason=action_log.fallback_reason,
            )
        if request.event_visibility == "public":
            record_model_progress_event("model_response_received")
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
                "request_id": lm_log.request_id,
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
        self._require_non_terminal_player_action()
        if len(requests) == 1:
            return [self._player_action_single(requests[0])]

        for request in requests:
            self._publish_player_action_requested(request)

        batch_started_at = self.monotonic()
        results: list[PlayerActionResult | None] = [None] * len(requests)
        exceptions: dict[int, Exception] = {}
        condition = threading.Condition()
        next_index = {"value": 0}
        gates = [_PublishGateSink(self.event_sink) for _ in requests]
        executor = ThreadPoolExecutor(max_workers=len(requests))
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
                gates[index],
            ): index
            for index, request in enumerate(requests)
        }
        batch_timeout = self._batch_deadline_seconds(requests)
        done, pending = wait(futures, timeout=batch_timeout)
        for future in done:
            index = futures[future]
            try:
                results[index] = future.result()
            except Exception as exc:
                exceptions[index] = exc
        for future in pending:
            index = futures[future]
            gates[index].close()
            future.cancel()
            request = requests[index]
            budget_spec = self.action_execution_budget.for_action(request.action)
            results[index] = self._timeout_fallback_result(
                request,
                started_at=batch_started_at,
                budget_ms=round(budget_spec.total_budget_seconds * 1000),
                timeout_source="batch",
            )
        if self.action_budgets_enabled:
            record_action_batch(
                action_kind=self.action_execution_budget.for_action(requests[0].action).kind,
                result=("deadline" if pending else "failed" if exceptions else "completed"),
                duration_ms=max(
                    0,
                    round((self.monotonic() - batch_started_at) * 1000),
                ),
            )
        executor.shutdown(wait=not pending, cancel_futures=bool(pending))

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

    def _batch_deadline_seconds(
        self,
        requests: list[PlayerActionRequest],
    ) -> float | None:
        if not self.action_budgets_enabled:
            return None
        deadlines = [
            deadline
            for request in requests
            if (
                deadline := self.action_execution_budget.for_action(
                    request.action
                ).batch_deadline_seconds
            )
            is not None
        ]
        return min(deadlines) if deadlines else None

    def _player_action_single(
        self,
        request: PlayerActionRequest,
    ) -> tuple[object | None, ActionLog]:
        self._require_non_terminal_player_action()
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
            if result is not None and self._is_checkpointable_player_action_result(result):
                self._checkpoint_player_action_success(result)

    def _is_checkpointable_player_action_result(
        self,
        result: PlayerActionResult,
    ) -> bool:
        return (
            result.execution_status == "completed"
            and result.fallback_reason is None
            and self._invalid_player_action_error(result) is None
        )

    def _publish_player_action_requested(self, request: PlayerActionRequest) -> None:
        if request.event_visibility == "private":
            return
        self._publish(
            "action_requested",
            round_number=request.round_state.number,
            phase=request.phase,
            actor=request.player.name,
            action=request.action,
            payload={"options": request.public_options.copy(), "result_key": request.result_key},
        )

    def _require_non_terminal_player_action(self) -> None:
        if self.state.winner:
            raise RuntimeError("Cannot request player action after game is terminal")

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
        if request.action in BUFFERED_QUALITY_ACTIONS and (
            not isinstance(result.value, str) or not result.value.strip()
        ):
            return ValueError(
                f"{request.player.name} did not return a valid {request.action} message."
            )
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

    def _publish_invalid_action_fallback_warning(
        self,
        *,
        request: PlayerActionRequest,
        invalid_value: object | None,
        fallback_choice: object,
        warning: str,
    ) -> None:
        self._publish(
            "action_quality_warning",
            round_number=request.round_state.number,
            phase=request.phase,
            actor=request.player.name,
            action=request.action,
            payload={
                "warnings": [warning],
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
        params: dict[str, object] = {}
        if target:
            params["target"] = target
        static_asset_id = seat_asset_id(cue, target) if cue == "witch_death" and target else cue
        self._publish_judge_cue(
            round_state,
            "night",
            cue_spec(cue, visible_text, static_asset_id=static_asset_id, params=params),
        )

    def _publish_judge_cue(
        self,
        round_state: RoundState,
        phase: str,
        cue: JudgeCueSpec,
    ) -> None:
        self._publish(
            "judge_cue",
            round_number=round_state.number,
            phase=phase,
            actor=None,
            action=cue.cue_id,
            payload=cue.to_payload(),
        )

    def _publish_judge_cues(
        self,
        round_state: RoundState,
        phase: str,
        cues: list[JudgeCueSpec],
    ) -> None:
        for cue in cues:
            self._publish_judge_cue(round_state, phase, cue)

    def _publish_state_updated(
        self,
        *,
        round_state: RoundState,
        phase: str,
        actor: str | None = None,
        action: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        public_payload = dict(payload or {})
        if round_state.public_outcome_events:
            public_payload["public_outcome_events"] = [
                event.to_dict() for event in round_state.public_outcome_events
            ]
            public_payload["public_outcome_next_sequence"] = (
                round_state.public_outcome_next_sequence
            )
        self._publish(
            "state_updated",
            round_number=round_state.number,
            phase=phase,
            actor=actor,
            action=action,
            payload=public_payload,
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
        player = self.state.player_by_name().get(actor)
        active_players = (
            player.gamestate.current_players
            if player is not None and player.gamestate
            else round_state.players
        )
        eligibility = (
            self._public_action_eligibility(player, active_players, round_state).to_dict()
            if player is not None
            else None
        )
        warnings = action_quality_warnings(
            action=action,
            text=text,
            actor=actor,
            endgame=len(active_players) <= 4,
            prior_texts=prior_texts,
            personality=personality,
            eligibility=eligibility,
            role=player.role if player is not None else "",
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

    def _player_action_event_visibility(
        self,
        phase: str,
        action: str,
    ) -> EventVisibility:
        if action == "summarize" or self._is_secret_werewolf_action(phase, action):
            return "private"
        return "public"

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
            "public_self_history": self._public_self_history(player.name),
            "stage_interruptions": self._stage_interruption_lines(round_state),
            "endgame_context": self._endgame_context(active_players),
            "remaining_players": "、".join(active_players),
            "debate": debate,
            "debate_guidance": self._debate_guidance(player, active_players, round_state),
            "personality": player.personality,
            "rule_text": render_rule_text(self.rule_set),
            "rule_set_snapshot": copy.deepcopy(self.state.rule_set),
            "werewolf_context": self._werewolf_context(player, active_players),
            "sheriff_election": self._sheriff_election_context(round_state),
            "public_action_eligibility": self._public_action_eligibility(
                player,
                active_players,
                round_state,
            ).to_dict(),
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

    def _append_public_outcome(
        self,
        *,
        round_state: RoundState,
        kind: PublicOutcomeKind,
        outcome: str,
        phase: str,
        actor_player: str | None = None,
        target_player: str | None = None,
        caused_by_event: PublicOutcomeEventV1 | None = None,
    ) -> PublicOutcomeEventV1:
        return append_public_outcome(
            round_state=round_state,
            session_id=self.state.session_id,
            kind=kind,
            actor_player_id=(self._public_player_reference(actor_player) if actor_player else None),
            target_player_id=(
                self._public_player_reference(target_player) if target_player else None
            ),
            outcome=outcome,
            occurred_phase=phase,
            caused_by_event_id=(caused_by_event.event_id if caused_by_event else None),
        )

    def _latest_player_outcome(
        self,
        round_state: RoundState,
        player: str,
    ) -> PublicOutcomeEventV1 | None:
        return latest_player_outcome_event(
            round_state.public_outcome_events,
            self._public_player_reference(player),
        )

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

    def _add_public_fact(
        self,
        round_number: int,
        category: str,
        text: str,
        *,
        stage: str | None = None,
        actor: str | None = None,
        retention: FactRetention | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        ordinal = len(self.state.public_facts)
        fact_stage = stage or category
        fact_actor = actor or "system"
        opportunity_id = (
            f"op:r{round_number}:{fact_stage}:{fact_actor}:"
            f"{len(self.state.public_fact_opportunities)}"
        )
        opportunity = PublicFactOpportunityV1(
            opportunity_id=opportunity_id,
            round_number=round_number,
            stage=fact_stage,
            category=category,
            retention=retention
            or (
                "important"
                if category in {"claim", "sheriff", "death", "vote", "reveal", "interruption"}
                else "recent"
            ),
            status="expected",
        ).to_dict()
        self.state.public_fact_opportunities.append(opportunity)
        fact_id = f"r{round_number}:{fact_stage}:{fact_actor}:{ordinal}"
        self.state.public_facts.append(
            PublicFact(
                round_number=round_number,
                category=category,
                text=text,
                fact_id=fact_id,
                stage=stage,
                actor=actor,
                retention=retention,
                source_opportunity_id=opportunity_id,
                details=details or {},
            ).to_dict()
        )
        opportunity["status"] = "recorded"
        opportunity["fact_id"] = fact_id
        self.state.public_fact_propositions.extend(
            self._public_fact_propositions(
                round_number=round_number,
                category=category,
                stage=fact_stage,
                details=details or {},
            )
        )

    def _public_fact_propositions(
        self,
        *,
        round_number: int,
        category: str,
        stage: str,
        details: dict[str, object],
    ) -> list[dict[str, object]]:
        propositions: list[dict[str, object]] = []
        if category == "death":
            raw_players = details.get("players")
            players = raw_players if isinstance(raw_players, list) else [details.get("target")]
            for player in players:
                if isinstance(player, str) and player:
                    propositions.append(
                        {
                            "subject": player,
                            "predicate": "alive",
                            "object": "",
                            "scope": "game",
                            "polarity": False,
                            "round_number": round_number,
                            "stage": stage,
                        }
                    )
        if category == "reveal" and isinstance(details.get("player"), str):
            propositions.append(
                {
                    "subject": details["player"],
                    "predicate": "role_revealed",
                    "object": "werewolf" if stage == "werewolf_self_explosion" else "public",
                    "scope": "game",
                    "polarity": True,
                    "round_number": round_number,
                    "stage": stage,
                }
            )
        return propositions

    def _public_fact_lines(
        self,
        *,
        sheriff_speech_context_round: int | None = None,
    ) -> list[str]:
        facts = [public_fact_from_dict(item) for item in self.state.public_facts]
        if sheriff_speech_context_round is not None:
            compacted_facts: list[PublicFact] = []
            for fact in facts:
                if fact.stage != "sheriff_speech":
                    compacted_facts.append(fact)
                    continue
                if fact.round_number == sheriff_speech_context_round:
                    continue
                compacted_facts.append(
                    replace(fact, text=_compact_sheriff_speech_context(fact.text))
                )
            facts = compacted_facts
        return compressed_public_facts(facts)

    def _public_self_history(self, player_name: str) -> list[str]:
        public_speech_stages = {"sheriff_speech", "sheriff_pk_speech", "debate"}
        facts = [
            public_fact_from_dict(item)
            for item in self.state.public_facts
            if isinstance(item, dict)
        ]
        own_public_speech = [
            fact
            for fact in facts
            if fact.actor == player_name
            and (fact.stage in public_speech_stages or fact.category in {"claim", "speech"})
        ]
        return compressed_public_facts(own_public_speech, max_lines=12)

    def _stage_interruption_lines(self, round_state: RoundState) -> list[str]:
        rounds = list(self.state.rounds)
        if all(existing is not round_state for existing in rounds):
            rounds.append(round_state)
        return [
            self._stage_interruption_text(existing.number, existing.interruption)
            for existing in rounds
            if existing.interruption is not None
        ]

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
            lines.append("本轮放逐可能直接触发任一阵营胜利，不能假定一定存在下一夜或下一轮。")
            lines.append("如果讨论明天，必须同时说明本轮错误放逐可能立即结束游戏。")
        return lines

    def _sheriff_election_context(
        self,
        round_state: RoundState,
        *,
        compact_prior_speeches: bool = False,
    ) -> list[str]:
        lines: list[str] = []
        if round_state.sheriff_candidates:
            lines.append(f"上警名单：{'、'.join(round_state.sheriff_candidates)}")
            voters = "、".join(round_state.sheriff_voters) or "无"
            lines.append(f"警下名单：{voters}")
        if round_state.sheriff_speeches:
            if compact_prior_speeches:
                speech_lines = [
                    (
                        f"{entry.get('speaker', '')}（前置位观点摘要，勿复用措辞或格式）："
                        f"{_compact_sheriff_speech_context(str(entry.get('message', '')))}"
                    )
                    for entry in round_state.sheriff_speeches
                    if entry.get("speaker") and entry.get("message")
                ]
            else:
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

    def _public_action_eligibility(
        self,
        player: Player,
        active_players: list[str],
        round_state: RoundState,
    ) -> PublicActionEligibility:
        candidates = round_state.sheriff_candidates.copy()
        voters = round_state.sheriff_voters.copy()
        final_candidates = round_state.sheriff_final_candidates.copy()
        actor_was_candidate = player.name in candidates
        actor_withdrew = player.name in round_state.sheriff_withdrawn
        election_active = self._should_run_sheriff_election(round_state)
        if not self.rule_set.sheriff_enabled:
            reason = "sheriff_disabled"
        elif round_state.sheriff_election_resolution is not None and not election_active:
            reason = "election_resolved"
        elif player.name in voters:
            reason = "eligible_original_voter"
        elif actor_withdrew:
            reason = "withdrew_candidate_not_original_voter"
        elif actor_was_candidate:
            reason = "candidate_not_eligible"
        elif candidates and not voters:
            reason = "no_off_sheriff_voters"
        else:
            reason = "election_resolved"
        return PublicActionEligibility(
            sheriff_election_active=election_active,
            original_candidates=candidates,
            original_voters=voters,
            final_candidates=final_candidates,
            actor_was_candidate=actor_was_candidate,
            actor_withdrew=actor_withdrew,
            actor_can_sheriff_vote=election_active and player.name in voters,
            sheriff_vote_reason=reason,  # type: ignore[arg-type]
            actor_can_exile_vote=player.can_vote and player.name in active_players,
        )

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

    def _refresh_winner(self, active_players: list[str]) -> bool:
        if self.state.winner:
            return True
        winner = self._get_winner(active_players)
        if not winner:
            return False
        self.state.winner = winner
        return True

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


def _self_explosion_decision_audit(
    result: dict[str, object] | None,
) -> tuple[str, dict[str, str] | None]:
    if not isinstance(result, dict):
        return "legacy", None
    benefit_type = result.get("benefit_type")
    expected_gain = result.get("expected_gain")
    primary_risk = result.get("primary_risk")
    if (
        isinstance(benefit_type, str)
        and benefit_type in SELF_EXPLOSION_BENEFIT_TYPES
        and isinstance(expected_gain, str)
        and bool(expected_gain.strip())
        and isinstance(primary_risk, str)
        and bool(primary_risk.strip())
    ):
        return (
            "v1",
            {
                "benefit_type": benefit_type,
                "expected_gain": expected_gain.strip(),
                "primary_risk": primary_risk.strip(),
            },
        )
    return "legacy", None
