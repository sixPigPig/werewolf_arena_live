from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from app.werewolf.public_facts import public_fact_dicts_from_value


PublicChannel = Literal["live_event", "voice", "subtitle", "replay", "public_state"]

PRIVATE_ACTIONS = frozenset(
    {
        "eliminate",
        "remove",
        "protect",
        "investigate",
        "witch_save",
        "witch_poison",
        "werewolf_discuss",
        "werewolf_kill_vote",
        "summarize",
    }
)
PUBLIC_SPEECH_ACTIONS = frozenset(
    {"debate", "sheriff_speech", "sheriff_pk_speech", "exile_pk_speech", "exile_last_words"}
)
PUBLIC_EVENT_TEXT_KEYS = frozenset(
    {
        "choice",
        "delta",
        "description",
        "final_target",
        "message",
        "result",
        "say",
        "speech",
        "summary",
        "target",
        "text",
        "visible_result",
        "visible_text",
        "winner",
    }
)


@dataclass(frozen=True)
class PrivateEvidenceV1:
    kind: str
    text: str
    round_number: int | None = None
    actor: str | None = None


@dataclass(frozen=True)
class PublicArtifactV1:
    channel: PublicChannel
    text: str
    round_number: int | None = None
    event_id: int | None = None
    utterance_id: str | None = None
    event_type: str | None = None
    action: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationSourceCoverageV1:
    state: str
    logs: str
    events: str
    voice: str
    subtitles: str
    max_event_id: int | None
    max_voice_source_event_id: int | None
    pending_voice_count: int
    failed_voice_count: int

    @property
    def data_status(self) -> str:
        if self.state == "missing" or self.logs == "missing":
            return "unavailable"
        if self.pending_voice_count or self.voice == "partial" or self.subtitles == "partial":
            return "partial"
        return "available"

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "logs": self.logs,
            "events": self.events,
            "voice": self.voice,
            "subtitles": self.subtitles,
            "max_event_id": self.max_event_id,
            "max_voice_source_event_id": self.max_voice_source_event_id,
            "pending_voice_count": self.pending_voice_count,
            "failed_voice_count": self.failed_voice_count,
        }


@dataclass(frozen=True)
class QualityEvaluationBundleV1:
    schema_version: int
    session_id: str
    run_id: str | None
    state: dict[str, Any]
    logs: list[dict[str, Any]]
    live_events: list[dict[str, Any]]
    voice_utterances: list[dict[str, Any]]
    private_evidence: tuple[PrivateEvidenceV1, ...]
    public_artifacts: tuple[PublicArtifactV1, ...]
    source_coverage: EvaluationSourceCoverageV1
    source_revision: str
    started_at: str | None = None
    completed_at: str | None = None


