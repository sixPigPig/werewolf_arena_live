import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { getGamePlayback } from "../api/gamesApi";
import type { LiveGameEvent } from "../api/types";
import { StatusBanner } from "../components/StatusBanner";

function eventDetail(event: LiveGameEvent) {
  const summary = event.payload.summary;
  if (typeof summary === "string" && summary.length > 0) {
    return summary;
  }

  return JSON.stringify(event.payload);
}

export function PlaybackPage() {
  const { sessionId } = useParams();
  const playbackQuery = useQuery({
    enabled: Boolean(sessionId),
    queryFn: () => getGamePlayback(sessionId!),
    queryKey: ["mobile-playback", sessionId],
  });
  const events = playbackQuery.data?.events ?? [];

  return (
    <section className="mobile-page-section">
      <header className="mobile-card">
        <p className="mobile-kicker">复盘</p>
        <h2>{playbackQuery.data?.rule_set?.name ?? sessionId}</h2>
      </header>

      {playbackQuery.isError ? (
        <StatusBanner title="复盘不可用" tone="error">
          <p>无法读取这场对局的复盘。</p>
        </StatusBanner>
      ) : null}

      <section className="mobile-card">
        {playbackQuery.isPending ? <p>正在读取复盘...</p> : null}
        {events.map((event) => (
          <article className="mobile-timeline-item" key={event.id}>
            <strong>{event.type}</strong>
            <p>
              第 {event.round ?? "-"} 轮 · {event.phase ?? "阶段未记录"}
            </p>
            <p>{eventDetail(event)}</p>
          </article>
        ))}
        {!playbackQuery.isPending && events.length === 0 ? (
          <p>这场对局暂无移动端事件。</p>
        ) : null}
      </section>
    </section>
  );
}
