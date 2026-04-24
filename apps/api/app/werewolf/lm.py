from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from app.werewolf.prompts_zh import build_prompt

DEFAULT_RETRIES = 3


class ModelProvider(Protocol):
    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        pass


@dataclass
class LmLog:
    prompt: str
    raw_response: str
    result: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "raw_response": self.raw_response,
            "result": self.result,
        }


class FakeProvider:
    def __init__(self, responses: list[dict[str, Any] | str]) -> None:
        self.responses = responses
        self.calls = 0

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        del model, prompt, temperature
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        if isinstance(response, str):
            return response
        return json.dumps(response, ensure_ascii=False)


def generate_action(
    *,
    provider: ModelProvider,
    action: str,
    world_state: dict[str, Any],
    model: str,
    allowed_values: list[Any] | None = None,
    result_key: str | None = None,
    retries: int = DEFAULT_RETRIES,
) -> tuple[Any | None, LmLog]:
    prompt, _schema = build_prompt(action, world_state)
    raw_responses: list[str] = []
    last_result: dict[str, Any] | None = None

    for attempt in range(retries):
        raw_response = provider.complete_json(
            model=model,
            prompt=prompt,
            temperature=min(1.0, 0.4 + attempt * 0.2),
        )
        raw_responses.append(raw_response)
        try:
            result = parse_json_object(raw_response)
        except ValueError:
            continue

        last_result = result
        value = result.get(result_key) if result_key else result
        normalized_value = _normalize_allowed_value(value, allowed_values)
        if allowed_values is None or normalized_value in allowed_values:
            return normalized_value, LmLog(prompt=prompt, raw_response=raw_response, result=result)

    return None, LmLog(
        prompt=prompt,
        raw_response="\n--- retry ---\n".join(raw_responses),
        result=last_result,
    )


def _normalize_allowed_value(value: Any, allowed_values: list[Any] | None) -> Any:
    if allowed_values is None:
        return value
    if value in allowed_values:
        return value
    if all(isinstance(item, str) for item in allowed_values) and value is not None:
        return str(value)
    return value


def parse_json_object(raw_response: str) -> dict[str, Any]:
    content = raw_response.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    decoder = json.JSONDecoder()
    try:
        parsed, _index = decoder.raw_decode(content)
    except json.JSONDecodeError as exc:
        raise ValueError("Model response was not valid JSON.") from exc

    if not isinstance(parsed, dict):
        raise ValueError("Model response JSON must be an object.")
    return parsed
