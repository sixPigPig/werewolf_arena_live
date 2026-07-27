import type { AdminJudgeConfiguration } from "@/features/judge-configuration/types";

export const previewJudgeConfiguration: AdminJudgeConfiguration = {
  voice_mode: "fixed",
  tts_speaker: "zh_female_vv_uranus_bigtts",
  random_tts_speakers: [],
  version: 1,
  source: "database",
  updated_at: "2026-07-23T08:00:00Z",
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
