from __future__ import annotations

from typing import Any


DEFAULT_THINKING_MAX_TOKENS = 16_384
DEFAULT_NON_THINKING_MAX_TOKENS = 512
GLM_5_2_MAX_OUTPUT_TOKENS = 131_072
DEFAULT_MAX_OUTPUT_TOKENS = 384_000


def max_output_tokens_limit(provider: str, model_id: str) -> int:
    if provider == "agent_plan" and model_id.lower().startswith("glm-5-2-"):
        return GLM_5_2_MAX_OUTPUT_TOKENS
    return DEFAULT_MAX_OUTPUT_TOKENS


def default_max_tokens(
    *,
    supports_thinking: bool,
    thinking: str,
    limit: int,
) -> int:
    preferred = (
        DEFAULT_THINKING_MAX_TOKENS
        if supports_thinking and thinking != "disabled"
        else DEFAULT_NON_THINKING_MAX_TOKENS
    )
    return min(preferred, limit)


def parameter_values_with_default_max_tokens(
    values: dict[str, Any] | None,
    *,
    supports_thinking: bool,
    limit: int,
) -> dict[str, Any]:
    normalized = dict(values or {})
    thinking = normalized.get("thinking", "default")
    normalized["thinking"] = thinking
    configured = normalized.get("max_tokens")
    if (
        not isinstance(configured, int)
        or isinstance(configured, bool)
        or not 1 <= configured <= limit
    ):
        normalized["max_tokens"] = default_max_tokens(
            supports_thinking=supports_thinking,
            thinking=thinking,
            limit=limit,
        )
    return normalized
