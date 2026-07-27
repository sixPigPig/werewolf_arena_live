import type {
  AdminModel,
  AdminModelCatalog,
  AdminModelSource,
  ModelParameters,
  ModelProvider,
  ThinkingMode,
} from "@/features/models/types";

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
    refresh_mode: record.refresh_mode === "automatic" ? "automatic" : "manual",
    status: record.status === "error" ? "error" : "ok",
    model_count: requiredNumber(record.model_count, "model_count"),
    last_synced_at: nullableString(record.last_synced_at),
    docs_url: requiredString(record.docs_url, "docs_url"),
    error: nullableString(record.error),
  };
}

function parseModel(value: unknown): AdminModel {
  const record = requiredRecord(value, "model");
  return {
    provider: providerValue(record.provider),
    model_id: requiredString(record.model_id, "model_id"),
    source_model_id: nullableString(record.source_model_id),
    display_name: requiredString(record.display_name, "display_name"),
    description: nullableString(record.description),
    available: requiredBoolean(record.available, "available"),
    enabled: requiredBoolean(record.enabled, "enabled"),
    is_default: requiredBoolean(record.is_default, "is_default"),
    selected_by_source: requiredBoolean(record.selected_by_source, "selected_by_source"),
    supports_thinking: requiredBoolean(record.supports_thinking, "supports_thinking"),
    assigned_profile_count: requiredNumber(record.assigned_profile_count, "assigned_profile_count"),
    parameters: parseParameters(record.parameters),
    reasoning_effort_options: requiredArray(
      record.reasoning_effort_options,
      "reasoning_effort_options",
    ).map((item) => requiredString(item, "reasoning_effort")),
    max_output_tokens_limit: requiredNumber(
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
    reasoning_effort: nullableString(record.reasoning_effort),
    temperature: nullableNumber(record.temperature),
    top_p: nullableNumber(record.top_p),
    max_tokens: nullableNumber(record.max_tokens),
    frequency_penalty: nullableNumber(record.frequency_penalty),
    presence_penalty: nullableNumber(record.presence_penalty),
  };
}

function providerValue(value: unknown): ModelProvider {
  if (value === "agent_plan" || value === "deepseek") return value;
  throw new Error("Invalid model provider");
}

function thinkingValue(value: unknown): ThinkingMode {
  if (value === "enabled" || value === "disabled") return value;
  return "default";
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

function nullableString(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

function requiredNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`Invalid ${label}`);
  }
  return value;
}

function nullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function requiredBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") throw new Error(`Invalid ${label}`);
  return value;
}
