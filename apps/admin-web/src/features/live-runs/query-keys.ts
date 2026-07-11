import type { AdminLiveRunListParams } from "@/features/live-runs/types";

export const adminLiveRunKeys = {
  all: ["admin", "live-runs"] as const,
  lists: () => [...adminLiveRunKeys.all, "list"] as const,
  list: (params: AdminLiveRunListParams) =>
    [...adminLiveRunKeys.lists(), params] as const,
  details: () => [...adminLiveRunKeys.all, "detail"] as const,
  detail: (runId: string) =>
    [...adminLiveRunKeys.details(), runId] as const,
  debug: (runId: string) =>
    [...adminLiveRunKeys.detail(runId), "debug"] as const,
};
