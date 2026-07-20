from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.werewolf.liveness_review import (
    FrozenReviewManifest,
    build_review_package,
    write_review_package,
)
from app.werewolf.lm import parse_json_object
from app.werewolf.prompts_zh import build_prompt
from app.werewolf.providers import DeepSeekProvider


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PilotSourceScenario(_StrictModel):
    scenario_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,100}$")
    slice: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,100}$")
    action: Literal[
        "debate",
        "sheriff_speech",
        "sheriff_pk_speech",
        "exile_pk_speech",
        "exile_last_words",
    ]
    speaker: str = Field(min_length=1, max_length=100)
    context: str = Field(min_length=1, max_length=20_000)
    baseline_text: str = Field(min_length=1, max_length=10_000)
    public_speech_scene: dict[str, Any]
    source_trace: dict[str, Any]

    @field_validator("public_speech_scene")
    @classmethod
    def _scene_contract(cls, value: dict[str, Any]) -> dict[str, Any]:
        if value.get("schema_version") != 1:
            raise ValueError("public_speech_scene must use schema_version 1")
        if not isinstance(value.get("turn_plan"), dict):
            raise ValueError("public_speech_scene must contain a turn_plan")
        return value


class PilotSourceManifest(_StrictModel):
    schema_version: Literal[1]
    experiment_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,100}$")
    generator_model: str = Field(min_length=1, max_length=120)
    scenarios: list[PilotSourceScenario] = Field(min_length=1, max_length=100)


def generate_manifest(
    source: PilotSourceManifest,
    *,
    provider: DeepSeekProvider,
) -> tuple[FrozenReviewManifest, dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    generations: list[dict[str, Any]] = []
    for item in source.scenarios:
        prompt, _schema = build_prompt(
            item.action,
            {"public_speech_scene": item.public_speech_scene},
        )
        raw_response = provider.complete_json(
            model=source.generator_model,
            prompt=prompt,
            temperature=0.4,
        )
        result = parse_json_object(raw_response)
        candidate_text = result.get("say")
        if not isinstance(candidate_text, str) or not candidate_text.strip():
            raise ValueError(f"generator returned no say for {item.scenario_id}")
        candidate_text = candidate_text.strip()
        scenarios.append(
            {
                "scenario_id": item.scenario_id,
                "slice": item.slice,
                "context": item.context,
                "baseline": {
                    "timeline": [
                        {
                            "speaker": item.speaker,
                            "text": item.baseline_text,
                            "start_ms": 0,
                            "end_ms": 0,
                        }
                    ]
                },
                "candidate": {
                    "timeline": [
                        {
                            "speaker": item.speaker,
                            "text": candidate_text,
                            "start_ms": 0,
                            "end_ms": 0,
                        }
                    ]
                },
            }
        )
        generations.append(
            {
                "scenario_id": item.scenario_id,
                "source_trace": item.source_trace,
                "generator_model": source.generator_model,
                "prompt": prompt,
                "raw_response": raw_response,
            }
        )
    return (
        FrozenReviewManifest.model_validate(
            {
                "schema_version": 1,
                "experiment_id": source.experiment_id,
                "scenarios": scenarios,
            }
        ),
        {
            "schema_version": 1,
            "experiment_id": source.experiment_id,
            "generator_model": source.generator_model,
            "items": generations,
        },
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a text-only liveness renderer pilot review package."
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--randomization-seed", required=True)
    args = parser.parse_args(argv)

    source = PilotSourceManifest.model_validate_json(
        args.source.read_text(encoding="utf-8")
    )
    manifest, generation_evidence = generate_manifest(
        source,
        provider=DeepSeekProvider(),
    )
    package = build_review_package(
        manifest,
        randomization_seed=args.randomization_seed,
    )
    write_review_package(package, args.output_dir)
    private_dir = args.output_dir / "private"
    _write_json(private_dir / "frozen_manifest.json", manifest.model_dump(mode="json"))
    _write_json(private_dir / "generation_evidence.json", generation_evidence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
