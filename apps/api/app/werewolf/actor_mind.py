from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Mapping


@dataclass(frozen=True, order=True)
class EventCoordinateV1:
    source_run_id: str
    source_event_id: int

    def __post_init__(self) -> None:
        if not self.source_run_id or self.source_event_id < 1:
            raise ValueError("invalid event coordinate")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> "EventCoordinateV1 | None":
        if not isinstance(value, Mapping):
            return None
        run_id = value.get("source_run_id")
        event_id = value.get("source_event_id")
        if not isinstance(run_id, str) or not run_id or type(event_id) is not int or event_id < 1:
            return None
        return cls(source_run_id=run_id, source_event_id=event_id)


@dataclass(frozen=True)
class ActorMindStimulusV1:
    source: EventCoordinateV1
    kind: Literal[
        "direct_question",
        "accusation",
        "vote",
        "support",
        "stage_pressure",
        "own_commitment",
        "phase_decay",
    ]
    source_actor: str | None = None
    target: str | None = None
    commitment_kind: str | None = None
    urgency: int = 50


@dataclass
class ActorMindV1:
    actor: str
    schema_version: Literal[1] = 1
    revision: int = 0
    last_processed_source: dict[str, object] | None = None
    beliefs: dict[str, dict[str, object]] = field(default_factory=dict)
    relationships: dict[str, dict[str, object]] = field(default_factory=dict)
    affect: dict[str, object] = field(
        default_factory=lambda: {
            "valence": 0,
            "arousal": 20,
            "confidence": 50,
            "stress": 20,
            "last_trigger_source": None,
        }
    )
    commitments: list[dict[str, object]] = field(default_factory=list)
    open_threads: list[dict[str, object]] = field(default_factory=list)
    recent_behavior: dict[str, list[str]] = field(
        default_factory=lambda: {
            "speech_acts": [],
            "length_bands": [],
            "opening_fingerprints": [],
        }
    )

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(asdict(self))

    def canonical_hash(self) -> str:
        payload = json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @classmethod
    def from_dict(cls, value: object, *, actor: str) -> "ActorMindV1":
        if not isinstance(value, Mapping) or value.get("schema_version") != 1:
            return cls(actor=actor)
        stored_actor = value.get("actor")
        if stored_actor != actor:
            raise ValueError("actor mind belongs to another actor")
        mind = cls(actor=actor)
        revision = value.get("revision")
        mind.revision = revision if type(revision) is int and revision >= 0 else 0
        coordinate = EventCoordinateV1.from_dict(value.get("last_processed_source"))
        mind.last_processed_source = coordinate.to_dict() if coordinate else None
        mind.beliefs = _bounded_mapping(value.get("beliefs"), limit=32)
        mind.relationships = _bounded_mapping(value.get("relationships"), limit=32)
        mind.affect = _normalized_affect(value.get("affect"))
        mind.commitments = _bounded_dict_list(value.get("commitments"), limit=12)
        mind.open_threads = _bounded_dict_list(value.get("open_threads"), limit=8)
        recent = value.get("recent_behavior")
        if isinstance(recent, Mapping):
            mind.recent_behavior = {
                "speech_acts": _bounded_strings(recent.get("speech_acts"), 6),
                "length_bands": _bounded_strings(recent.get("length_bands"), 6),
                "opening_fingerprints": _bounded_strings(
                    recent.get("opening_fingerprints"), 4
                ),
            }
        return mind


