from __future__ import annotations

import copy
import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping


StyleGateMode = Literal["legacy", "async_observe"]
ActorMindMode = Literal["off", "shadow", "read"]
SentenceStreamMode = Literal[
    "off",
    "committed_segments",
    "committed_segments_v2",
]
AffectDeliveryMode = Literal["off", "shadow", "on"]
VoicePreemptMode = Literal["off", "deterministic"]


class LivenessSnapshotError(ValueError):
    """Raised when a persisted non-legacy liveness snapshot is malformed."""


@dataclass(frozen=True)
class LivenessExperimentAssignmentV1:
    snapshot: "LivenessExperienceSnapshotV1"
    experiment_id: str
    variant: Literal["control", "treatment"]


@dataclass(frozen=True)
class LivenessFeatureModesV1:
    style_gate: StyleGateMode = "async_observe"
    actor_mind: ActorMindMode = "shadow"
    sentence_stream: SentenceStreamMode = "off"
    affect_delivery: AffectDeliveryMode = "shadow"
    tts_prefetch_depth: Literal[0, 1] = 0
    voice_preempt: VoicePreemptMode = "off"

    @classmethod
    def from_dict(cls, value: object) -> "LivenessFeatureModesV1":
        payload = value if isinstance(value, Mapping) else {}
        style_gate = _enum_value(payload, "style_gate", {"legacy", "async_observe"}, "legacy")
        actor_mind = _enum_value(payload, "actor_mind", {"off", "shadow", "read"}, "off")
        sentence_stream = _enum_value(
            payload,
            "sentence_stream",
            {"off", "committed_segments", "committed_segments_v2"},
            "off",
        )
        affect_delivery = _enum_value(
            payload,
            "affect_delivery",
            {"off", "shadow", "on"},
            "off",
        )
        raw_prefetch = payload.get("tts_prefetch_depth")
        tts_prefetch_depth: Literal[0, 1] = 1 if raw_prefetch == 1 else 0
        voice_preempt = _enum_value(
            payload,
            "voice_preempt",
            {"off", "deterministic"},
            "off",
        )
        return cls(
            style_gate=style_gate,  # type: ignore[arg-type]
            actor_mind=actor_mind,  # type: ignore[arg-type]
            sentence_stream=sentence_stream,  # type: ignore[arg-type]
            affect_delivery=affect_delivery,  # type: ignore[arg-type]
            tts_prefetch_depth=tts_prefetch_depth,
            voice_preempt=voice_preempt,  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class LivenessExperienceSnapshotV1:
    schema_version: Literal[1]
    experience_revision: str
    scene_packet_version: str
    actor_mind_version: str
    turn_policy_version: str
    renderer_version: str
    quality_gate_version: str
    speech_stream_version: str
    affect_mapping_version: str
    prompt_revision: str
    feature_modes: LivenessFeatureModesV1

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(asdict(self))

    def public_summary(
        self,
        *,
        experiment_id: str | None = None,
        variant: str | None = None,
    ) -> dict[str, Any]:
        return {
            "revision": self.experience_revision,
            "experiment_id": experiment_id,
            "variant": variant,
            "feature_modes": asdict(self.feature_modes),
            "scene_packet_version": self.scene_packet_version,
            "actor_mind_version": self.actor_mind_version,
            "quality_gate_version": self.quality_gate_version,
            "speech_stream_version": self.speech_stream_version,
            "affect_mapping_version": self.affect_mapping_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> "LivenessExperienceSnapshotV1":
        if not isinstance(value, Mapping) or value.get("schema_version") != 1:
            return legacy_liveness_experience()
        required = (
            "experience_revision",
            "scene_packet_version",
            "actor_mind_version",
            "turn_policy_version",
            "renderer_version",
            "quality_gate_version",
            "speech_stream_version",
            "affect_mapping_version",
            "prompt_revision",
        )
        if any(not _clean_string(value.get(name)) for name in required):
            return legacy_liveness_experience()
        return cls(
            schema_version=1,
            experience_revision=str(value["experience_revision"]),
            scene_packet_version=str(value["scene_packet_version"]),
            actor_mind_version=str(value["actor_mind_version"]),
            turn_policy_version=str(value["turn_policy_version"]),
            renderer_version=str(value["renderer_version"]),
            quality_gate_version=str(value["quality_gate_version"]),
            speech_stream_version=str(value["speech_stream_version"]),
            affect_mapping_version=str(value["affect_mapping_version"]),
            prompt_revision=str(value["prompt_revision"]),
            feature_modes=LivenessFeatureModesV1.from_dict(value.get("feature_modes")),
        )


def liveness_experience_v1(
    *,
    feature_modes: LivenessFeatureModesV1 | None = None,
) -> LivenessExperienceSnapshotV1:
    resolved_modes = feature_modes or LivenessFeatureModesV1()
    return LivenessExperienceSnapshotV1(
        schema_version=1,
        experience_revision="liveness-v1",
        scene_packet_version="scene-packet-v1",
        actor_mind_version="actor-mind-v1",
        turn_policy_version="turn-policy-v1",
        renderer_version="persona-renderer-v1",
        quality_gate_version="hard-speech-gate-v1",
        speech_stream_version=(
            "speech-v2"
            if resolved_modes.sentence_stream == "committed_segments_v2"
            else "speech-v1"
        ),
        affect_mapping_version="affect-delivery-v2",
        prompt_revision="lifelike-prompt-v1",
        feature_modes=resolved_modes,
    )


def assign_liveness_experiment_v1(
    *,
    session_id: str,
    experiment_id: str,
    treatment_percent: int,
    experience_revision: str = "liveness-v1",
) -> LivenessExperimentAssignmentV1:
    if not session_id or not experiment_id:
        raise ValueError("liveness assignment requires session and experiment ids")
    if not 0 <= treatment_percent <= 100:
        raise ValueError("liveness treatment percent must be between 0 and 100")
    if experience_revision != "liveness-v1":
        raise ValueError("unsupported liveness experience revision")
    bucket = int.from_bytes(
        hashlib.sha256(f"{experiment_id}\0{session_id}".encode()).digest()[:8],
        "big",
    ) % 10_000
    treatment = bucket < treatment_percent * 100
    feature_modes = (
        LivenessFeatureModesV1(
            style_gate="async_observe",
            actor_mind="read",
            sentence_stream="off",
            affect_delivery="on",
            tts_prefetch_depth=0,
            voice_preempt="off",
        )
        if treatment
        else LivenessFeatureModesV1(
            style_gate="async_observe",
            actor_mind="shadow",
            sentence_stream="off",
            affect_delivery="shadow",
            tts_prefetch_depth=0,
            voice_preempt="off",
        )
    )
    return LivenessExperimentAssignmentV1(
        snapshot=liveness_experience_v1(feature_modes=feature_modes),
        experiment_id=experiment_id,
        variant="treatment" if treatment else "control",
    )


def legacy_liveness_experience() -> LivenessExperienceSnapshotV1:
    return LivenessExperienceSnapshotV1(
        schema_version=1,
        experience_revision="legacy-v0",
        scene_packet_version="legacy-v0",
        actor_mind_version="legacy-v0",
        turn_policy_version="legacy-v0",
        renderer_version="legacy-v0",
        quality_gate_version="legacy-v0",
        speech_stream_version="legacy-v0",
        affect_mapping_version="legacy-v0",
        prompt_revision="legacy-v0",
        feature_modes=LivenessFeatureModesV1(
            style_gate="legacy",
            actor_mind="off",
            sentence_stream="off",
            affect_delivery="off",
            tts_prefetch_depth=0,
            voice_preempt="off",
        ),
    )


def liveness_experience_from_storage(value: object) -> LivenessExperienceSnapshotV1:
    if value is None:
        return legacy_liveness_experience()
    if not isinstance(value, Mapping) or value.get("schema_version") != 1:
        raise LivenessSnapshotError("invalid liveness experience snapshot")
    required = (
        "experience_revision",
        "scene_packet_version",
        "actor_mind_version",
        "turn_policy_version",
        "renderer_version",
        "quality_gate_version",
        "speech_stream_version",
        "affect_mapping_version",
        "prompt_revision",
    )
    if any(not _clean_string(value.get(name)) for name in required):
        raise LivenessSnapshotError("incomplete liveness experience snapshot")
    modes = value.get("feature_modes")
    if not isinstance(modes, Mapping):
        raise LivenessSnapshotError("missing liveness feature modes")
    allowed_modes: dict[str, set[object]] = {
        "style_gate": {"legacy", "async_observe"},
        "actor_mind": {"off", "shadow", "read"},
        "sentence_stream": {
            "off",
            "committed_segments",
            "committed_segments_v2",
        },
        "affect_delivery": {"off", "shadow", "on"},
        "tts_prefetch_depth": {0, 1},
        "voice_preempt": {"off", "deterministic"},
    }
    if (
        type(modes.get("tts_prefetch_depth")) is not int
        or any(modes.get(name) not in allowed for name, allowed in allowed_modes.items())
    ):
        raise LivenessSnapshotError("invalid liveness feature modes")
    snapshot = LivenessExperienceSnapshotV1.from_dict(value)
    uses_segments_v2 = (
        snapshot.feature_modes.sentence_stream == "committed_segments_v2"
    )
    uses_speech_v2 = snapshot.speech_stream_version == "speech-v2"
    if uses_segments_v2 != uses_speech_v2:
        raise LivenessSnapshotError("segments v2 and speech-v2 must be paired")
    return snapshot


def _clean_string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _enum_value(
    payload: Mapping[object, object],
    name: str,
    allowed: set[str],
    fallback: str,
) -> str:
    value = payload.get(name)
    return value if isinstance(value, str) and value in allowed else fallback
