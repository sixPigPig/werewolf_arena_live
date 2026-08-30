import type {
  AdminModel,
  AdminModelCatalog,
  ModelReasoningPolicy,
} from "@/features/models/types";

export const previewModelCatalog: AdminModelCatalog = {
  generated_at: "2026-07-15T12:00:00+08:00",
  sources: [
    {
      provider: "agent_plan",
      label: "火山方舟 Agent Plan",
      refresh_mode: "manual",
      status: "ok",
      model_count: 3,
      last_synced_at: "2026-07-15T11:56:00+08:00",
      docs_url: "https://api.volcengine.com/api-docs/view?action=ChatCompletions&serviceCode=ark&version=2024-01-01",
      error: null,
    },
    {
      provider: "ark",
      label: "火山方舟标准推理 API",
      refresh_mode: "manual",
      status: "ok",
      model_count: 1,
      last_synced_at: "2026-07-15T11:56:00+08:00",
      docs_url: "https://www.volcengine.com/docs/82379/1298454",
      error: null,
    },
    {
      provider: "deepseek",
      label: "DeepSeek 官方 API",
      refresh_mode: "automatic",
      status: "ok",
      model_count: 2,
      last_synced_at: "2026-07-15T12:00:00+08:00",
      docs_url: "https://api-docs.deepseek.com/zh-cn/quick_start/pricing",
      error: null,
    },
  ],
  models: [
    previewModel("ark", "ep-example", true, false),
    previewModel("agent_plan", "doubao-seed-2-0-lite-260215", true, true),
    previewModel("agent_plan", "glm-5-2-260617", true, false),
    previewModel(
      "agent_plan",
      "doubao-seed-2-0-code-preview-260215",
      false,
      false,
    ),
    previewModel("deepseek", "deepseek-v4-flash", true, false),
    previewModel("deepseek", "deepseek-v4-pro", false, false),
  ],
};

function previewModel(
  provider: "agent_plan" | "ark" | "deepseek",
  modelId: string,
  enabled: boolean,
  isDefault: boolean,
): AdminModel {
  const usesCodePreviewPolicy = modelId.includes("doubao-seed-2-0-code-preview");
  const usesHighMaxPolicy =
    provider === "deepseek" ||
    modelId.includes("glm-5-2") ||
    modelId.includes("deepseek-v4") ||
    (!usesCodePreviewPolicy && !modelId.startsWith("doubao-"));
  const usesDoubaoPolicy = modelId.startsWith("doubao-") && !usesCodePreviewPolicy;
  const usesVerifiedThinkingPolicy = usesHighMaxPolicy || usesDoubaoPolicy;
  const supportsThinking = !usesCodePreviewPolicy;
  const parameters = usesVerifiedThinkingPolicy
    ? {
        thinking: "enabled" as const,
        reasoning_effort: usesHighMaxPolicy ? "high" : "low",
        temperature: null,
        top_p: null,
        max_tokens: usesHighMaxPolicy ? 8_192 : 4_096,
        max_tokens_mode: "auto" as const,
        frequency_penalty: null,
        presence_penalty: null,
      }
    : {
        thinking: "disabled" as const,
        reasoning_effort: null,
        temperature: null,
        top_p: null,
        max_tokens: 512,
        max_tokens_mode: "auto" as const,
        frequency_penalty: null,
        presence_penalty: null,
      };
  const reasoningPolicy: ModelReasoningPolicy = usesHighMaxPolicy
    ? {
        thinking_options: ["enabled", "disabled"],
        default_thinking: "enabled",
        thinking_locked: false,
        reasoning_effort_options: ["high", "max"],
        default_reasoning_effort: "high",
        max_tokens_by_effort: { high: 8_192, max: 16_384 },
        default_max_tokens: 8_192,
        disabled_max_tokens: 512,
        sampling_parameters_allowed_when_thinking:
          !modelId.includes("deepseek-v4"),
      }
    : usesDoubaoPolicy
      ? {
          thinking_options: ["enabled", "disabled"],
          default_thinking: "enabled",
          thinking_locked: false,
          reasoning_effort_options: ["low", "medium", "high"],
          default_reasoning_effort: "low",
          max_tokens_by_effort: {
            low: 4_096,
            medium: 8_192,
            high: 16_384,
          },
          default_max_tokens: 4_096,
          disabled_max_tokens: 512,
          sampling_parameters_allowed_when_thinking: true,
        }
      : usesCodePreviewPolicy
        ? {
            thinking_options: ["disabled"],
            default_thinking: "disabled",
            thinking_locked: true,
            reasoning_effort_options: [],
            default_reasoning_effort: null,
            max_tokens_by_effort: {},
            default_max_tokens: 512,
            disabled_max_tokens: 512,
            sampling_parameters_allowed_when_thinking: true,
          }
        : {
            thinking_options: ["enabled", "disabled"],
            default_thinking: "enabled",
            thinking_locked: false,
            reasoning_effort_options: ["high", "max"],
            default_reasoning_effort: "high",
            max_tokens_by_effort: { high: 8_192, max: 16_384 },
            default_max_tokens: 8_192,
            disabled_max_tokens: 512,
            sampling_parameters_allowed_when_thinking: true,
          };
  return {
    provider,
    model_id: modelId,
    source_model_id: modelId,
    display_name: modelId,
    description:
      provider === "deepseek"
        ? "DeepSeek 官方 API 模型，支持思考模式与推理强度控制。"
        : provider === "ark"
          ? "火山方舟标准推理接入点。"
          : "Agent Plan 套餐内可用模型。",
    available: true,
    enabled,
    is_default: isDefault,
    selected_by_source: isDefault,
    supports_thinking: supportsThinking,
    assigned_profile_count: enabled ? 3 : 0,
    parameters,
    reasoning_policy: reasoningPolicy,
    max_output_tokens_limit:
      (provider === "agent_plan" || provider === "ark") &&
      modelId.includes("glm-5-2")
        ? 131072
        : 384000,
    docs_url:
      provider === "deepseek"
        ? "https://api-docs.deepseek.com/zh-cn/guides/thinking_mode"
        : "https://api.volcengine.com/api-docs/view?action=ChatCompletions&serviceCode=ark&version=2024-01-01",
    updated_at: "2026-07-15T12:00:00+08:00",
  };
}
