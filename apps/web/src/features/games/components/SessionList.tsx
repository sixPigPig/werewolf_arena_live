import { Link } from "react-router-dom";

import type { GameSessionSummary } from "../types";

type SessionListProps = {
  sessions: GameSessionSummary[];
  onResumeSession?: (sessionId: string) => void;
  resumingSessionId?: string | null;
};

function formatStatus(status: GameSessionSummary["status"]) {
  return status === "complete" ? "已完成" : "部分日志";
}

export function SessionList({
  sessions,
  onResumeSession,
  resumingSessionId,
}: SessionListProps) {
  if (sessions.length === 0) {
    return (
      <p className="rounded border border-dashed border-slate-300 px-4 py-6 text-sm text-slate-600">
        还没有可复盘的对局
      </p>
    );
  }

  return (
    <div className="divide-y divide-slate-200 rounded border border-slate-200 bg-white">
      {sessions.map((session) => (
        <div
          className="flex flex-col gap-3 px-4 py-3 transition hover:bg-slate-50 sm:flex-row sm:items-center sm:justify-between"
          key={session.session_id}
        >
          <Link
            className="min-w-0 flex-1 focus:outline-none focus:ring-2 focus:ring-slate-400"
            to={`/games/${session.session_id}`}
          >
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="font-mono text-sm font-medium text-slate-900">
                  {session.session_id}
                </p>
                <p className="mt-1 text-sm text-slate-600">
                  {formatStatus(session.status)} · {session.round_count} 轮
                </p>
              </div>
              <p className="text-sm font-medium text-slate-800">
                {session.winner ?? "未决出"}
              </p>
            </div>
          </Link>
          {session.resumable && onResumeSession ? (
            <button
              className="h-9 shrink-0 rounded-md bg-slate-950 px-3 text-sm font-medium text-white disabled:bg-slate-400"
              disabled={resumingSessionId === session.session_id}
              onClick={() => onResumeSession(session.session_id)}
              type="button"
            >
              {resumingSessionId === session.session_id ? "继续中..." : "继续对局"}
            </button>
          ) : null}
        </div>
      ))}
    </div>
  );
}
