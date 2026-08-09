from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


ThinkingMode = Literal["enabled", "disabled"]
MaxTokensMode = Literal["auto", "manual"]

DEFAULT_NON_THINKING_MAX_TOKENS = 512
GLM_5_2_MAX_OUTPUT_TOKENS = 131_072
DEFAULT_MAX_OUTPUT_TOKENS = 384_000


@dataclass(frozen=True)
class ReasoningPolicy:
    """Model-level Thinking, effort, and output-budget contract."""

    thinking_options: tuple[ThinkingMode, ...]
    default_thinking: ThinkingMode
    thinking_locked: bool
    reasoning_effort_options: tuple[str, ...]
    default_reasoning_effort: str | None
    max_tokens_by_effort: dict[str, int]
    default_max_tokens: int
    disabled_max_tokens: int | None
    sampling_parameters_allowed_when_thinking: bool


_NON_THINKING_POLICY = ReasoningPolicy(
    thinking_options=("disabled",),
    default_thinking="disabled",
    thinking_locked=True,
    reasoning_effort_options=(),
    default_reasoning_effort=None,
    max_tokens_by_effort={},
    default_max_tokens=DEFAULT_NON_THINKING_MAX_TOKENS,
    disabled_max_tokens=DEFAULT_NON_THINKING_MAX_TOKENS,
    sampling_parameters_allowed_when_thinking=True,
)

_DOUBAO_POLICY = ReasoningPolicy(
    thinking_options=("enabled", "disabled"),
    default_thinking="enabled",
    thinking_locked=False,
    reasoning_effort_options=("low", "medium", "high"),
    default_reasoning_effort="low",
    max_tokens_by_effort={"low": 4_096, "medium": 8_192, "high": 16_384},
    default_max_tokens=4_096,
    disabled_max_tokens=DEFAULT_NON_THINKING_MAX_TOKENS,
    sampling_parameters_allowed_when_thinking=True,
)

_GLM_5_2_POLICY = ReasoningPolicy(
    thinking_options=("enabled", "disabled"),
    default_thinking="enabled",
    thinking_locked=False,
    reasoning_effort_options=("high", "max"),
    default_reasoning_effort="high",
    max_tokens_by_effort={"high": 8_192, "max": 16_384},
    default_max_tokens=8_192,
    disabled_max_tokens=DEFAULT_NON_THINKING_MAX_TOKENS,
    sampling_parameters_allowed_when_thinking=True,
)

_DEEPSEEK_V4_POLICY = ReasoningPolicy(
    thinking_options=("enabled", "disabled"),
    default_thinking="enabled",
    thinking_locked=False,
    reasoning_effort_options=("high", "max"),
    default_reasoning_effort="high",
    max_tokens_by_effort={"high": 8_192, "max": 16_384},
    default_max_tokens=8_192,
    disabled_max_tokens=DEFAULT_NON_THINKING_MAX_TOKENS,
    sampling_parameters_allowed_when_thinking=False,
)

_KIMI_K3_POLICY = ReasoningPolicy(
    thinking_options=("enabled",),
    default_thinking="enabled",
    thinking_locked=True,
    reasoning_effort_options=("low", "high", "max"),
    default_reasoning_effort="low",
    max_tokens_by_effort={"low": 4_096, "high": 8_192, "max": 16_384},
    default_max_tokens=4_096,
    disabled_max_tokens=None,
    sampling_parameters_allowed_when_thinking=True,
)

_MINIMAX_M3_POLICY = ReasoningPolicy(
    thinking_options=("enabled", "disabled"),
    default_thinking="enabled",
    thinking_locked=False,
    reasoning_effort_options=(),
    default_reasoning_effort=None,
    max_tokens_by_effort={},
    default_max_tokens=8_192,
    disabled_max_tokens=DEFAULT_NON_THINKING_MAX_TOKENS,
    sampling_parameters_allowed_when_thinking=True,
)


def max_output_tokens_limit(provider: str, model_id: str) -> int:
    if provider in {"agent_plan", "ark"} and "glm-5-2" in model_id.lower():
        return GLM_5_2_MAX_OUTPUT_TOKENS
    return DEFAULT_MAX_OUTPUT_TOKENS


def reasoning_policy_for_model(
    provider: str,
    model_id: str,
    *,
    supports_thinking: bool,
) -> ReasoningPolicy:
    """Return the verified policy for one concrete model.

    Provider discovery may advertise generic Thinking support, but it is not
    enough to invent effort levels. Unknown and legacy model families therefore
    remain non-thinking until a verified model-level policy is added here.
    """

    normalized = model_id.strip().lower()
    if "doubao-seed-2-0-code-preview" in normalized:
        return _NON_THINKING_POLICY
    if "glm-5-2" in normalized:
        return _GLM_5_2_POLICY
    if "deepseek-v4" in normalized:
        return _DEEPSEEK_V4_POLICY
    if normalized == "kimi-k3" or normalized.startswith("kimi-k3-"):
        return _KIMI_K3_POLICY
    if normalized == "minimax-m3" or normalized.startswith("minimax-m3-"):
        return _MINIMAX_M3_POLICY
    if "doubao-" in normalized:
        return _DOUBAO_POLICY
    del provider, supports_thinking
    return _NON_THINKING_POLICY


