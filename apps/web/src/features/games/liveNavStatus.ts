import type { ConnectionState } from "./hooks/useGameRunEvents";
import type { LiveDirectorSpeed } from "./hooks/useLiveDirector";
import type { GameRunStatus } from "./types";

export type LiveNavStatusKind =
  | "connecting"
  | "live"
  | "catchingUp"
  | "paused"
  | "ended"
  | "interrupted";

export type LiveNavStatusTone =
  | "neutral"
  | "good"
  | "warning"
  | "danger"
  | "done";

export type LiveNavStatus = {
  kind: LiveNavStatusKind;
  label: string;
  detailItems: string[];
  tone: LiveNavStatusTone;
};

export type LiveNavStatusInput = {
  connectionState: ConnectionState | (string & {});
  runStatus: GameRunStatus | (string & {});
  isPaused: boolean;
  backlogCount: number;
  speed: LiveDirectorSpeed;
  hasCompletedTerminalEvent?: boolean;
  hasFailedTerminalEvent?: boolean;
};

const connectionLabels = {
  idle: "未连接",
  connecting: "连接中",
  open: "已连接",
  closed: "已关闭",
  error: "连接异常",
} satisfies Record<ConnectionState, string>;

const runStatusLabels = {
  queued: "排队中",
  running: "进行中",
  completed: "已完成",
  failed: "失败",
} satisfies Record<GameRunStatus, string>;

export function deriveLiveNavStatus(input: LiveNavStatusInput): LiveNavStatus {
  const backlogCount = Math.max(0, input.backlogCount);
  const connectionLabel = labelForConnectionState(input.connectionState);
  const runStatusLabel = labelForRunStatus(input.runStatus);
  const endedLabel =
    input.runStatus === "completed" || input.hasCompletedTerminalEvent
      ? "已完成"
      : runStatusLabel;
  const interruptedLabel =
    input.runStatus === "failed" || input.hasFailedTerminalEvent
      ? "失败"
      : connectionLabel;
  const isEnded =
    input.runStatus === "completed" || input.hasCompletedTerminalEvent === true;
  const isInterrupted =
    input.runStatus === "failed" ||
    input.hasFailedTerminalEvent === true ||
    (!isEnded &&
      (input.connectionState === "error" || input.connectionState === "closed"));

  if (isInterrupted) {
    return {
      detailItems: [interruptedLabel],
      kind: "interrupted",
      label: "异常中断",
      tone: "danger",
    };
  }

  if (isEnded) {
    return {
      detailItems: [endedLabel],
      kind: "ended",
      label: "已结束",
      tone: "done",
    };
  }

  if (input.isPaused) {
    return {
      detailItems: backlogCount > 0 ? [`落后 ${backlogCount} 条`] : [],
      kind: "paused",
      label: "已暂停",
      tone: "warning",
    };
  }

  if (
    input.connectionState === "idle" ||
    input.connectionState === "connecting" ||
    input.runStatus === "queued"
  ) {
    return {
      detailItems: [],
      kind: "connecting",
      label: "连接中",
      tone: "neutral",
    };
  }

  if (backlogCount > 0) {
    return {
      detailItems: [`落后 ${backlogCount} 条`, `${input.speed}x`],
      kind: "catchingUp",
      label: "追播中",
      tone: "warning",
    };
  }

  return {
    detailItems: [`${input.speed}x`],
    kind: "live",
    label: "直播中",
    tone: "good",
  };
}

function labelForConnectionState(
  connectionState: ConnectionState | (string & {}),
) {
  return connectionLabels[connectionState as ConnectionState] ?? connectionState;
}

function labelForRunStatus(runStatus: GameRunStatus | (string & {})) {
  return runStatusLabels[runStatus as GameRunStatus] ?? runStatus;
}
