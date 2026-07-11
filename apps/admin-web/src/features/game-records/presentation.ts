import type {
  GameSessionStatus,
  LiveRunStatus,
} from "@/features/game-records/types";

export const GAME_STATUS_LABELS: Record<GameSessionStatus, string> = {
  complete: "已完成",
  partial: "部分记录",
};

export const RUN_STATUS_LABELS: Record<LiveRunStatus, string> = {
  queued: "排队中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  canceled: "已取消",
};

export function formatDateTime(value: string | null) {
  if (!value) {
    return "—";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function displayValue(value: string | null | undefined) {
  return value?.trim() || "—";
}
