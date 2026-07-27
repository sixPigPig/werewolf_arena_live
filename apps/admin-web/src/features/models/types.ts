export type ModelProvider = "agent_plan" | "deepseek";
export type ThinkingMode = "default" | "enabled" | "disabled";

export type ModelParameters = {
  thinking: ThinkingMode;
  reasoning_effort: string | null;
  temperature: number | null;
  top_p: number | null;
  max_tokens: number;
  frequency_penalty: number | null;
  presence_penalty: number | null;
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
  reasoning_effort_options: string[];
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
