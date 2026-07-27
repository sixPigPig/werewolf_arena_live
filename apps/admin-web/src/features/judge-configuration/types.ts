export type JudgeVoiceMode = "fixed" | "random";

export type JudgeSpeakerOption = {
  voice_type: string;
  name: string;
};

export type AdminJudgeConfiguration = {
  voice_mode: JudgeVoiceMode;
  tts_speaker: string;
  random_tts_speakers: string[];
  version: number;
  source: "database" | "environment";
  updated_at: string | null;
  speakers: JudgeSpeakerOption[];
  speaker_catalog_available: boolean;
  tts_resource_id: string;
};

export type UpdateJudgeConfigurationRequest = {
  voice_mode: JudgeVoiceMode;
  tts_speaker: string | null;
  random_tts_speakers: string[];
  expected_version: number;
};
