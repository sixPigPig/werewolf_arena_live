import type { LiveGameEvent } from "../types";

const HIDDEN_TIMELINE_EVENT_TYPES = new Set([
  "model_response_delta",
  "model_thinking_tick",
]);

function titleForEvent(event: LiveGameEvent) {
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
};

export function LiveEventTimeline({
  events,
  currentEventId = null,
}: LiveEventTimelineProps) {
  const visibleEvents = events.filter(
    (event) => !HIDDEN_TIMELINE_EVENT_TYPES.has(event.type),
  );

  if (visibleEvents.length === 0) {
    return <p className="p-4 text-sm text-slate-600">等待实时事件...</p>;
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
                {titleForEvent(event)}
              </p>
              <p className="text-xs text-slate-500">
                {event.round ? `第 ${event.round} 轮` : event.type}
              </p>
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
