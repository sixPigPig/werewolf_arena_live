import type { AdminJudgeVoiceListParams } from "@/features/voice-assets/types";

export const adminJudgeVoiceKeys = {
  all: ["admin", "judge-voice-lines"] as const,
  list: (params: AdminJudgeVoiceListParams) =>
    [...adminJudgeVoiceKeys.all, "list", params] as const,
};
