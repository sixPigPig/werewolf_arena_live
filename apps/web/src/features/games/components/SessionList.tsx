import { Button, Card } from "../../../components/ui";
import { Link } from "react-router-dom";

import type { GameSessionSummary } from "../types";

type SessionListProps = {
  sessions: GameSessionSummary[];
  onResumeSession?: (sessionId: string) => void;
  resumingSessionId?: string | null;
  variant?: "default" | "ornate";
};

function formatStatus(status: GameSessionSummary["status"]) {
  return status === "complete" ? "已完成" : "部分日志";
}

function factionTone(winner: string | null) {
  const normalizedWinner = winner?.trim() ?? "";

  if (normalizedWinner.includes("狼")) {
    return "werewolf";
  }
  if (normalizedWinner.includes("好人")) {
    return "villager";
  }
  return "neutral";
}

function FactionBadge({ winner }: { winner: string | null }) {
  const tone = factionTone(winner);
  const label = winner?.trim() ? winner : "未决出";
  const mark = tone === "werewolf" ? "狼" : tone === "villager" ? "民" : "?";

  return (
    <span className={`history-faction-badge history-faction-${tone}`}>
      <span aria-hidden="true" className="history-faction-mark">
        {mark}
      </span>
      {label}
    </span>
  );
}

function ScrollMedallion({ active }: { active: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={[
        "history-scroll-medallion",
        active ? "history-scroll-medallion-active" : "",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <span className="history-scroll-sheet">
        <span />
        <span />
        <span />
      </span>
    </span>
  );
}

export function SessionList({
  sessions,
  onResumeSession,
  resumingSessionId,
  variant = "default",
}: SessionListProps) {
  if (sessions.length === 0) {
    if (variant === "ornate") {
      return (
        <div
          className="games-sessions-module history-empty-state glass-panel"
          data-testid="games-sessions-module"
        >
          <ScrollMedallion active />
          <div className="min-w-0">
            <p className="history-empty-title">还没有可复盘的对局</p>
            <p className="history-empty-copy">等待第一场月下审判落幕</p>
          </div>
        </div>
      );
    }

    return (
      <Card asChild size="2" variant="surface">
        <p
          className="games-sessions-module text-sm text-slate-600"
          data-testid="games-sessions-module"
        >
          还没有可复盘的对局
        </p>
      </Card>
    );
  }

  if (variant === "ornate") {
    return (
      <div
        className="games-sessions-module history-session-list glass-panel"
        data-testid="games-sessions-module"
      >
        {sessions.map((session) => {
          const isResumable = Boolean(session.resumable && onResumeSession);

          return (
            <article
              className={[
                "history-session-row",
                isResumable ? "history-session-row-resumable" : "",
              ]
                .filter(Boolean)
                .join(" ")}
              key={session.session_id}
            >
              <ScrollMedallion active={isResumable} />
              <Link
                aria-label={`查看对局 ${session.session_id}`}
                className="history-session-link"
                to={`/games/${session.session_id}`}
              >
                <p className="history-session-id">{session.session_id}</p>
                <p className="history-session-meta">
                  <span
                    aria-hidden="true"
                    className={`history-status-dot history-status-${session.status}`}
                  />
                  <span>{formatStatus(session.status)}</span>
                  <span aria-hidden="true" className="history-meta-divider">
                    |
                  </span>
                  <span>{session.round_count} 轮</span>
                </p>
              </Link>
              <div className="history-session-actions">
                <FactionBadge winner={session.winner} />
                {isResumable ? (
                  <Button
                    className="history-resume-button"
                    color="amber"
                    disabled={resumingSessionId === session.session_id}
                    loading={resumingSessionId === session.session_id}
                    onClick={() => onResumeSession?.(session.session_id)}
                    type="button"
                    variant="surface"
                  >
                    继续对局
                  </Button>
                ) : null}
              </div>
            </article>
          );
        })}
      </div>
    );
  }

  return (
    <Card asChild size="1">
      <div
        className="games-sessions-module divide-y divide-slate-200"
        data-testid="games-sessions-module"
      >
        {sessions.map((session) => (
          <div
            className="flex flex-col gap-3 px-4 py-3 transition sm:flex-row sm:items-center sm:justify-between"
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
