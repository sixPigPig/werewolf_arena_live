import { Button, Card } from "@radix-ui/themes";
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
      <Card asChild size="2" variant="surface">
      <p className="text-sm text-slate-600">
        还没有可复盘的对局
      </p>
      </Card>
    );
  }

  return (
    <Card asChild size="1">
      <div className="divide-y divide-slate-200">
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
            <Button
              className="shrink-0"
              disabled={resumingSessionId === session.session_id}
              highContrast
              loading={resumingSessionId === session.session_id}
              onClick={() => onResumeSession(session.session_id)}
              type="button"
            >
              继续对局
            </Button>
          ) : null}
        </div>
      ))}
      </div>
    </Card>
  );
}
