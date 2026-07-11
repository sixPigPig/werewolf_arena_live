import type {
  AdminLiveRunList,
  AdminLiveRunStatus,
} from "@/features/live-runs/types";

export const LIVE_RUN_STATUS_LABELS: Record<AdminLiveRunStatus, string> = {
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
};

export function formatLiveRunDateTime(value: string | null) {
  if (!value) {
    return "—";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function isActiveLiveRun(status: AdminLiveRunStatus) {
  return status === "queued" || status === "running";
}

export function liveRunListRefreshInterval(
  data: AdminLiveRunList | undefined,
  page = 1,
) {
  if (page !== 1) {
    return false;
  }
  return data?.items.some((item) => isActiveLiveRun(item.status))
    ? 5_000
    : 30_000;
}

export function liveRunDetailRefreshInterval(
  status: AdminLiveRunStatus | undefined,
) {
  return status && isActiveLiveRun(status) ? 5_000 : false;
}
