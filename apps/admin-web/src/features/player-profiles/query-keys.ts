import type { PlayerProfileListParams } from "@/features/player-profiles/types";

export const playerProfileKeys = {
  all: ["admin", "player-profiles"] as const,
  lists: () => [...playerProfileKeys.all, "list"] as const,
  list: (params: PlayerProfileListParams) =>
    [...playerProfileKeys.lists(), params] as const,
  details: () => [...playerProfileKeys.all, "detail"] as const,
  detail: (profileId: string) =>
    [...playerProfileKeys.details(), profileId] as const,
  options: () => [...playerProfileKeys.all, "options"] as const,
  ttsSpeakers: () => [...playerProfileKeys.all, "tts-speakers"] as const,
};
