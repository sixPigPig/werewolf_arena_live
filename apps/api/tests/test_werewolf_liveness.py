from __future__ import annotations

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.game_session import (
    GameSessionRecord,
    SpeechTurnReceiptRecord,
    SpeechTurnSegmentRecord,
    VoicePlaybackObservationRecord,
)
from app.models.live import VoiceUtteranceRecord
from app.werewolf.actor_mind import (
    ActorMindReducer,
    ActorMindStimulusV1,
    ActorMindV1,
    EventCoordinateV1,
    public_affect_projection,
)
from app.werewolf.live import LiveEvent
from app.werewolf.liveness import (
    LivenessFeatureModesV1,
    LivenessSnapshotError,
    assign_liveness_experiment_v1,
    legacy_liveness_experience,
    liveness_experience_from_storage,
    liveness_experience_v1,
)
from app.werewolf.liveness_store import LivenessIntegrityError, LivenessRuntimeStore
from app.werewolf.liveness_telemetry import (
    record_liveness_speech,
    render_liveness_metrics,
    reset_liveness_metrics_for_tests,
)
from app.werewolf.scene_packet import build_actor_scene_packet, build_public_speech_scene
from app.werewolf.speech_gate import (
    IncrementalSpeechSegmenter,
    hard_speech_gate,
    split_complete_speech_segments,
    stable_segment_id,
    stable_segment_presentation_id,
    stable_speech_id,
)
from app.werewolf.turn_planning import (
    fallback_public_turn_plan,
    public_turn_plan_from_model,
    stable_plan_id,
)


def test_missing_liveness_snapshot_is_explicit_legacy_not_current_default() -> None:
    legacy = liveness_experience_from_storage(None)
    current = liveness_experience_v1()

    assert legacy == legacy_liveness_experience()
    assert legacy.experience_revision == "legacy-v0"
    assert legacy.feature_modes.style_gate == "legacy"
    assert current.experience_revision == "liveness-v1"
    assert current.feature_modes.style_gate == "async_observe"


def test_liveness_snapshot_round_trip_freezes_feature_modes() -> None:
    source = liveness_experience_v1(
        feature_modes=LivenessFeatureModesV1(
            actor_mind="read",
            sentence_stream="committed_segments",
            affect_delivery="on",
            tts_prefetch_depth=1,
            voice_preempt="deterministic",
        )
    )

    restored = liveness_experience_from_storage(source.to_dict())

    assert restored == source
    assert restored.to_dict() == source.to_dict()


def test_segments_v2_snapshot_round_trip_uses_versioned_speech_contract() -> None:
    source = liveness_experience_v1(
        feature_modes=LivenessFeatureModesV1(
            sentence_stream="committed_segments_v2",
        )
    )

    restored = liveness_experience_from_storage(source.to_dict())

    assert restored == source
    assert restored.speech_stream_version == "speech-v2"


@pytest.mark.parametrize(
    ("sentence_stream", "speech_stream_version"),
    [
        ("committed_segments_v2", "speech-v1"),
        ("committed_segments", "speech-v2"),
    ],
)
def test_segments_v2_snapshot_rejects_mismatched_contract_versions(
    sentence_stream: str,
    speech_stream_version: str,
) -> None:
    snapshot = liveness_experience_v1().to_dict()
    snapshot["feature_modes"]["sentence_stream"] = sentence_stream
    snapshot["speech_stream_version"] = speech_stream_version

    with pytest.raises(LivenessSnapshotError, match="must be paired"):
        liveness_experience_from_storage(snapshot)


def test_liveness_experiment_assignment_is_session_stable_and_stage_bounded() -> None:
    control = assign_liveness_experiment_v1(
        session_id="game_stable",
        experiment_id="lifelike-v1",
        treatment_percent=0,
    )
    treatment = assign_liveness_experiment_v1(
        session_id="game_stable",
        experiment_id="lifelike-v1",
        treatment_percent=100,
    )
    repeated = assign_liveness_experiment_v1(
        session_id="game_stable",
        experiment_id="lifelike-v1",
        treatment_percent=100,
    )

    assert control.variant == "control"
    assert control.snapshot.feature_modes.actor_mind == "shadow"
    assert control.snapshot.feature_modes.sentence_stream == "off"
    assert treatment == repeated
    assert treatment.variant == "treatment"
    assert treatment.snapshot.feature_modes.actor_mind == "read"
    assert treatment.snapshot.feature_modes.sentence_stream == "off"
    assert treatment.snapshot.feature_modes.affect_delivery == "on"
    assert treatment.snapshot.feature_modes.tts_prefetch_depth == 0
    assert treatment.snapshot.feature_modes.voice_preempt == "off"


