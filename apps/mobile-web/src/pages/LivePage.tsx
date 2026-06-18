import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { getGameRun } from "../api/gamesApi";
import { MobileButton } from "../components/MobileButton";
import { StatusBanner } from "../components/StatusBanner";
import { useMobileGameRunEvents } from "../features/live/useMobileGameRunEvents";

function connectionLabel(state: string) {
  if (state === "open") {
    return "连接正常";
  }

  if (state === "connecting") {
    return "正在连接";
  }

  if (state === "reconnecting") {
    return "正在重连";
  }

  if (state === "error") {
    return "连接中断";
  }

  return "连接已关闭";
}

function payloadSummary(payload: Record<string, unknown> | undefined) {
  if (!payload) {
    return "后台正在准备对局。";
  }

  return JSON.stringify(payload);
}

export function LivePage() {
  const { runId } = useParams();
  const runQuery = useQuery({
    enabled: Boolean(runId),
    queryFn: () => getGameRun(runId!),
    queryKey: ["mobile-game-run", runId],
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 15000;
    },
  });
  const run = runQuery.data;
  const streamRunId = run ? runId : undefined;
  const { connectionState, events, latestEvent } =
    useMobileGameRunEvents(streamRunId);
  const isTerminal = run?.status === "completed" || run?.status === "failed";

  return (
    <section className="mobile-page-section">
      <header className="mobile-live-header">
        <div>
          <p className="mobile-kicker">{run?.rule_set?.name ?? "实时对局"}</p>
          <h2>实时舞台</h2>
        </div>
        <span className="mobile-live-status">
          {connectionLabel(connectionState)}
        </span>
      </header>

      {runQuery.isError ? (
        <StatusBanner title="无法读取实时对局" tone="error">
          <p>这个 run 不存在或后端暂时不可用。</p>
        </StatusBanner>
      ) : null}

      <section className="mobile-stage-card">
        <p className="mobile-kicker">当前事件</p>
        <strong>{latestEvent?.type ?? "等待事件"}</strong>
        <p>{payloadSummary(latestEvent?.payload)}</p>
      </section>

      <section className="mobile-card">
        <h2>玩家快捷席位</h2>
        <div className="mobile-seat-strip" aria-label="玩家快捷席位">
          {Array.from({ length: run?.rule_set?.player_count ?? 12 }, (_, index) => (
            <span key={index + 1}>{index + 1}</span>
          ))}
        </div>
      </section>

      <section className="mobile-card">
        <h2>关键事件</h2>
        {events.slice(-3).map((event) => (
          <p key={event.id}>
            {event.id}. {event.type}
          </p>
        ))}
        {events.length === 0 ? <p>还没有收到事件。</p> : null}
      </section>

      {isTerminal && run ? (
        <Link className="mobile-link-button" to={`/playback/${run.session_id}`}>
          查看复盘
        </Link>
      ) : (
        <MobileButton
          onClick={() => {
            window.location.reload();
          }}
        >
          重连
        </MobileButton>
      )}
    </section>
  );
}
