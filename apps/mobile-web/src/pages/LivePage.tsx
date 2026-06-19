import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  deriveGodViewState,
  deriveLiveNavStatus,
  deriveLiveSpectatorState,
  getGameRun,
  resumeGameRun,
  useGameRunEvents,
  useLiveDirector,
  type GameRun,
  type LiveGameEvent,
} from "@werewolf-arena/game-client";

const EMPTY_EVENTS: LiveGameEvent[] = [];

export function LivePage() {
  const { gameId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { connectionState, events, latestEvent } = useGameRunEvents(gameId);
  const runQuery = useQuery({
    queryKey: ["game-run", gameId],
    queryFn: () => getGameRun(gameId ?? ""),
    enabled: Boolean(gameId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 15000;
    },
  });
  const resumeMutation = useMutation({
    mutationFn: (sessionId: string) => resumeGameRun(sessionId),
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: ["games"] });
      void queryClient.invalidateQueries({ queryKey: ["game-run", gameId] });
      navigate(`/games/${run.run_id}/live`);
    },
  });

  const run = runQuery.data;
  const terminalEvent = events.find(isTerminalEvent);
  const director = useLiveDirector(events, {
    resetKey: gameId,
    startAtLatestTerminal: isTerminalRunStatus(run?.status),
  });
  const stageEvents = useMemo(() => {
    const currentEventId = director.currentEventId;
    if (currentEventId === null) {
      return EMPTY_EVENTS;
    }

    return events.filter((event) => event.id <= currentEventId);
  }, [director.currentEventId, events]);
  const currentEvent =
    stageEvents.find((event) => event.id === director.currentEventId) ??
    latestEvent;
  const spectatorState = useMemo(
    () => deriveLiveSpectatorState(stageEvents),
    [stageEvents],
  );
  const godViewState = useMemo(
    () =>
      deriveGodViewState(
        stageEvents,
        spectatorState,
        run?.rule_set?.name ?? "实时对局",
        { sheriffEnabled: run?.rule_set?.sheriff_enabled },
      ),
    [
      run?.rule_set?.name,
      run?.rule_set?.sheriff_enabled,
      spectatorState,
      stageEvents,
    ],
  );
  const liveStatus = deriveLiveNavStatus({
    backlogCount: director.backlogCount,
    connectionState,
    hasCompletedTerminalEvent: terminalEvent?.type === "game_completed",
    hasFailedTerminalEvent: terminalEvent?.type === "game_failed",
    isPaused: director.isPaused,
    runStatus: run?.status ?? "queued",
    speed: director.speed,
  });
  const canResumeRun =
    run?.status === "failed" || terminalEvent?.type === "game_failed";

  return (
    <main className="mobile-page mobile-live-page">
      <header className="mobile-page-section">
        <h1>实时观战</h1>
        <p>{run?.rule_set?.name ?? "正在读取规则"}</p>
      </header>

      {runQuery.isPending ? <p>正在读取实时对局...</p> : null}
      {runQuery.isError ? (
        <p className="mobile-status-banner" role="alert">
          无法读取实时对局
        </p>
      ) : null}
      {resumeMutation.isError ? (
        <p className="mobile-status-banner" role="alert">
          无法继续对局
        </p>
      ) : null}

      {run ? (
        <>
          <LiveSummary
            connectionState={connectionState}
            liveStatusLabel={liveStatus.label}
            run={run}
          />
          <CurrentEventPanel
            currentEvent={currentEvent}
            currentPhase={spectatorState.currentPhase ?? godViewState.phaseLabel}
            currentRound={spectatorState.currentRound}
          />
          {godViewState.players.length > 0 ? (
            <section aria-label="玩家席位" className="mobile-live-player-grid">
              {godViewState.players.map((player) => (
                <article className="mobile-live-player" key={player.name}>
                  <span>{player.seatNumber}</span>
                  <strong>{player.name}</strong>
                  <em>{player.role || "未知身份"}</em>
                  <small>{player.stageStatus.label}</small>
                </article>
              ))}
            </section>
          ) : null}
          <div className="mobile-live-action-bar" aria-label="实时观战操作">
            <button
              className="mobile-button"
              onClick={director.togglePaused}
              type="button"
            >
              {director.isPaused ? "继续" : "暂停"}
            </button>
            <button
              className="mobile-button"
              onClick={() => director.setSpeed(director.speed === 1 ? 2 : 1)}
              type="button"
            >
              {director.speed === 1 ? "1x" : "2x"}
            </button>
            <button
              className="mobile-button"
              onClick={director.catchUpToLatest}
              type="button"
            >
              追到最新
            </button>
            {canResumeRun ? (
              <button
                className="mobile-button mobile-button-primary"
                disabled={resumeMutation.isPending}
                onClick={() => resumeMutation.mutate(run.session_id)}
                type="button"
              >
                {resumeMutation.isPending ? "继续中" : "继续对局"}
              </button>
            ) : null}
            {isTerminalRunStatus(run.status) || terminalEvent ? (
              <Link
                className="mobile-button mobile-live-link"
                to={`/games/${run.session_id}/replay`}
              >
                查看复盘
              </Link>
            ) : null}
          </div>
        </>
      ) : null}
    </main>
  );
}

type LiveSummaryProps = {
  connectionState: string;
  liveStatusLabel: string;
  run: GameRun;
};

function LiveSummary({ connectionState, liveStatusLabel, run }: LiveSummaryProps) {
  return (
    <section aria-label="实时概要" className="mobile-live-summary">
      <dl className="mobile-session-meta">
        <div>
          <dt>规则</dt>
          <dd>{run.rule_set?.name ?? "未知规则"}</dd>
        </div>
        <div>
          <dt>会话</dt>
          <dd>{run.session_id}</dd>
        </div>
        <div>
          <dt>连接</dt>
          <dd>{connectionLabel(connectionState)}</dd>
        </div>
        <div>
          <dt>状态</dt>
          <dd>{liveStatusLabel}</dd>
        </div>
        <div>
          <dt>事件</dt>
          <dd>{run.event_count}</dd>
        </div>
      </dl>
    </section>
  );
}

type CurrentEventPanelProps = {
  currentEvent: LiveGameEvent | null;
  currentPhase: string | null;
  currentRound: number | null;
};

function CurrentEventPanel({
  currentEvent,
  currentPhase,
  currentRound,
}: CurrentEventPanelProps) {
  return (
    <section aria-label="当前事件" className="mobile-live-event">
      <span>当前事件</span>
      <strong>{currentEvent?.type ?? "等待事件"}</strong>
      <dl className="mobile-session-meta">
        <div>
          <dt>轮次</dt>
          <dd>{typeof currentRound === "number" ? `第 ${currentRound} 轮` : "未开始"}</dd>
        </div>
        <div>
          <dt>阶段</dt>
          <dd>{currentPhase || "等待阶段"}</dd>
        </div>
      </dl>
    </section>
  );
}

function connectionLabel(state: string) {
  if (state === "open") return "连接正常";
  if (state === "connecting") return "正在连接";
  if (state === "error") return "连接中断";
  if (state === "closed") return "连接已关闭";
  return "等待连接";
}

function isTerminalEvent(event: LiveGameEvent) {
  return event.type === "game_completed" || event.type === "game_failed";
}

function isTerminalRunStatus(status: string | undefined) {
  return status === "completed" || status === "failed";
}
