from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.live import VoiceMaterializationJobRecord
from app.werewolf import live as live_module
from app.werewolf.engine import GameEngine, initialize_game_state
from app.werewolf.live import EventSink, LiveRunRegistry
from app.werewolf.live_store import DatabaseLiveStore
from app.werewolf.lm import FakeProvider
from app.werewolf.replay_playback import (
    build_public_game_session,
    build_replay_playback,
)
from app.werewolf.rules import get_rule_set
from app.werewolf.voice import (
    VoiceSpeakerConfig,
    event_to_voice_materialization,
    voice_job_candidate,
)


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "run_2d12b755578b_terminal_regression.json"
)
MODEL_EVENT_TYPES = {
    "action_requested",
    "model_request_started",
    "model_thinking_tick",
    "model_thinking_delta",
    "model_response_delta",
    "model_response_received",
    "action_parsed",
}


@pytest.fixture
def live_db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with session_factory() as session:
        yield session
    engine.dispose()


def test_run_2d12b755578b_terminal_contract_across_engine_replay_voice_and_live(
    monkeypatch: pytest.MonkeyPatch,
    live_db_session: Session,
) -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    terminal = fixture["terminal"]
    rule_set = get_rule_set(fixture["rule_set_id"])
    state = initialize_game_state(
        session_id=fixture["source_session_id"],
        villager_model="fixture-model",
        werewolf_model="fixture-model",
        seed=fixture["seed"],
        rule_set=rule_set,
    )
    players_by_name = state.player_by_name()
    for player_fixture in terminal["players"].values():
        players_by_name[player_fixture["seat"]].role = player_fixture["role"]

    wolf = players_by_name[terminal["players"]["wolf_sheriff"]["seat"]]
    civilian = players_by_name[terminal["players"]["last_civilian"]["seat"]]
    hunter = players_by_name[terminal["players"]["surviving_hunter"]["seat"]]
    state.sheriff = wolf.name
    wolf.is_sheriff = True

    fixed_uuid = SimpleNamespace(hex=fixture["source_run_id"].removeprefix("run_") + "0" * 20)
    monkeypatch.setattr(
        live_module,
        "uuid",
        SimpleNamespace(uuid4=lambda: fixed_uuid),
    )
    registry = LiveRunRegistry(
        live_store=DatabaseLiveStore(live_db_session),
        worker_id="worker_run_2d12b755578b",
    )
    run = registry.create_run(
        session_id=fixture["source_session_id"],
        villager_model="fixture-model",
        werewolf_model="fixture-model",
        seed=fixture["seed"],
        max_rounds=8,
        rule_set_id=fixture["rule_set_id"],
    )
    assert run.run_id == fixture["source_run_id"]
    registry.mark_running(run.run_id)

    provider = FakeProvider(
        [{"reasoning": "终局后不应调用模型。", "say": "SENTINEL_POST_TERMINAL"}]
    )
    engine = GameEngine(
        state=state,
        provider=provider,
        max_rounds=8,
        rule_set=rule_set,
        event_sink=EventSink(
            registry,
            run.run_id,
            fence_token=run.fence_token,
        ),
        starting_active_players=list(terminal["active_before"]),
    )
    monkeypatch.setattr(engine, "_run_night_phase", lambda *_args: None)
    monkeypatch.setattr(engine, "_run_debate_phase", lambda *_args: False)
    monkeypatch.setattr(
        engine,
        "_run_voting",
        lambda *_args: (dict(terminal["votes"]), []),
    )

    logs = engine.run()
    assert engine.terminal_keep_from_event_id is not None
    completion = registry.mark_completed(
        run.run_id,
        winner=state.winner,
        terminal_keep_from_event_id=engine.terminal_keep_from_event_id,
    )

    assert state.winner == terminal["winner"]
    assert provider.calls == 0
    assert engine._current_active_players() == terminal["active_after"]
    assert hunter.name in engine._current_active_players()
    assert civilian.name not in engine._current_active_players()
    assert len(logs) == 1
    round_state = state.rounds[0]
    round_log = logs[0]
    assert round_state.exiled == terminal["exiled"]
    assert round_state.exile_last_words is None
    assert round_state.sheriff_badge_target is None
    assert round_log.sheriff_badge is None
    assert round_log.summaries == []
    assert round_state.private_summaries == {}

    live_events = registry.events_after(run.run_id)
    decisive_event = next(
        event
        for event in live_events
        if event.type == "state_updated" and event.action == "exile_resolved"
    )
    assert decisive_event.payload["exiled"] == terminal["exiled"]
    assert engine.terminal_keep_from_event_id == decisive_event.id
    assert completion.payload == {
        "winner": terminal["winner"],
        "terminal_keep_from_event_id": decisive_event.id,
    }
    terminal_window = [event for event in live_events if event.id >= decisive_event.id]
    forbidden_actions = set(fixture["forbidden_post_terminal_actions"])
    forbidden_phases = set(fixture["forbidden_post_terminal_phases"])
    assert not any(event.type in MODEL_EVENT_TYPES for event in terminal_window)
    assert not any(event.action in forbidden_actions for event in terminal_window)
    assert not any(event.phase in forbidden_phases for event in terminal_window)
    assert [event.type for event in terminal_window].count("game_completed") == 1

    raw_session = {
        "session_id": fixture["source_session_id"],
        "status": "complete",
        "state": state.to_dict(),
        "logs": [log.to_dict() for log in logs],
    }
    public_game = build_public_game_session(raw_session)
    playback = build_replay_playback(raw_session)
    public_round = public_game["state"]["rounds"][0]
    assert public_game["state"]["winner"] == terminal["winner"]
    assert public_round["exiled"] == terminal["exiled"]
    assert public_round["exile_last_words"] is None
    assert "private_summaries" not in public_round
    assert public_game["logs"] == []
    playback_actions = {event.get("action") for event in playback["events"]}
    playback_phases = {event.get("phase") for event in playback["events"]}
    assert playback_actions.isdisjoint(forbidden_actions)
    assert playback_phases.isdisjoint(forbidden_phases)
    assert sum(event["type"] == "game_completed" for event in playback["events"]) == 1

    jobs = (
        live_db_session.query(VoiceMaterializationJobRecord)
        .filter(VoiceMaterializationJobRecord.run_id == run.run_id)
        .order_by(VoiceMaterializationJobRecord.source_event_id.asc())
        .all()
    )
    events_by_id = {event.id: event for event in live_events}
    terminal_jobs = [
        job for job in jobs if job.source_event_id >= decisive_event.id
    ]
    assert not any(job.speaker_kind == "player" for job in terminal_jobs)
    assert not any(
        events_by_id[job.source_event_id].action in forbidden_actions
        for job in terminal_jobs
    )
    completion_jobs = [
        job
        for job in jobs
        if events_by_id[job.source_event_id].type == "game_completed"
    ]
    assert len(completion_jobs) == 1
    assert completion_jobs[0].speaker_kind == "judge"
    assert completion_jobs[0].audience == "player_public"
    assert voice_job_candidate(completion) == "judge"
    voice_config = VoiceSpeakerConfig(
        player_speaker="fixture-player",
        judge_speaker="fixture-judge",
    )
    terminal_voice = event_to_voice_materialization(
        completion,
        voice_config,
    )
    assert terminal_voice is not None
    assert terminal_voice.text == "游戏结束，狼人阵营获胜。"
    assert terminal_voice.static_asset_id == "game_over_wolves"
    terminal_materializations = [
        voice
        for job in terminal_jobs
        if (
            voice := event_to_voice_materialization(
                events_by_id[job.source_event_id],
                voice_config,
            )
        )
        is not None
    ]
    assert [
        voice.source_event_id
        for voice in terminal_materializations
        if voice.static_asset_id == "game_over_wolves"
    ] == [completion.id]
