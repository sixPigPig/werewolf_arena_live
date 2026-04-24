import type { LiveGameEvent } from "../types";

function titleForEvent(event: LiveGameEvent) {
  if (event.type === "action_requested" && event.actor && event.action) {
    return `${event.actor} 正在 ${event.action}`;
  }
  if (event.type === "model_response_received") {
    return "模型返回原文";
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

function detailForEvent(event: LiveGameEvent) {
  const raw = event.payload.raw_response;
  if (typeof raw === "string") {
    return raw;
  }
  const choice = event.payload.choice;
  if (typeof choice === "string") {
    return choice;
  }
  const winner = event.payload.winner;
  if (typeof winner === "string") {
    return winner;
  }
  return "";
}

export function LiveEventTimeline({ events }: { events: LiveGameEvent[] }) {
  if (events.length === 0) {
    return <p className="p-4 text-sm text-slate-600">等待实时事件...</p>;
  }

  return (
    <ol className="divide-y divide-slate-200">
      {events.map((event) => (
        <li className="px-4 py-3" key={event.id}>
          <div className="flex items-center justify-between gap-3">
            <p className="text-sm font-medium text-slate-950">
              {titleForEvent(event)}
            </p>
            <p className="text-xs text-slate-500">
              {event.round ? `第 ${event.round} 轮` : event.type}
            </p>
          </div>
          {detailForEvent(event) ? (
            <pre className="mt-2 overflow-auto rounded-md bg-slate-100 p-2 text-xs text-slate-700">
              {detailForEvent(event)}
            </pre>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