def test_liveness_metrics_use_only_bounded_labels_and_stage_denominators() -> None:
    reset_liveness_metrics_for_tests()
    record_liveness_speech(
        action="debate",
        experience_revision="custom-unbounded-revision",
        result="partial",
        timing={
            "turn_ready_at": 100,
            "actor_brain_started_at": 110,
            "turn_plan_ready_at": 150,
            "renderer_started_at": 160,
            "first_model_delta_at": 200,
            "first_clause_committed_at": 230,
            "hard_gate_duration_ms": 4,
        },
        hard_rejected_count=1,
    )

    metrics = render_liveness_metrics()

    assert 'action="debate",mode="v1",result="partial"' in metrics
    assert 'stage="first_delta_to_clause",action="debate",mode="v1"' in metrics
    assert "custom-unbounded-revision" not in metrics
    assert 'werewolf_liveness_hard_rejection_total{action="debate",mode="v1"} 1' in metrics


def test_persisted_liveness_snapshot_fails_closed_on_unknown_mode() -> None:
    stored = liveness_experience_v1().to_dict()
    stored["feature_modes"]["sentence_stream"] = "raw_tokens"

    with pytest.raises(LivenessSnapshotError):
        liveness_experience_from_storage(stored)


def test_actor_mind_reducer_is_deterministic_bounded_and_idempotent() -> None:
    reducer = ActorMindReducer()
    source = EventCoordinateV1("run_a", 7)
    stimulus = ActorMindStimulusV1(
        source=source,
        kind="accusation",
        source_actor="2号玩家",
        urgency=88,
    )

    first = reducer.apply(ActorMindV1(actor="1号玩家"), stimulus)
    replayed = reducer.apply(first, stimulus)
    stale = reducer.apply(
        first,
        ActorMindStimulusV1(
            source=EventCoordinateV1("run_a", 6),
            kind="vote",
            source_actor="3号玩家",
        ),
    )
    independent = reducer.apply(ActorMindV1(actor="1号玩家"), stimulus)

    assert replayed is first
    assert stale is first
    assert first.to_dict() == independent.to_dict()
    assert first.canonical_hash() == independent.canonical_hash()
    assert first.revision == 1
    assert first.relationships["2号玩家"]["hostility"] == 12
    assert public_affect_projection(first) == {
        "mood": "calm",
        "intensity": "low",
        "pace": "natural",
    }


def test_public_turn_plan_declassifier_drops_unapproved_private_values() -> None:
    plan = public_turn_plan_from_model(
        {
            "primary_speech_act": "challenge",
            "social_goal": "shift_pressure",
            "response_targets": ["2号玩家", "狼人队友"],
            "must_reference_public_fact_ids": ["fact_public", "fact_private"],
            "stimulus_sources": [
                {"source_run_id": "run_a", "source_event_id": 3},
                {"source_run_id": "private_run", "source_event_id": 9},
            ],
        },
        action_id="act_1",
        fence={"phase_instance_id": "phase_1"},
        allowed_targets={"2号玩家"},
        allowed_sources={("run_a", 3)},
        allowed_fact_ids={"fact_public"},
    )

    assert plan.response_targets == ("2号玩家",)
    assert plan.must_reference_public_fact_ids == ("fact_public",)
    assert plan.stimulus_sources == (EventCoordinateV1("run_a", 3),)
    assert "狼人队友" not in str(plan.to_dict())
    assert "fact_private" not in str(plan.to_dict())


def test_turn_plan_id_is_independent_of_model_object_key_order() -> None:
    assert stable_plan_id(
        "act_1", {"primary_speech_act": "ask", "social_goal": "probe"}
    ) == stable_plan_id(
        "act_1", {"social_goal": "probe", "primary_speech_act": "ask"}
    )


