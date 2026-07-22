import type { AdminJudgeConfiguration } from "@/features/judge-configuration/types";

export const previewJudgeConfiguration: AdminJudgeConfiguration = {
  model_provider: "agent_plan",
  model_id: "doubao-seed-2-0-lite-260215",
  tts_speaker: "zh_female_vv_uranus_bigtts",
  version: 1,
  source: "database",
  updated_at: "2026-07-23T08:00:00Z",
  models: [
    {
      provider: "agent_plan",
      model_id: "doubao-seed-2-0-lite-260215",
      label: "Doubao Seed 2.0 Lite",
    },
    {
      provider: "agent_plan",
      model_id: "glm-5-2-260617",
      label: "GLM 5.2",
    },
  ],
  speakers: [
    { voice_type: "zh_female_vv_uranus_bigtts", name: "Vivi 2.0" },
    {
      voice_type: "zh_female_gaolengyujie_uranus_bigtts",
      name: "高冷御姐 2.0",
    },
    { voice_type: "zh_male_yangguangqingnian_uranus_bigtts", name: "阳光青年 2.0" },
  ],
  speaker_catalog_available: true,
  tts_resource_id: "seed-tts-2.0",
};
