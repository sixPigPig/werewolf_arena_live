import type { LiveGameEvent } from "../types";
import { liveEventTitle } from "../liveLabels";

const HIDDEN_TIMELINE_EVENT_TYPES = new Set([
  "model_response_delta",
  "model_thinking_tick",
]);

const STORY_TIMELINE_EVENT_TYPES = new Set([
  "run_started",
  "game_started",
  "round_started",
  "phase_started",
  "action_requested",
  "action_parsed",
  "state_updated",
  "game_completed",
  "game_failed",
]);

function rawTitleForEvent(event: LiveGameEvent) {
  if (event.type === "action_requested" && event.actor && event.action) {
    return `${event.actor} 正在 ${event.action}`;
  }
  if (event.type === "model_response_received") {
    return "模型返回已接收";
  }
  if (event.type === "action_parsed") {
    return "行动解析完成";
  }
  if (event.type === "game_completed") {
    return "对局完成";
  }
  if (event.type === "game_failed") {
    return "对局失败";
  }
  return event.type;
}

function payloadForEvent(event: LiveGameEvent) {
  return event.payload &&
    typeof event.payload === "object" &&
    !Array.isArray(event.payload)
    ? event.payload
    : {};
}

function detailForEvent(event: LiveGameEvent) {
  const payload = payloadForEvent(event);
  const visibleText = payload.visible_text;
  if (typeof visibleText === "string") {
    return visibleText;
  }
  const message = payload.message;
  if (typeof message === "string") {
    return message;
  }
  const choice = payload.choice;
  if (typeof choice === "string") {
    return choice;
  }
  const visibleResult = payload.visible_result;
  if (isRecord(visibleResult)) {
    const say = visibleResult.say;
    if (typeof say === "string") {
      return say;
    }
    const summary = visibleResult.summary;
    if (typeof summary === "string") {
      return summary;
    }
  }
  const winner = payload.winner;
  if (typeof winner === "string") {
    return winner;
  }
  const error = payload.error;
  if (typeof error === "string") {
    return error;
  }
  return "";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

type LiveEventTimelineProps = {
  events: LiveGameEvent[];
  currentEventId?: number | null;
  variant?: "raw" | "story";
};

export function LiveEventTimeline({
  events,
  currentEventId = null,
  variant = "raw",
}: LiveEventTimelineProps) {
  const visibleEvents = events
    .filter((event) => !HIDDEN_TIMELINE_EVENT_TYPES.has(event.type))
    .filter((event) =>
      variant === "story" ? STORY_TIMELINE_EVENT_TYPES.has(event.type) : true,
    );

  if (visibleEvents.length === 0) {
    return (
      <p className="p-4 text-sm text-slate-600">
        {variant === "story" ? "等待剧情事件..." : "等待实时事件..."}
      </p>
    );
  }

  return (
    <ol className="divide-y divide-slate-200">
      {visibleEvents.map((event) => {
        const detail = detailForEvent(event);
        const isCurrent = event.id === currentEventId;

        return (
          <li
            className={[
              "px-4 py-3",
              isCurrent ? "bg-slate-100 ring-1 ring-inset ring-slate-300" : "",
            ].join(" ")}
            key={event.id}
          >
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-slate-950">
                {variant === "story"
                  ? liveEventTitle(event)
                  : rawTitleForEvent(event)}
              </p>
              <p className="text-xs text-slate-500">{metaForEvent(event, variant)}</p>
            </div>
            {detail ? (
              <pre className="mt-2 overflow-auto rounded-md bg-slate-100 p-2 text-xs text-slate-700">
                {detail}
              </pre>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

function metaForEvent(event: LiveGameEvent, variant: "raw" | "story") {
  if (event.round) {
    return `第 ${event.round} 轮`;
  }
  if (variant === "story") {
    return "流程";
  }
  return event.type;
}
