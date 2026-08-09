export type ModelProvider = "agent_plan" | "ark" | "deepseek";
export type ThinkingMode = "enabled" | "disabled";
export type MaxTokensMode = "auto" | "manual";

export type ModelParameters = {
  thinking: ThinkingMode;
  reasoning_effort: string | null;
  temperature: number | null;
  top_p: number | null;
  max_tokens: number;
  max_tokens_mode: MaxTokensMode;
  frequency_penalty: number | null;
  presence_penalty: number | null;
};

export type ModelReasoningPolicy = {
  thinking_options: ThinkingMode[];
  default_thinking: ThinkingMode;
  thinking_locked: boolean;
  reasoning_effort_options: string[];
  default_reasoning_effort: string | null;
  max_tokens_by_effort: Record<string, number>;
  default_max_tokens: number;
  disabled_max_tokens: number | null;
  sampling_parameters_allowed_when_thinking: boolean;
};

export type AdminModelSource = {
  provider: ModelProvider;
  label: string;
  refresh_mode: "manual" | "automatic";
  status: "ok" | "error";
  model_count: number;
  last_synced_at: string | null;
  docs_url: string;
  error: string | null;
};

export type AdminModel = {
  provider: ModelProvider;
  model_id: string;
  source_model_id: string | null;
  display_name: string;
  description: string | null;
  available: boolean;
  enabled: boolean;
  is_default: boolean;
  selected_by_source: boolean;
  supports_thinking: boolean;
  assigned_profile_count: number;
  parameters: ModelParameters;
  reasoning_policy: ModelReasoningPolicy;
  max_output_tokens_limit: number;
  docs_url: string;
  updated_at: string;
};

export type AdminModelCatalog = {
  generated_at: string;
  sources: AdminModelSource[];
  models: AdminModel[];
};

export type ModelConfigurationInput = {
  enabled: boolean;
  is_default: boolean;
  parameters: ModelParameters;
};