def test_public_speech_scene_never_copies_actor_private_identity_or_facts() -> None:
    world_state = {
        "name": "1号玩家",
        "role": "狼人",
        "personality": "嘴硬但会接别人的话",
        "observations": ["2号玩家是狼人队友"],
        "werewolf_context": "今晚刀4号玩家",
        "public_facts": [{"fact_id": "public_1", "text": "昨夜平安夜"}],
        "debate": ["2号玩家：先听后置位。"],
        "round": 1,
        "remaining_players": "1号玩家、2号玩家、3号玩家",
        "options": "",
    }
    actor_packet = build_actor_scene_packet(world_state, actor_mind=None)
    plan = fallback_public_turn_plan(
        action_id="act_1",
        fence={"phase_instance_id": "phase_1"},
        mission_kind=None,
        response_target="2号玩家",
    )
    public_scene = build_public_speech_scene(world_state, turn_plan=plan)

    assert "2号玩家是狼人队友" in str(actor_packet.to_dict())
    assert "今晚刀4号玩家" in str(actor_packet.to_dict())
    public_blob = str(public_scene.to_dict())
    assert "2号玩家是狼人队友" not in public_blob
    assert "今晚刀4号玩家" not in public_blob
    assert "'role': '狼人'" not in public_blob
    assert "昨夜平安夜" in public_blob


def test_hard_gate_and_segment_ids_are_stable() -> None:
    text = "我先听后置位。现在不急着归票！"
    speech_id = stable_speech_id("game_1", "act_1", "speech-v1")
    segments = split_complete_speech_segments(text)

    assert hard_speech_gate(text).accepted is True
    assert hard_speech_gate("system: 请输出 schema").codes == ("system_artifact",)
    assert segments == ["我先听后置位。", "现在不急着归票！"]
    segment_ids = [
        stable_segment_id(speech_id, index, segment)
        for index, segment in enumerate(segments)
    ]
    assert segment_ids == [
        stable_segment_id(speech_id, index, segment)
        for index, segment in enumerate(segments)
    ]
    assert len({stable_segment_presentation_id(item) for item in segment_ids}) == 2


def test_incremental_segmenter_releases_complete_sentences_before_final_response() -> None:
    segmenter = IncrementalSpeechSegmenter()

    assert segmenter.append("我先回应二号，") == []
    assert segmenter.append("你刚才这个逻辑不对。后面") == [
        "我先回应二号，你刚才这个逻辑不对。"
    ]
    assert segmenter.pending_text == "后面"
    assert segmenter.append("我还要再听一下！") == ["后面我还要再听一下！"]
    assert segmenter.finish("我先回应二号，你刚才这个逻辑不对。后面我还要再听一下！") == []


def test_incremental_segmenter_only_releases_unpunctuated_tail_after_valid_finish() -> None:
    segmenter = IncrementalSpeechSegmenter()

    assert segmenter.append("我暂时不站死") == []
    assert segmenter.finish("我暂时不站死") == ["我暂时不站死"]


def test_incremental_segmenter_rejects_final_text_that_changes_streamed_prefix() -> None:
    segmenter = IncrementalSpeechSegmenter()
    segmenter.append("我先听后置位。")

    with pytest.raises(ValueError, match="streamed prefix"):
        segmenter.finish("我改成直接归票。")


