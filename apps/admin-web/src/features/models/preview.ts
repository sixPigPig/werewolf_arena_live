import type { AdminModelCatalog } from "@/features/models/types";

export const previewModelCatalog: AdminModelCatalog = {
  generated_at: "2026-07-15T12:00:00+08:00",
  sources: [
    {
      provider: "agent_plan",
      label: "火山方舟 Agent Plan",
      refresh_mode: "manual",
      status: "ok",
      model_count: 2,
      last_synced_at: "2026-07-15T11:56:00+08:00",
      docs_url: "https://api.volcengine.com/api-docs/view?action=ChatCompletions&serviceCode=ark&version=2024-01-01",
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
    previewModel("agent_plan", "doubao-seed-2-0-lite-260215", true, true),
    previewModel("agent_plan", "glm-5-2-260617", true, false),
    previewModel("deepseek", "deepseek-v4-flash", true, false),
    previewModel("deepseek", "deepseek-v4-pro", false, false),
  ],
};

function previewModel(
  provider: "agent_plan" | "deepseek",
  modelId: string,
  enabled: boolean,
  isDefault: boolean,
) {
  return {
    provider,
    model_id: modelId,
    source_model_id: modelId,
    display_name: modelId,
    description:
      provider === "deepseek"
        ? "DeepSeek 官方 API 模型，支持思考模式与推理强度控制。"
        : "Agent Plan 套餐内可用模型。",
    available: true,
    enabled,
    is_default: isDefault,
    selected_by_source: isDefault,
    supports_thinking: true,
    assigned_profile_count: enabled ? 3 : 0,
    parameters: {
      thinking: "default" as const,
      reasoning_effort: null,
      temperature: null,
      top_p: null,
      max_tokens: 2048,
      frequency_penalty: null,
      presence_penalty: null,
    },
    reasoning_effort_options:
      provider === "deepseek"
        ? ["high", "max"]
        : ["minimal", "low", "medium", "high"],
    max_output_tokens_limit:
      provider === "agent_plan" && modelId.startsWith("glm-5-2-")
        ? 131072
        : 384000,
    docs_url:
      provider === "deepseek"
        ? "https://api-docs.deepseek.com/zh-cn/guides/thinking_mode"
        : "https://api.volcengine.com/api-docs/view?action=ChatCompletions&serviceCode=ark&version=2024-01-01",
    updated_at: "2026-07-15T12:00:00+08:00",
  };
}
