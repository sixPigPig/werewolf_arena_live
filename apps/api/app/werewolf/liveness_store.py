from __future__ import annotations

import copy
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.game_session import (
    ActorMindSnapshotRecord,
    GameSessionRecord,
    SpeechTurnReceiptRecord,
    SpeechTurnSegmentRecord,
    VoicePlaybackObservationRecord,
)
from app.models.live import VoiceUtteranceRecord
from app.werewolf.actor_mind import ActorMindV1, EventCoordinateV1
from app.werewolf.live import LiveEvent


SERVER_PLAYBACK_STATUSES = frozenset({"acked", "connection_lost", "ack_timeout"})
CLIENT_PLAYBACK_STATUSES = frozenset({"completed", "interrupted", "skipped", "failed"})
SPEECH_STREAM_MODE = "segments_v2"


class LivenessIntegrityError(RuntimeError):
    """Raised when durable liveness records disagree with canonical events."""


class LivenessRuntimeStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def save_actor_mind(self, session_id: str, mind: ActorMindV1) -> None:
        self._require_session(session_id)
        key = (session_id, mind.actor)
        state = mind.to_dict()
        state_hash = mind.canonical_hash()
        coordinate = EventCoordinateV1.from_dict(mind.last_processed_source)
        record = self.db.get(ActorMindSnapshotRecord, key)
        if record is None:
            self.db.add(
                ActorMindSnapshotRecord(
                    session_id=session_id,
                    actor=mind.actor,
                    schema_version=1,
                    revision=mind.revision,
                    last_source_run_id=(coordinate.source_run_id if coordinate else None),
                    last_source_event_id=(coordinate.source_event_id if coordinate else None),
                    state=state,
                    state_hash=state_hash,
                )
            )
            return
        if record.revision > mind.revision:
            raise LivenessIntegrityError("actor mind revision moved backwards")
        if record.revision == mind.revision:
            if record.state_hash != state_hash:
                raise LivenessIntegrityError("actor mind revision hash mismatch")
            return
        record.schema_version = 1
        record.revision = mind.revision
        record.last_source_run_id = coordinate.source_run_id if coordinate else None
        record.last_source_event_id = coordinate.source_event_id if coordinate else None
        record.state = state
        record.state_hash = state_hash

    def load_actor_minds(self, session_id: str) -> dict[str, ActorMindV1]:
        rows = self.db.scalars(
            select(ActorMindSnapshotRecord)
            .where(ActorMindSnapshotRecord.session_id == session_id)
            .order_by(ActorMindSnapshotRecord.actor.asc())
        )
        result: dict[str, ActorMindV1] = {}
        for row in rows:
            mind = ActorMindV1.from_dict(row.state, actor=row.actor)
            if mind.revision != row.revision or mind.canonical_hash() != row.state_hash:
                raise LivenessIntegrityError("stored actor mind is corrupt")
            result[row.actor] = mind
        return result

    def validate_checkpoint_actor_minds(
        self,
        session_id: str,
        checkpoint_minds: dict[str, Any],
    ) -> None:
        stored = self.load_actor_minds(session_id)
        if set(stored) != set(checkpoint_minds):
            raise LivenessIntegrityError("checkpoint actor mind set mismatch")
        for actor, mind in stored.items():
            try:
                checkpoint_mind = ActorMindV1.from_dict(
                    checkpoint_minds.get(actor),
                    actor=actor,
                )
            except ValueError as exc:
                raise LivenessIntegrityError("checkpoint actor mind is invalid") from exc
            if checkpoint_mind.canonical_hash() != mind.canonical_hash():
                raise LivenessIntegrityError("checkpoint actor mind mismatch")

    def validate_checkpoint_speech_receipts(
        self,
        session_id: str,
        checkpoint_receipts: dict[str, Any],
    ) -> None:
        durable = self.checkpoint_speech_receipts(session_id)
        if set(durable) != set(checkpoint_receipts):
            raise LivenessIntegrityError("checkpoint speech receipt set mismatch")
        self._validate_checkpoint_receipt_subset(
            checkpoint_receipts,
            durable,
        )

    def reconcile_checkpoint_speech_receipts(
        self,
        session_id: str,
        checkpoint_receipts: dict[str, Any],
    ) -> dict[str, Any]:
        """Hydrate durable segments committed immediately before a process crash."""

        durable = self.checkpoint_speech_receipts(session_id)
        if not set(checkpoint_receipts).issubset(durable):
            raise LivenessIntegrityError("checkpoint speech receipt set mismatch")
        self._validate_checkpoint_receipt_subset(
            checkpoint_receipts,
            durable,
        )
        return {
            action_id: {
                **(
                    copy.deepcopy(checkpoint_receipts[action_id])
                    if action_id in checkpoint_receipts
                    else {}
                ),
                **copy.deepcopy(receipt),
            }
            for action_id, receipt in durable.items()
        }

    def checkpoint_speech_receipts(self, session_id: str) -> dict[str, Any]:
        stored_receipts = list(
            self.db.scalars(
                select(SpeechTurnReceiptRecord)
                .where(SpeechTurnReceiptRecord.session_id == session_id)
                .order_by(SpeechTurnReceiptRecord.action_id.asc())
            )
        )
        result: dict[str, Any] = {}
        for stored in stored_receipts:
            segments = list(
                self.db.scalars(
                    select(SpeechTurnSegmentRecord)
                    .where(
                        SpeechTurnSegmentRecord.session_id == session_id,
                        SpeechTurnSegmentRecord.action_id == stored.action_id,
                    )
                    .order_by(SpeechTurnSegmentRecord.segment_index.asc())
                )
            )
            result[stored.action_id] = {
                "speech_id": segments[0].speech_id if segments else "",
                "speech_stream_mode": stored.speech_stream_mode,
                "status": stored.status,
                "segment_count": len(segments),
                "segments": [
                    {
                        "segment_id": stored_segment.segment_id,
                        "segment_index": index,
                        "text": stored_segment.text,
                        "presentation_id": stored_segment.presentation_id,
                        "source_event_id": stored_segment.source_event_id,
                        "source_run_id": stored_segment.source_run_id,
                    }
                    for index, stored_segment in enumerate(segments)
                ],
                "final_text": stored.final_text,
                "accepted_renderer_request_id": stored.accepted_renderer_request_id,
                **(
                    {"final_segment_index": stored.final_segment_index}
                    if stored.final_segment_index is not None
                    else {}
                ),
                **(
                    {
                        "sealed_source_run_id": stored.sealed_source_run_id,
                        "sealed_source_event_id": stored.sealed_source_event_id,
                    }
                    if stored.sealed_source_run_id is not None
                    and stored.sealed_source_event_id is not None
                    else {}
                ),
            }
        return result

    def _validate_checkpoint_receipt_subset(
        self,
        checkpoint_receipts: dict[str, Any],
        durable_receipts: dict[str, Any],
    ) -> None:
        core_keys = {
            "speech_id",
            "status",
            "segment_count",
            "segments",
            "final_text",
        }
        for action_id, checkpoint in checkpoint_receipts.items():
            durable = durable_receipts.get(action_id)
            if not isinstance(checkpoint, dict) or not isinstance(durable, dict):
                raise LivenessIntegrityError("checkpoint speech receipt is missing")
            checkpoint_core = {
                key: copy.deepcopy(checkpoint.get(key))
                for key in core_keys
            }
            checkpoint_core["speech_stream_mode"] = checkpoint.get("speech_stream_mode")
            durable_core = {
                key: copy.deepcopy(durable.get(key))
                for key in core_keys
            }
            durable_core["speech_stream_mode"] = durable.get("speech_stream_mode")
            status_advanced_at_seal = (
                checkpoint_core.get("status") == "partial"
                and durable_core.get("status") in {"complete", "interrupted"}
                and {
                    key: value
                    for key, value in checkpoint_core.items()
                    if key != "status"
                }
                == {
                    key: value
                    for key, value in durable_core.items()
                    if key != "status"
                }
            )
            if checkpoint_core != durable_core and not status_advanced_at_seal:
                raise LivenessIntegrityError("checkpoint speech receipt mismatch")
            for key in (
                "final_segment_index",
                "sealed_source_run_id",
                "sealed_source_event_id",
            ):
                if key in checkpoint and checkpoint.get(key) != durable.get(key):
                    raise LivenessIntegrityError("checkpoint speech seal mismatch")

    def stage_committed_segment(self, event: LiveEvent) -> None:
        payload = event.payload
        if (
            event.type != "model_response_delta"
            or payload.get("schema_version") != 2
            or payload.get("commit_state") != "accepted_segment"
        ):
            return
        self._require_session(event.session_id)
        action_id = _required_string(payload, "action_id")
        speech_id = _required_string(payload, "speech_id")
        segment_id = _required_string(payload, "segment_id")
        presentation_id = _required_string(payload, "presentation_id")
        text = _required_string(payload, "visible_text")
        request_id = _optional_string(payload.get("request_id"))
        speech_stream_mode = payload.get("speech_stream_mode")
        segment_index = payload.get("segment_index")
        segment_final = payload.get("segment_final")
        if speech_stream_mode != SPEECH_STREAM_MODE:
            raise LivenessIntegrityError("invalid committed speech stream mode")
        if (
            type(segment_index) is not int
            or segment_index < 0
            or type(segment_final) is not bool
        ):
            raise LivenessIntegrityError("invalid committed segment position")
        if segment_final:
            raise LivenessIntegrityError("segments v2 cannot self-finalize")
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        receipt_key = (event.session_id, action_id)
        receipt = self.db.get(SpeechTurnReceiptRecord, receipt_key)
        if receipt is None:
            receipt = SpeechTurnReceiptRecord(
                session_id=event.session_id,
                action_id=action_id,
                actor=event.actor or "",
                round=event.round,
                phase=event.phase,
                action=event.action,
                speech_stream_mode=speech_stream_mode,
                experience_revision=_required_string(payload, "experience_revision"),
                plan_id=_optional_string(payload.get("plan_id")),
                fence=(
                    copy.deepcopy(payload.get("fence"))
                    if isinstance(payload.get("fence"), dict)
                    else None
                ),
                scene_packet_hash=_optional_string(payload.get("scene_packet_hash")),
                planner_request_id=_optional_string(payload.get("planner_request_id")),
                renderer_attempts=(
                    copy.deepcopy(payload.get("renderer_attempts"))
                    if isinstance(payload.get("renderer_attempts"), list)
                    else []
                ),
                accepted_renderer_request_id=request_id,
                status="partial",
                final_text="",
                delivery_snapshot=(
                    copy.deepcopy(payload.get("voice_snapshot"))
                    if isinstance(payload.get("voice_snapshot"), dict)
                    else None
                ),
            )
            self.db.add(receipt)
            self.db.flush([receipt])
        elif (
            receipt.actor != (event.actor or "")
            or receipt.round != event.round
            or receipt.phase != event.phase
            or receipt.action != event.action
            or receipt.speech_stream_mode != speech_stream_mode
        ):
            raise LivenessIntegrityError("speech receipt identity mismatch")

        segment_key = (event.session_id, action_id, segment_index)
        existing = self.db.get(SpeechTurnSegmentRecord, segment_key)
        if existing is not None:
            if (
                existing.segment_id != segment_id
                or existing.speech_id != speech_id
                or existing.source_run_id != event.run_id
                or existing.source_event_id != event.id
                or existing.text_hash != text_hash
                or existing.presentation_id != presentation_id
            ):
                raise LivenessIntegrityError("committed segment receipt mismatch")
            return
        if receipt.sealed_source_event_id is not None:
            raise LivenessIntegrityError("sealed speech cannot accept another segment")

        prior_segments = list(
            self.db.scalars(
                select(SpeechTurnSegmentRecord)
                .where(
                    SpeechTurnSegmentRecord.session_id == event.session_id,
                    SpeechTurnSegmentRecord.action_id == action_id,
                )
                .order_by(SpeechTurnSegmentRecord.segment_index.asc())
            )
        )
        if segment_index != len(prior_segments):
            raise LivenessIntegrityError("committed segment sequence has a gap")
        if prior_segments and prior_segments[0].speech_id != speech_id:
            raise LivenessIntegrityError("speech id changed within one action")
        self.db.add(
            SpeechTurnSegmentRecord(
                session_id=event.session_id,
                action_id=action_id,
                segment_index=segment_index,
                segment_id=segment_id,
                speech_id=speech_id,
                request_id=request_id,
                source_run_id=event.run_id,
                source_event_id=event.id,
                text=text,
                text_hash=text_hash,
                presentation_id=presentation_id,
            )
        )
        receipt.final_text = "".join([*(item.text for item in prior_segments), text])
        receipt.status = "partial"
        receipt.accepted_renderer_request_id = request_id

    def finalize_speech_turn(self, event: LiveEvent) -> None:
        payload = event.payload
        if event.type != "action_parsed":
            return
        speech_stream_mode = payload.get("speech_stream_mode")
        if speech_stream_mode != SPEECH_STREAM_MODE:
            return
        action_id = _required_string(payload, "action_id")
        speech_id = _required_string(payload, "speech_id")
        segment_count = payload.get("segment_count")
        speech_status = payload.get("speech_status")
        if type(segment_count) is not int or segment_count < 1:
            raise LivenessIntegrityError("invalid finalized speech segment count")
        if speech_status not in {"spoken", "partial", "interrupted"}:
            raise LivenessIntegrityError("invalid finalized speech status")
        final_segment_index = payload.get("final_segment_index")
        if (
            type(final_segment_index) is not int
            or final_segment_index != segment_count - 1
        ):
            raise LivenessIntegrityError("invalid segments v2 final index")
        receipt = self.db.get(SpeechTurnReceiptRecord, (event.session_id, action_id))
        if receipt is None:
            raise LivenessIntegrityError("finalized speech has no durable receipt")
        if receipt.speech_stream_mode != speech_stream_mode:
            raise LivenessIntegrityError("finalized speech stream mode mismatch")
        already_sealed = receipt.sealed_source_event_id is not None
        if already_sealed and not (
            receipt.sealed_source_run_id == event.run_id
            and receipt.sealed_source_event_id == event.id
            and receipt.final_segment_index == final_segment_index
        ):
            raise LivenessIntegrityError("speech already sealed")
        segments = list(
            self.db.scalars(
                select(SpeechTurnSegmentRecord)
                .where(
                    SpeechTurnSegmentRecord.session_id == event.session_id,
                    SpeechTurnSegmentRecord.action_id == action_id,
                )
                .order_by(SpeechTurnSegmentRecord.segment_index.asc())
            )
        )
        if len(segments) != segment_count or any(
            segment.speech_id != speech_id for segment in segments
        ):
            raise LivenessIntegrityError("finalized speech receipt does not match segments")
        final_text = "".join(segment.text for segment in segments)
        visible_result = payload.get("visible_result")
        if isinstance(visible_result, dict):
            visible_speech = next(
                (
                    value
                    for key, value in visible_result.items()
                    if key in {"say", "message"} and isinstance(value, str)
                ),
                None,
            )
            if visible_speech is not None and visible_speech != final_text:
                raise LivenessIntegrityError("finalized public speech differs from receipt")
        finalized_status = (
            "complete"
            if speech_status == "spoken"
            else "partial"
            if speech_status == "partial"
            else "interrupted"
        )
        if already_sealed:
            if receipt.final_text != final_text or receipt.status != finalized_status:
                raise LivenessIntegrityError("replayed speech seal changed content")
            return
        receipt.final_text = final_text
        receipt.status = finalized_status
        receipt.final_segment_index = final_segment_index
        receipt.sealed_source_run_id = event.run_id
        receipt.sealed_source_event_id = event.id

    def record_playback_observation(
        self,
        *,
        playback_session_id: str,
        utterance_id: str,
        server_terminal_status: str,
        client_status: str | None = None,
        played_ms: int | None = None,
    ) -> None:
        if server_terminal_status not in SERVER_PLAYBACK_STATUSES:
            raise ValueError("invalid server playback status")
        if client_status is not None and client_status not in CLIENT_PLAYBACK_STATUSES:
            raise ValueError("invalid client playback status")
        if played_ms is not None and (type(played_ms) is not int or played_ms < 0):
            raise ValueError("invalid played duration")
        utterance = self.db.get(VoiceUtteranceRecord, utterance_id)
        if utterance is None:
            raise LivenessIntegrityError("playback observation has no utterance")
        key = (playback_session_id, utterance_id)
        observed_at = datetime.now(tz=UTC)
        playback_started_at = (
            observed_at - timedelta(milliseconds=played_ms)
            if client_status is not None and played_ms is not None
            else None
        )
        playback_finished_at = observed_at if client_status is not None else None
        ack_received_at = observed_at if client_status is not None else None
        record = self.db.get(VoicePlaybackObservationRecord, key)
        if record is None:
            self.db.add(
                VoicePlaybackObservationRecord(
                    playback_session_id=playback_session_id,
                    utterance_id=utterance_id,
                    session_id=utterance.session_id,
                    speech_id=utterance.speech_id,
                    server_terminal_status=server_terminal_status,
                    client_status=client_status,
                    played_ms=played_ms,
                    playback_started_at=playback_started_at,
                    playback_finished_at=playback_finished_at,
                    ack_received_at=ack_received_at,
                )
            )
            return
        record.server_terminal_status = server_terminal_status
        if client_status is not None:
            record.client_status = client_status
            record.played_ms = played_ms
            record.playback_started_at = playback_started_at
            record.playback_finished_at = playback_finished_at
            record.ack_received_at = ack_received_at
        record.updated_at = observed_at

    def _require_session(self, session_id: str) -> None:
        if self.db.get(GameSessionRecord, session_id) is None:
            raise LivenessIntegrityError("liveness record has no game session")


def _required_string(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value:
        raise LivenessIntegrityError(f"missing committed segment {name}")
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
