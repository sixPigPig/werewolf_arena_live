import type { AdminGameListParams } from "@/features/game-records/types";

export const adminGameKeys = {
  all: ["admin", "games"] as const,
  lists: () => [...adminGameKeys.all, "list"] as const,
  list: (params: AdminGameListParams) =>
    [...adminGameKeys.lists(), params] as const,
  details: () => [...adminGameKeys.all, "detail"] as const,
  detail: (sessionId: string) =>
    [...adminGameKeys.details(), sessionId] as const,
  debug: (sessionId: string) =>
    [...adminGameKeys.detail(sessionId), "debug"] as const,
  modelRequests: (sessionId: string) =>
    [...adminGameKeys.detail(sessionId), "model-requests"] as const,
  modelRequest: (sessionId: string, requestId: string) =>
    [...adminGameKeys.modelRequests(sessionId), requestId] as const,
  qualityIssues: (sessionId: string) =>
    [...adminGameKeys.detail(sessionId), "quality-issues"] as const,
};