def default_parameter_values(
    provider: str,
    model_id: str,
    *,
    supports_thinking: bool,
    limit: int,
) -> dict[str, Any]:
    policy = reasoning_policy_for_model(
        provider,
        model_id,
        supports_thinking=supports_thinking,
    )
    values: dict[str, Any] = {
        "thinking": policy.default_thinking,
        "reasoning_effort": policy.default_reasoning_effort,
        "max_tokens_mode": "auto",
        "max_tokens": min(policy.default_max_tokens, limit),
    }
    return values


def normalize_model_parameters(
    provider: str,
    model_id: str,
    values: dict[str, Any],
    *,
    supports_thinking: bool,
    limit: int,
    enforce_auto_max_tokens: bool = False,
) -> dict[str, Any]:
    """Validate and canonicalize the complete persisted/runtime contract.

    Admin writes use the default behavior so changing Thinking or effort
    atomically relinks an automatic budget. Runtime callers should pass
    ``enforce_auto_max_tokens=True`` to reject stale or partial snapshots.
    """

    allowed_keys = {
        "thinking",
        "reasoning_effort",
        "temperature",
        "top_p",
        "max_tokens_mode",
        "max_tokens",
        "frequency_penalty",
        "presence_penalty",
    }
    unknown = sorted(set(values) - allowed_keys)
    if unknown:
        raise ValueError(f"unsupported parameters: {', '.join(unknown)}")
    required_keys = {
        "thinking",
        "reasoning_effort",
        "max_tokens_mode",
        "max_tokens",
    }
    missing = sorted(required_keys - set(values))
    if missing:
        raise ValueError(f"missing required parameters: {', '.join(missing)}")

    policy = reasoning_policy_for_model(
        provider,
        model_id,
        supports_thinking=supports_thinking,
    )
    policy_supports_thinking = "enabled" in policy.thinking_options
    if supports_thinking is not policy_supports_thinking:
        raise ValueError(
            "supports_thinking does not match the model reasoning policy"
        )
    thinking = values.get("thinking")
    if thinking not in policy.thinking_options:
        allowed = ", ".join(policy.thinking_options)
        raise ValueError(f"thinking must be one of: {allowed}")

    reasoning_effort = values.get("reasoning_effort")
    if thinking == "disabled":
        if reasoning_effort is not None:
            raise ValueError("reasoning_effort must be empty when thinking is disabled")
    elif policy.reasoning_effort_options:
        if reasoning_effort is None:
            raise ValueError("reasoning_effort is required when thinking is enabled")
        if reasoning_effort not in policy.reasoning_effort_options:
            allowed = ", ".join(policy.reasoning_effort_options)
            raise ValueError(f"reasoning_effort must be one of: {allowed}")
    elif reasoning_effort is not None:
        raise ValueError("reasoning_effort is not supported by this model")

    max_tokens_mode = values.get("max_tokens_mode")
    if max_tokens_mode not in {"auto", "manual"}:
        raise ValueError("max_tokens_mode must be auto or manual")

    configured_max_tokens = values.get("max_tokens")
    if isinstance(configured_max_tokens, bool) or not isinstance(
        configured_max_tokens,
        int,
    ):
        raise ValueError("max_tokens must be an integer")

    linked_max_tokens = _linked_max_tokens(
        policy,
        thinking=thinking,
        reasoning_effort=reasoning_effort,
        limit=limit,
    )
    if max_tokens_mode == "auto":
        if enforce_auto_max_tokens and configured_max_tokens != linked_max_tokens:
            raise ValueError(
                "max_tokens must match the model reasoning policy when "
                "max_tokens_mode is auto"
            )
        max_tokens = linked_max_tokens
    else:
        max_tokens = configured_max_tokens

    if not 1 <= max_tokens <= limit:
        raise ValueError(f"max_tokens must be between 1 and {limit}")

    normalized: dict[str, Any] = {
        "thinking": thinking,
        "reasoning_effort": reasoning_effort,
        "max_tokens_mode": max_tokens_mode,
        "max_tokens": max_tokens,
    }
    _copy_optional_number(values, normalized, "temperature", minimum=0, maximum=2)
    _copy_optional_number(values, normalized, "top_p", minimum=0, maximum=1)
    _copy_optional_number(
        values,
        normalized,
        "frequency_penalty",
        minimum=-2,
        maximum=2,
    )
    _copy_optional_number(
        values,
        normalized,
        "presence_penalty",
        minimum=-2,
        maximum=2,
    )
    return normalized


def _linked_max_tokens(
    policy: ReasoningPolicy,
    *,
    thinking: str,
    reasoning_effort: Any,
    limit: int,
) -> int:
    if thinking == "disabled":
        if policy.disabled_max_tokens is None:
            raise ValueError("thinking cannot be disabled for this model")
        return min(policy.disabled_max_tokens, limit)
    if reasoning_effort is not None:
        return min(policy.max_tokens_by_effort[reasoning_effort], limit)
    return min(policy.default_max_tokens, limit)


def _copy_optional_number(
    source: dict[str, Any],
    target: dict[str, Any],
    key: str,
    *,
    minimum: float,
    maximum: float,
) -> None:
    value = source.get(key)
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum:g} and {maximum:g}")
    target[key] = float(value)
