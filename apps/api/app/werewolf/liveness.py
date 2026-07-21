from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping


class LivenessSnapshotError(ValueError):
    """Raised when the current liveness snapshot is malformed."""


@dataclass(frozen=True)
class LivenessFeatureModesV1:
    """The only supported runtime mode for new games."""

    style_gate: Literal["async_observe"] = "async_observe"
    actor_mind: Literal["read"] = "read"
    sentence_stream: Literal["committed_segments_v2"] = "committed_segments_v2"
    affect_delivery: Literal["on"] = "on"
    tts_prefetch_depth: Literal[1] = 1
    voice_preempt: Literal["deterministic"] = "deterministic"

    @classmethod
    def from_dict(cls, value: object) -> "LivenessFeatureModesV1":
        if not isinstance(value, Mapping):
            raise LivenessSnapshotError("missing liveness feature modes")
        expected = asdict(cls())
        if dict(value) != expected:
            raise LivenessSnapshotError("unsupported liveness feature modes")
        return cls()


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
        return asdict(self)

    def public_summary(self) -> dict[str, Any]:
        return {
            "revision": self.experience_revision,
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
        snapshot = cls(
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
        if snapshot != liveness_experience_v1():
            raise LivenessSnapshotError("unsupported liveness experience snapshot")
        return snapshot


def liveness_experience_v1() -> LivenessExperienceSnapshotV1:
    return LivenessExperienceSnapshotV1(
        schema_version=1,
        experience_revision="liveness-v1",
        scene_packet_version="scene-packet-v1",
        actor_mind_version="actor-mind-v1",
        turn_policy_version="turn-policy-v1",
        renderer_version="persona-renderer-v1",
        quality_gate_version="hard-speech-gate-v1",
        speech_stream_version="speech-v2",
        affect_mapping_version="affect-delivery-v2",
        prompt_revision="lifelike-prompt-v1",
        feature_modes=LivenessFeatureModesV1(),
    )


def liveness_experience_from_storage(value: object) -> LivenessExperienceSnapshotV1:
    if value is None:
        return liveness_experience_v1()
    return LivenessExperienceSnapshotV1.from_dict(value)


def _clean_string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""
