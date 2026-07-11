import type { AdminJudgeVoiceList } from "@/features/voice-assets/types";

export const contractJudgeVoiceList: AdminJudgeVoiceList = {
  audio_format: "mp3",
  sample_rate: 24000,
  storage_mode: "legacy_static_directory",
  coverage: {
    total: 3,
    available: 2,
    missing: 1,
    byte_total: 4096,
  },
  categories: [
    { name: "开局", total: 1, available: 1, missing: 0 },
    { name: "夜晚", total: 2, available: 1, missing: 1 },
  ],
  items: [
    {
      id: "game_intro",
      text: "本局游戏开始，请所有玩家确认自己的身份牌。",
      category: "开局",
      available: true,
      byte_size: 2048,
      template_id: null,
      seat_number: null,
      subtitle_cue_count: 12,
      audio_url: "/api/v1/admin/judge-voice-lines/game_intro/audio",
    },
    {
      id: "speech_prompt_seat_01",
      text: "1号玩家请发言。",
      category: "夜晚",
      available: true,
      byte_size: 2048,
      template_id: "speech_prompt",
      seat_number: 1,
      subtitle_cue_count: 5,
      audio_url:
        "/api/v1/admin/judge-voice-lines/speech_prompt_seat_01/audio",
    },
    {
      id: "night_start",
      text: "夜晚降临，所有玩家请闭眼。",
      category: "夜晚",
      available: false,
      byte_size: null,
      template_id: null,
      seat_number: null,
      subtitle_cue_count: 0,
      audio_url: null,
    },
  ],
  pagination: { page: 1, page_size: 20, total: 3, pages: 1 },
};