def test_committed_segment_receipt_is_idempotent_and_reconstructs_final_text() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(GameSessionRecord(session_id="game_1", status="partial"))
        db.commit()
        store = LivenessRuntimeStore(db)
        speech_id = stable_speech_id("game_1", "act_1", "speech-v1")
        texts = ["我先听后置位。", "现在不急着归票！"]
        for index, text in enumerate(texts):
            segment_id = stable_segment_id(speech_id, index, text)
            event = LiveEvent(
                id=index + 10,
                type="model_response_delta",
                run_id="run_1",
                session_id="game_1",
                created_at="2026-07-19T00:00:00Z",
                round=1,
                phase="day",
                actor="1号玩家",
                action="debate",
                payload={
                    "schema_version": 2,
                    "commit_state": "accepted_segment",
                    "action_id": "act_1",
                    "request_id": "req_1",
                    "speech_id": speech_id,
                    "segment_id": segment_id,
                    "segment_index": index,
                    "segment_final": index == len(texts) - 1,
                    "presentation_id": stable_segment_presentation_id(segment_id),
                    "experience_revision": "liveness-v1",
                    "visible_text": text,
                },
            )
            store.stage_committed_segment(event)
            db.flush()
            store.stage_committed_segment(event)
            db.flush()

        receipt = db.get(SpeechTurnReceiptRecord, ("game_1", "act_1"))
        rows = list(
            db.scalars(
                select(SpeechTurnSegmentRecord).order_by(
                    SpeechTurnSegmentRecord.segment_index
                )
            )
        )
        assert receipt is not None
        assert receipt.status == "complete"
        assert receipt.final_text == "".join(texts)
        assert [row.text for row in rows] == texts
        checkpoint_receipt = {
            "speech_id": speech_id,
            "status": "complete",
            "segment_count": 2,
            "final_text": "".join(texts),
            "segments": [
                {
                    "segment_id": row.segment_id,
                    "segment_index": row.segment_index,
                    "text": row.text,
                    "presentation_id": row.presentation_id,
                    "source_event_id": row.source_event_id,
                    "source_run_id": row.source_run_id,
                }
                for row in rows
            ],
        }
        store.validate_checkpoint_speech_receipts(
            "game_1",
            {"act_1": checkpoint_receipt},
        )
        checkpoint_receipt["final_text"] = "被篡改"
        with pytest.raises(LivenessIntegrityError):
            store.validate_checkpoint_speech_receipts(
                "game_1",
                {"act_1": checkpoint_receipt},
            )


def test_playback_observation_keeps_server_and_client_terminal_states() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(GameSessionRecord(session_id="game_voice", status="partial"))
        db.add(
            VoiceUtteranceRecord(
                utterance_id="voice_1",
                run_id="run_1",
                session_id="game_voice",
                source_event_id=8,
                last_source_event_id=8,
                speech_id="sp_1",
                speaker_kind="player",
                speaker_name="1号玩家",
                speaker="speaker_1",
                text="先听后置位。",
                text_hash="hash",
                audio_format="pcm",
                sample_rate=24000,
                mime_type="audio/L16",
                status="complete",
            )
        )
        db.commit()

        store = LivenessRuntimeStore(db)
        store.record_playback_observation(
            playback_session_id="pbs_1",
            utterance_id="voice_1",
            server_terminal_status="acked",
            client_status="interrupted",
            played_ms=420,
        )
        db.commit()

        observation = db.get(VoicePlaybackObservationRecord, ("pbs_1", "voice_1"))
        assert observation is not None
        assert observation.session_id == "game_voice"
        assert observation.speech_id == "sp_1"
        assert observation.server_terminal_status == "acked"
        assert observation.client_status == "interrupted"
        assert observation.played_ms == 420
        assert observation.playback_started_at is not None
        assert observation.playback_finished_at is not None
        assert observation.ack_received_at is not None
        elapsed_ms = round(
            (
                observation.playback_finished_at
                - observation.playback_started_at
            ).total_seconds()
            * 1000
        )
        assert elapsed_ms == 420


