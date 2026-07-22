export type JudgeModelProvider = "agent_plan";

export type JudgeModelOption = {
  provider: JudgeModelProvider;
  model_id: string;
  label: string;
};

export type JudgeSpeakerOption = {
  voice_type: string;
  name: string;
};

export type AdminJudgeConfiguration = {
  model_provider: JudgeModelProvider;
  model_id: string;
  tts_speaker: string;
  version: number;
  source: "database" | "environment";
  updated_at: string | null;
  models: JudgeModelOption[];
  speakers: JudgeSpeakerOption[];
  speaker_catalog_available: boolean;
  tts_resource_id: string;
};

export type UpdateJudgeConfigurationRequest = {
  model_provider: JudgeModelProvider;
  model_id: string;
  tts_speaker: string;
  expected_version: number;
};
