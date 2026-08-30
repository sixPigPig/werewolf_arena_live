import type {
  AdminModel,
  AdminModelCatalog,
  AdminModelSource,
  ModelParameters,
  ModelProvider,
  ModelReasoningPolicy,
  ThinkingMode,
  VolcLoginChallenge,
} from "@/features/models/types";

export function parseVolcLoginChallenge(value: unknown): VolcLoginChallenge {
  const record = requiredRecord(value, "volc login challenge");
  const alreadyAuthenticated = requiredBoolean(
    record.already_authenticated,
    "already_authenticated",
  );
  if (alreadyAuthenticated) {
    return {
      authorize_url: requiredNullableString(record.authorize_url, "authorize_url"),
      expires_in_sec: requiredNullableInteger(
        record.expires_in_sec,
        "expires_in_sec",
      ),
      already_authenticated: true,
    };
  }
  return {
    authorize_url: requiredString(record.authorize_url, "authorize_url"),
    expires_in_sec: requiredInteger(record.expires_in_sec, "expires_in_sec"),
    already_authenticated: false,
  };
}

export function parseAdminModelCatalog(value: unknown): AdminModelCatalog {
  const record = requiredRecord(value, "model catalog");
  return {
    generated_at: requiredString(record.generated_at, "generated_at"),
    sources: requiredArray(record.sources, "sources").map(parseSource),
    models: requiredArray(record.models, "models").map(parseModel),
  };
}

function parseSource(value: unknown): AdminModelSource {
  const record = requiredRecord(value, "model source");
  return {
    provider: providerValue(record.provider),
    label: requiredString(record.label, "label"),
    refresh_mode: refreshModeValue(record.refresh_mode),
    status: sourceStatusValue(record.status),
    model_count: requiredInteger(record.model_count, "model_count"),
    last_synced_at: requiredNullableString(record.last_synced_at, "last_synced_at"),
    docs_url: requiredString(record.docs_url, "docs_url"),
    error: requiredNullableString(record.error, "error"),
  };
}

function parseModel(value: unknown): AdminModel {
  const record = requiredRecord(value, "model");
  return {
    provider: providerValue(record.provider),
    model_id: requiredString(record.model_id, "model_id"),
    source_model_id: requiredNullableString(record.source_model_id, "source_model_id"),
    display_name: requiredString(record.display_name, "display_name"),
    description: requiredNullableString(record.description, "description"),
    available: requiredBoolean(record.available, "available"),
    enabled: requiredBoolean(record.enabled, "enabled"),
    is_default: requiredBoolean(record.is_default, "is_default"),
    selected_by_source: requiredBoolean(record.selected_by_source, "selected_by_source"),
    supports_thinking: requiredBoolean(record.supports_thinking, "supports_thinking"),
    assigned_profile_count: requiredInteger(
      record.assigned_profile_count,
      "assigned_profile_count",
    ),
    parameters: parseParameters(record.parameters),
    reasoning_policy: parseReasoningPolicy(record.reasoning_policy),
    max_output_tokens_limit: requiredInteger(
      record.max_output_tokens_limit,
      "max_output_tokens_limit",
    ),
    docs_url: requiredString(record.docs_url, "docs_url"),
    updated_at: requiredString(record.updated_at, "updated_at"),
  };
}

function parseParameters(value: unknown): ModelParameters {
  const record = requiredRecord(value, "model parameters");
  return {
    thinking: thinkingValue(record.thinking),
    reasoning_effort: requiredNullableString(
      record.reasoning_effort,
      "reasoning_effort",
    ),
    temperature: requiredNullableNumber(record.temperature, "temperature"),
    top_p: requiredNullableNumber(record.top_p, "top_p"),
    max_tokens: requiredInteger(record.max_tokens, "max_tokens"),
    max_tokens_mode: maxTokensModeValue(record.max_tokens_mode),
    frequency_penalty: requiredNullableNumber(
      record.frequency_penalty,
      "frequency_penalty",
    ),
    presence_penalty: requiredNullableNumber(
      record.presence_penalty,
      "presence_penalty",
    ),
  };
}

function parseReasoningPolicy(value: unknown): ModelReasoningPolicy {
  const record = requiredRecord(value, "reasoning policy");
  const maxTokensRecord = requiredRecord(
    record.max_tokens_by_effort,
    "max_tokens_by_effort",
  );
  return {
    thinking_options: requiredArray(
      record.thinking_options,
      "thinking_options",
    ).map(thinkingValue),
    default_thinking: thinkingValue(record.default_thinking),
    thinking_locked: requiredBoolean(record.thinking_locked, "thinking_locked"),
    reasoning_effort_options: requiredArray(
      record.reasoning_effort_options,
      "reasoning_effort_options",
    ).map((item) => requiredString(item, "reasoning_effort")),
    default_reasoning_effort: requiredNullableString(
      record.default_reasoning_effort,
      "default_reasoning_effort",
    ),
    max_tokens_by_effort: Object.fromEntries(
      Object.entries(maxTokensRecord).map(([effort, tokens]) => [
        effort,
        requiredInteger(tokens, `max_tokens_by_effort.${effort}`),
      ]),
    ),
    default_max_tokens: requiredInteger(
      record.default_max_tokens,
      "default_max_tokens",
    ),
    disabled_max_tokens: requiredNullableInteger(
      record.disabled_max_tokens,
      "disabled_max_tokens",
    ),
    sampling_parameters_allowed_when_thinking: requiredBoolean(
      record.sampling_parameters_allowed_when_thinking,
      "sampling_parameters_allowed_when_thinking",
    ),
  };
}

function providerValue(value: unknown): ModelProvider {
  if (value === "agent_plan" || value === "ark" || value === "deepseek") return value;
  throw new Error("Invalid model provider");
}

function refreshModeValue(value: unknown): "manual" | "automatic" {
  if (value === "manual" || value === "automatic") return value;
  throw new Error("Invalid refresh mode");
}

function sourceStatusValue(value: unknown): "ok" | "error" {
  if (value === "ok" || value === "error") return value;
  throw new Error("Invalid model source status");
}

function thinkingValue(value: unknown): ThinkingMode {
  if (value === "enabled" || value === "disabled") return value;
  throw new Error("Invalid thinking mode");
}

function maxTokensModeValue(value: unknown): "auto" | "manual" {
  if (value === "auto" || value === "manual") return value;
  throw new Error("Invalid max tokens mode");
}

function requiredRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`Invalid ${label}`);
  }
  return value as Record<string, unknown>;
}

function requiredArray(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) throw new Error(`Invalid ${label}`);
  return value;
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value) throw new Error(`Invalid ${label}`);
  return value;
}

function requiredNullableString(value: unknown, label: string): string | null {
  if (value === null) return null;
  return requiredString(value, label);
}

function requiredNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`Invalid ${label}`);
  }
  return value;
}

function requiredInteger(value: unknown, label: string): number {
  const number = requiredNumber(value, label);
  if (!Number.isInteger(number)) throw new Error(`Invalid ${label}`);
  return number;
}

function requiredNullableNumber(value: unknown, label: string): number | null {
  if (value === null) return null;
  return requiredNumber(value, label);
}

function requiredNullableInteger(value: unknown, label: string): number | null {
  if (value === null) return null;
  return requiredInteger(value, label);
}

function requiredBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") throw new Error(`Invalid ${label}`);
  return value;
}
