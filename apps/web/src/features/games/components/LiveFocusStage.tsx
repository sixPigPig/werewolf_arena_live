import { Badge, Card } from "@radix-ui/themes";

import type { LiveGameEvent } from "../types";
import type { LivePlayer } from "../liveSpectator";

type LiveFocusStageProps = {
  player: LivePlayer | null;
  currentRound: number | null;
  currentPhase: string | null;
  latestEvent: LiveGameEvent | null;
};

const STATUS_LABELS: Record<LivePlayer["status"], string> = {
  waiting: "等待中",
  thinking: "正在思考",
  requesting: "正在请求模型",
  streaming: "输出中",
  responded: "模型已返回",
  acted: "行动已解析",
  out: "已出局",
};

export function LiveFocusStage({
  player,
  currentRound,
  currentPhase,
  latestEvent,
}: LiveFocusStageProps) {
  if (!player) {
    return (
      <Card asChild size="3">
      <section className="min-h-80">
        <p className="text-sm text-slate-600">等待玩家行动...</p>
      </section>
      </Card>
    );
  }

  const detail = player.lastDetail || detailForEvent(latestEvent);

  return (
    <Card asChild size="1">
      <section className="min-h-80">
      <div className="border-b border-slate-200 px-5 py-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="text-xs font-medium text-slate-500">当前聚焦</p>
            <h2 className="mt-1 text-xl font-semibold text-slate-950">
              {player.name}
            </h2>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <Badge color="gray" variant="surface">
              {player.role}
            </Badge>
            <Badge color="gray" variant="surface">
              {STATUS_LABELS[player.status]}
            </Badge>
            {!player.isAlive ? (
              <Badge color="red" variant="surface">
                出局
              </Badge>
            ) : null}
          </div>
        </div>
      </div>

      <div className="space-y-4 px-5 py-5">
        <div className="flex flex-wrap gap-2 text-sm text-slate-600">
          <span>{currentRound ? `第 ${currentRound} 轮` : "等待回合"}</span>
          <span>{currentPhase ? `阶段：${currentPhase}` : "阶段未开始"}</span>
        </div>

        <div>
          <p className="text-xs font-medium text-slate-500">最近行动</p>
          <p className="mt-1 text-base font-medium text-slate-950">
            {player.lastAction || latestEvent?.type || "等待行动"}
          </p>
        </div>

        {detail ? (
          <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-md bg-slate-100 p-4 text-sm leading-6 text-slate-800">
            {detail}
          </pre>
        ) : (
          <p className="rounded-md bg-slate-50 p-4 text-sm text-slate-600">
            正在等待这个玩家的下一条可展示内容。
          </p>
        )}
      </div>
      </section>
    </Card>
  );
}

function detailForEvent(event: LiveGameEvent | null): string {
  if (!event || !event.payload || typeof event.payload !== "object") {
    return "";
  }
  const payload = event.payload;
  if (typeof payload.visible_text === "string") {
    return payload.visible_text;
  }
  if (typeof payload.message === "string") {
    return payload.message;
  }
  if (typeof payload.choice === "string") {
    return payload.choice;
  }
  const visibleResult = payload.visible_result;
  if (isRecord(visibleResult)) {
    if (typeof visibleResult.say === "string") {
      return visibleResult.say;
    }
    if (typeof visibleResult.summary === "string") {
      return visibleResult.summary;
    }
  }
  return "";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