class ActorMindReducer:
    def apply(self, mind: ActorMindV1, stimulus: ActorMindStimulusV1) -> ActorMindV1:
        previous = EventCoordinateV1.from_dict(mind.last_processed_source)
        if previous == stimulus.source or (
            previous is not None
            and previous.source_run_id == stimulus.source.source_run_id
            and previous.source_event_id >= stimulus.source.source_event_id
        ):
            return mind
        updated = ActorMindV1.from_dict(mind.to_dict(), actor=mind.actor)
        if stimulus.kind == "phase_decay":
            self._decay(updated)
        elif stimulus.kind in {"direct_question", "accusation", "vote", "support"}:
            self._relationship_stimulus(updated, stimulus)
        elif stimulus.kind == "stage_pressure":
            self._stage_pressure(updated, stimulus)
        elif stimulus.kind == "own_commitment":
            self._commitment(updated, stimulus)
        updated.revision += 1
        updated.last_processed_source = stimulus.source.to_dict()
        return updated

    def record_behavior(
        self,
        mind: ActorMindV1,
        *,
        speech_act: str,
        length_band: str,
        opening_fingerprint: str,
    ) -> ActorMindV1:
        updated = ActorMindV1.from_dict(mind.to_dict(), actor=mind.actor)
        _append_bounded(updated.recent_behavior["speech_acts"], speech_act, 6)
        _append_bounded(updated.recent_behavior["length_bands"], length_band, 6)
        if opening_fingerprint:
            _append_bounded(
                updated.recent_behavior["opening_fingerprints"],
                opening_fingerprint[:80],
                4,
            )
        updated.revision += 1
        return updated

    def _relationship_stimulus(
        self,
        mind: ActorMindV1,
        stimulus: ActorMindStimulusV1,
    ) -> None:
        actor = stimulus.source_actor
        if not actor or actor == mind.actor:
            return
        relationship = mind.relationships.setdefault(
            actor,
            {"trust": 0, "hostility": 0, "pressure": 0, "unresolved_thread_ids": []},
        )
        if stimulus.kind == "support":
            relationship["trust"] = _clamp(_int(relationship.get("trust")) + 10, -100, 100)
            mind.affect["confidence"] = _clamp(_int(mind.affect.get("confidence")) + 6, 0, 100)
            mind.affect["valence"] = _clamp(_int(mind.affect.get("valence")) + 5, -100, 100)
            return
        pressure_delta = 18 if stimulus.kind == "direct_question" else 25
        hostility_delta = 5 if stimulus.kind == "direct_question" else 12
        if stimulus.kind == "vote":
            pressure_delta = 20
            hostility_delta = 15
        relationship["trust"] = _clamp(_int(relationship.get("trust")) - hostility_delta, -100, 100)
        relationship["hostility"] = _clamp(
            _int(relationship.get("hostility")) + hostility_delta, 0, 100
        )
        relationship["pressure"] = _clamp(
            _int(relationship.get("pressure")) + pressure_delta, 0, 100
        )
        mind.affect["stress"] = _clamp(_int(mind.affect.get("stress")) + 12, 0, 100)
        mind.affect["arousal"] = _clamp(_int(mind.affect.get("arousal")) + 10, 0, 100)
        mind.affect["last_trigger_source"] = stimulus.source.to_dict()
        thread_id = _stable_id("thread", mind.actor, actor, stimulus.source)
        existing = next(
            (item for item in mind.open_threads if item.get("thread_id") == thread_id),
            None,
        )
        if existing is None:
            mind.open_threads.append(
                {
                    "thread_id": thread_id,
                    "source": stimulus.source.to_dict(),
                    "source_actor": actor,
                    "kind": stimulus.kind,
                    "urgency": _clamp(stimulus.urgency, 0, 100),
                }
            )
            mind.open_threads = mind.open_threads[-8:]
        unresolved = relationship.get("unresolved_thread_ids")
        if not isinstance(unresolved, list):
            unresolved = []
            relationship["unresolved_thread_ids"] = unresolved
        _append_bounded(unresolved, thread_id, 4)

    def _stage_pressure(self, mind: ActorMindV1, stimulus: ActorMindStimulusV1) -> None:
        urgency = _clamp(stimulus.urgency, 0, 100)
        mind.affect["stress"] = max(_int(mind.affect.get("stress")), urgency)
        mind.affect["arousal"] = max(_int(mind.affect.get("arousal")), min(100, urgency + 5))
        mind.affect["last_trigger_source"] = stimulus.source.to_dict()

    def _commitment(self, mind: ActorMindV1, stimulus: ActorMindStimulusV1) -> None:
        if not stimulus.commitment_kind:
            return
        mind.commitments.append(
            {
                "commitment_id": _stable_id(
                    "commitment", mind.actor, stimulus.target or "", stimulus.source
                ),
                "kind": stimulus.commitment_kind,
                "target": stimulus.target,
                "source": stimulus.source.to_dict(),
                "status": "active",
            }
        )
        mind.commitments = mind.commitments[-12:]

    def _decay(self, mind: ActorMindV1) -> None:
        mind.affect["stress"] = max(0, _int(mind.affect.get("stress")) - 8)
        mind.affect["arousal"] = max(10, _int(mind.affect.get("arousal")) - 6)
        for relationship in mind.relationships.values():
            relationship["pressure"] = max(0, _int(relationship.get("pressure")) - 10)


def public_affect_projection(mind: ActorMindV1) -> dict[str, str]:
    stress = _int(mind.affect.get("stress"))
    arousal = _int(mind.affect.get("arousal"))
    valence = _int(mind.affect.get("valence"))
    mood = "tense" if stress >= 70 else "frustrated" if valence <= -45 else "calm"
    intensity = "high" if max(stress, arousal) >= 80 else "low" if arousal <= 30 else "medium"
    pace = "fast" if arousal >= 75 else "slow" if arousal <= 25 else "natural"
    return {"mood": mood, "intensity": intensity, "pace": pace}


def _stable_id(prefix: str, actor: str, target: str, source: EventCoordinateV1) -> str:
    value = f"{prefix}:{actor}:{target}:{source.source_run_id}:{source.source_event_id}"
    return f"{prefix[:2]}_{hashlib.sha256(value.encode()).hexdigest()[:20]}"


def _normalized_affect(value: object) -> dict[str, object]:
    payload = value if isinstance(value, Mapping) else {}
    coordinate = EventCoordinateV1.from_dict(payload.get("last_trigger_source"))
    return {
        "valence": _clamp(_int(payload.get("valence")), -100, 100),
        "arousal": _clamp(_int(payload.get("arousal"), 20), 0, 100),
        "confidence": _clamp(_int(payload.get("confidence"), 50), 0, 100),
        "stress": _clamp(_int(payload.get("stress"), 20), 0, 100),
        "last_trigger_source": coordinate.to_dict() if coordinate else None,
    }


def _bounded_mapping(value: object, *, limit: int) -> dict[str, dict[str, object]]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, dict[str, object]] = {}
    for key, item in list(value.items())[:limit]:
        if isinstance(key, str) and isinstance(item, Mapping):
            result[key] = copy.deepcopy(dict(item))
    return result


def _bounded_dict_list(value: object, *, limit: int) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [copy.deepcopy(dict(item)) for item in value[-limit:] if isinstance(item, Mapping)]


def _bounded_strings(value: object, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:120] for item in value[-limit:] if isinstance(item, str)]


def _append_bounded(values: list[Any], value: Any, limit: int) -> None:
    values.append(value)
    del values[:-limit]


def _int(value: object, fallback: int = 0) -> int:
    return value if type(value) is int else fallback


def _clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))