def test_action_parsed_finalizes_and_cross_checks_speech_receipt() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(GameSessionRecord(session_id="game_finalize", status="partial"))
        db.commit()
        store = LivenessRuntimeStore(db)
        text = "我会回应刚才的问题。"
        speech_id = stable_speech_id("game_finalize", "act_finalize", "speech-v1")
        segment_id = stable_segment_id(speech_id, 0, text)
        store.stage_committed_segment(
            LiveEvent(
                id=3,
                type="model_response_delta",
                run_id="run_finalize",
                session_id="game_finalize",
                created_at="2026-07-19T00:00:00Z",
                round=1,
                phase="day",
                actor="1号玩家",
                action="debate",
                payload={
                    "schema_version": 2,
                    "commit_state": "accepted_segment",
                    "speech_stream_mode": "segments_v2",
                    "action_id": "act_finalize",
                    "request_id": "req_finalize",
                    "speech_id": speech_id,
                    "segment_id": segment_id,
                    "segment_index": 0,
                    "segment_final": False,
                    "presentation_id": stable_segment_presentation_id(segment_id),
                    "experience_revision": "liveness-v1",
                    "visible_text": text,
                },
            )
        )
        db.flush()
        store.finalize_speech_turn(
            LiveEvent(
                id=4,
                type="action_parsed",
                run_id="run_finalize",
                session_id="game_finalize",
                created_at="2026-07-19T00:00:01Z",
                round=1,
                phase="day",
                actor="1号玩家",
                action="debate",
                payload={
                    "action_id": "act_finalize",
                    "speech_id": speech_id,
                    "speech_stream_mode": "segments_v2",
                    "segment_count": 1,
                    "final_segment_index": 0,
                    "speech_status": "spoken",
                    "visible_result": {"say": text},
                },
            )
        )
        db.flush()

        receipt = db.get(SpeechTurnReceiptRecord, ("game_finalize", "act_finalize"))
        assert receipt is not None
        assert receipt.speech_stream_mode == "segments_v2"
        assert receipt.status == "complete"
        assert receipt.final_text == text
        assert receipt.final_segment_index == 0
        assert receipt.sealed_source_run_id == "run_finalize"
        assert receipt.sealed_source_event_id == 4
        checkpoint = store.checkpoint_speech_receipts("game_finalize")["act_finalize"]
        assert checkpoint["speech_stream_mode"] == "segments_v2"
        assert checkpoint["final_segment_index"] == 0
        assert checkpoint["sealed_source_run_id"] == "run_finalize"
        assert checkpoint["sealed_source_event_id"] == 4
        changed_checkpoint = dict(checkpoint)
        changed_checkpoint["sealed_source_event_id"] = 999
        with pytest.raises(LivenessIntegrityError, match="seal mismatch"):
            store.validate_checkpoint_speech_receipts(
                "game_finalize",
                {"act_finalize": changed_checkpoint},
            )
        preseal_checkpoint = dict(checkpoint)
        preseal_checkpoint["status"] = "partial"
        preseal_checkpoint.pop("final_segment_index")
        preseal_checkpoint.pop("sealed_source_run_id")
        preseal_checkpoint.pop("sealed_source_event_id")
        reconciled = store.reconcile_checkpoint_speech_receipts(
            "game_finalize",
            {"act_finalize": preseal_checkpoint},
        )["act_finalize"]
        assert reconciled["status"] == "complete"
        assert reconciled["final_segment_index"] == 0
        assert reconciled["sealed_source_event_id"] == 4

        store.finalize_speech_turn(
            LiveEvent(
                id=4,
                type="action_parsed",
                run_id="run_finalize",
                session_id="game_finalize",
                created_at="2026-07-19T00:00:01Z",
                round=1,
                phase="day",
                actor="1号玩家",
                action="debate",
                payload={
                    "action_id": "act_finalize",
                    "speech_id": speech_id,
                    "speech_stream_mode": "segments_v2",
                    "segment_count": 1,
                    "final_segment_index": 0,
                    "speech_status": "spoken",
                    "visible_result": {"say": text},
                },
            )
        )

        with pytest.raises(LivenessIntegrityError, match="already sealed"):
            store.finalize_speech_turn(
                LiveEvent(
                    id=6,
                    type="action_parsed",
                    run_id="run_finalize",
                    session_id="game_finalize",
                    created_at="2026-07-19T00:00:03Z",
                    round=1,
                    phase="day",
                    actor="1号玩家",
                    action="debate",
                    payload={
                        "action_id": "act_finalize",
                        "speech_id": speech_id,
                        "speech_stream_mode": "segments_v2",
                        "segment_count": 1,
                        "final_segment_index": 0,
                        "speech_status": "spoken",
                        "visible_result": {"say": text},
                    },
                )
            )

        with pytest.raises(LivenessIntegrityError, match="sealed"):
            store.stage_committed_segment(
                LiveEvent(
                    id=5,
                    type="model_response_delta",
                    run_id="run_finalize",
                    session_id="game_finalize",
                    created_at="2026-07-19T00:00:02Z",
                    round=1,
                    phase="day",
                    actor="1号玩家",
                    action="debate",
                    payload={
                        "schema_version": 2,
                        "commit_state": "accepted_segment",
                        "speech_stream_mode": "segments_v2",
                        "action_id": "act_finalize",
                        "request_id": "req_finalize",
                        "speech_id": speech_id,
                        "segment_id": "seg_after_seal",
                        "segment_index": 1,
                        "segment_final": False,
                        "presentation_id": "pres_after_seal",
                        "experience_revision": "liveness-v1",
                        "visible_text": "封口后不得追加。",
                    },
                )
            )