def build_quality_evaluation_bundle(
    *,
    state: dict[str, Any],
    logs: list[dict[str, Any]],
    live_events: list[dict[str, Any]] | None = None,
    voice_utterances: list[dict[str, Any]] | None = None,
    run_id: str | None = None,
    started_at: str | None = None,
    completed_at: str | None = None,
) -> QualityEvaluationBundleV1:
    events = sorted(
        [event for event in live_events or [] if isinstance(event, dict)],
        key=lambda item: _safe_int(item.get("id"), default=0),
    )
    voices = sorted(
        [voice for voice in voice_utterances or [] if isinstance(voice, dict)],
        key=lambda item: (
            _safe_int(item.get("source_event_id"), default=0),
            str(item.get("utterance_id") or ""),
        ),
    )
    normalized_logs = [item for item in logs if isinstance(item, dict)]
    private_evidence = tuple(_private_evidence(state, normalized_logs))
    public_artifacts = tuple(_public_artifacts(state, events, voices))
    coverage = _source_coverage(state, normalized_logs, events, voices)
    session_id = str(state.get("session_id") or "")
    effective_run_id = run_id or _first_text(events, "run_id") or None
    revision_payload = {
        "schema_version": 1,
        "session_id": session_id,
        "run_id": effective_run_id,
        "state": state,
        "logs": normalized_logs,
        "live_events": events,
        "voice_utterances": voices,
        "started_at": started_at,
        "completed_at": completed_at,
    }
    source_revision = hashlib.sha256(
        json.dumps(
            revision_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return QualityEvaluationBundleV1(
        schema_version=1,
        session_id=session_id,
        run_id=effective_run_id,
        state=state,
        logs=normalized_logs,
        live_events=events,
        voice_utterances=voices,
        private_evidence=private_evidence,
        public_artifacts=public_artifacts,
        source_coverage=coverage,
        source_revision=source_revision,
        started_at=started_at,
        completed_at=completed_at,
    )


def _private_evidence(
    state: dict[str, Any],
    logs: list[dict[str, Any]],
) -> list[PrivateEvidenceV1]:
    evidence: list[PrivateEvidenceV1] = []
    for round_state in _rounds(state):
        round_number = _optional_int(round_state.get("number"))
        summaries = round_state.get("private_summaries")
        if isinstance(summaries, dict):
            for actor, text in sorted(summaries.items(), key=lambda item: str(item[0])):
                if isinstance(text, str) and text.strip():
                    evidence.append(
                        PrivateEvidenceV1(
                            kind="private_summary",
                            text=text,
                            round_number=round_number,
                            actor=str(actor),
                        )
                    )
        for key, kind in (
            ("werewolf_discussion", "werewolf_discussion"),
            ("werewolf_vote_rounds", "werewolf_vote"),
        ):
            for text in _selected_strings(round_state.get(key)):
                evidence.append(
                    PrivateEvidenceV1(
                        kind=kind,
                        text=text,
                        round_number=round_number,
                    )
                )

    for round_log in logs:
        round_number = _optional_int(round_log.get("number"))
        for action_log in _action_logs(round_log):
            action = str(action_log.get("action") or "")
            if action not in PRIVATE_ACTIONS:
                continue
            actor = str(action_log.get("actor") or "") or None
            for text in _action_log_private_strings(action_log):
                evidence.append(
                    PrivateEvidenceV1(
                        kind=action or "private_action",
                        text=text,
                        round_number=round_number,
                        actor=actor,
                    )
                )
    return _deduplicate_evidence(evidence)


def _public_artifacts(
    state: dict[str, Any],
    events: list[dict[str, Any]],
    voices: list[dict[str, Any]],
) -> list[PublicArtifactV1]:
    artifacts: list[PublicArtifactV1] = []
    for event in events:
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        text = "\n".join(_public_payload_strings(payload))
        artifacts.append(
            PublicArtifactV1(
                channel="live_event",
                text=text,
                round_number=_optional_int(event.get("round")),
                event_id=_optional_int(event.get("id")),
                event_type=str(event.get("type") or "") or None,
                action=str(event.get("action") or "") or None,
                payload=payload,
            )
        )

    for voice in voices:
        if str(voice.get("status") or "complete") != "complete":
            continue
        utterance_id = str(voice.get("utterance_id") or "") or None
        source_event_id = _optional_int(voice.get("source_event_id"))
        text = str(voice.get("text") or voice.get("_text") or "")
        artifacts.append(
            PublicArtifactV1(
                channel="voice",
                text=text,
                event_id=source_event_id,
                utterance_id=utterance_id,
                action=str(voice.get("action") or "") or None,
            )
        )
        timings = voice.get("subtitle_timings")
        if isinstance(timings, list):
            for timing in timings:
                if not isinstance(timing, dict):
                    continue
                subtitle = timing.get("text")
                if not isinstance(subtitle, str) or not subtitle.strip():
                    continue
                artifacts.append(
                    PublicArtifactV1(
                        channel="subtitle",
                        text=subtitle,
                        event_id=source_event_id,
                        utterance_id=utterance_id,
                        action=str(voice.get("action") or "") or None,
                    )
                )

    for round_state in _rounds(state):
        round_number = _optional_int(round_state.get("number"))
        for field_name in (
            "debate",
            "sheriff_speeches",
            "sheriff_pk_speeches",
            "exile_pk_speeches",
            "summaries",
            "public_summary",
        ):
            text = "\n".join(_selected_strings(round_state.get(field_name)))
            if text:
                artifacts.append(
                    PublicArtifactV1(
                        channel="replay",
                        text=text,
                        round_number=round_number,
                        event_type=f"round.{field_name}",
                    )
                )
        for field_name in ("public_outcome_events",):
            value = round_state.get(field_name)
            text = "\n".join(_selected_strings(value))
            if text or value:
                artifacts.append(
                    PublicArtifactV1(
                        channel="public_state",
                        text=text,
                        round_number=round_number,
                        event_type=f"round.{field_name}",
                        payload={field_name: value},
                    )
                )

    public_facts = public_fact_dicts_from_value(state.get("public_facts"))
    if public_facts:
        for fact in public_facts:
            artifacts.append(
                PublicArtifactV1(
                    channel="public_state",
                    text=str(fact.get("text") or ""),
                    round_number=_optional_int(fact.get("round_number")),
                    event_type="public_fact",
                    payload=fact,
                )
            )
    return artifacts


def _source_coverage(
    state: dict[str, Any],
    logs: list[dict[str, Any]],
    events: list[dict[str, Any]],
    voices: list[dict[str, Any]],
) -> EvaluationSourceCoverageV1:
    complete_voices = [voice for voice in voices if voice.get("status", "complete") == "complete"]
    pending_voices = [
        voice
        for voice in voices
        if str(voice.get("status") or "") in {"pending", "processing", "synthesizing"}
    ]
    failed_voices = [voice for voice in voices if voice.get("status") == "failed"]
    subtitle_count = sum(
        len(voice.get("subtitle_timings") or [])
        for voice in complete_voices
        if isinstance(voice.get("subtitle_timings"), list)
    )
    return EvaluationSourceCoverageV1(
        state="complete" if state else "missing",
        logs="complete" if isinstance(logs, list) else "missing",
        events="complete" if events else "missing",
        voice=("partial" if pending_voices else "complete" if complete_voices else "missing"),
        subtitles=(
            "partial"
            if pending_voices
            else "complete"
            if subtitle_count
            else "missing"
        ),
        max_event_id=max((_safe_int(event.get("id"), 0) for event in events), default=None),
        max_voice_source_event_id=max(
            (_safe_int(voice.get("source_event_id"), 0) for voice in complete_voices),
            default=None,
        ),
        pending_voice_count=len(pending_voices),
        failed_voice_count=len(failed_voices),
    )


def _rounds(state: dict[str, Any]) -> list[dict[str, Any]]:
    rounds = state.get("rounds")
    if not isinstance(rounds, list):
        return []
    return [item for item in rounds if isinstance(item, dict)]


def _action_logs(value: object) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("action"), str) and isinstance(value.get("lm_log"), dict):
            found.append(value)
        else:
            for nested in value.values():
                found.extend(_action_logs(nested))
    elif isinstance(value, list):
        for nested in value:
            found.extend(_action_logs(nested))
    return found


def _action_log_private_strings(action_log: dict[str, Any]) -> list[str]:
    values: list[str] = []
    choice = action_log.get("choice")
    if isinstance(choice, str):
        values.append(choice)
    lm_log = action_log.get("lm_log")
    if isinstance(lm_log, dict):
        for field_name in ("result", "raw_responses"):
            values.extend(_selected_strings(lm_log.get(field_name)))
    return [text for text in values if text.strip()]


def _public_payload_strings(payload: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key, value in payload.items():
        if str(key) in PUBLIC_EVENT_TEXT_KEYS:
            values.extend(_selected_strings(value))
    return values


def _selected_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, dict):
        values: list[str] = []
        for nested in value.values():
            values.extend(_selected_strings(nested))
        return values
    if isinstance(value, list):
        values = []
        for nested in value:
            values.extend(_selected_strings(nested))
        return values
    return []


def _deduplicate_evidence(values: list[PrivateEvidenceV1]) -> list[PrivateEvidenceV1]:
    result: list[PrivateEvidenceV1] = []
    seen: set[tuple[str, str, int | None, str | None]] = set()
    for value in values:
        key = (value.kind, value.text, value.round_number, value.actor)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _first_text(values: list[dict[str, Any]], key: str) -> str:
    for value in values:
        text = value.get(key)
        if isinstance(text, str) and text:
            return text
    return ""


def _safe_int(value: object, default: int) -> int:
    return value if type(value) is int else default


def _optional_int(value: object) -> int | None:
    return value if type(value) is int else None
