import { Button, Callout, Text } from "../components/ui";
import { withGlassPanel } from "../components/ui/glass";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { AppTopNav } from "../app/AppTopNav";
import { getGameRun } from "../features/games/api/getGameRun";
import { resumeGameRun } from "../features/games/api/resumeGameRun";
import { LiveDirectorControls } from "../features/games/components/LiveDirectorControls";
import { LiveDirectorStage } from "../features/games/components/LiveDirectorStage";
import { LiveEventTimeline } from "../features/games/components/LiveEventTimeline";
import {
  PlayerRosterPanel,
  type PlayerRosterItem,
} from "../features/games/components/PlayerRosterPanel";
import { LiveStatusStrip } from "../features/games/components/LiveStatusStrip";
import { RuleSetSummary } from "../features/games/components/RuleSetSummary";
import { useGameRunEvents } from "../features/games/hooks/useGameRunEvents";
import { useLiveDirector } from "../features/games/hooks/useLiveDirector";
import {
  deriveLiveSpectatorState,
  type LivePlayerStatus,
} from "../features/games/liveSpectator";
import { LivePageShell } from "./components/LivePageShell";
import { LiveStageModule } from "./components/LiveStageModule";

export function LiveGamePage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { events, connectionState } = useGameRunEvents(runId);
  const [autoFollow, setAutoFollow] = useState(true);
  const [manualFocusName, setManualFocusName] = useState<string | null>(null);
  const [terminalStartByRunId, setTerminalStartByRunId] = useState<
    Record<string, boolean>
  >({});
  const {
    data: run,
    isError,
    isPending,
  } = useQuery({
    queryKey: ["game-run", runId],
    queryFn: () => getGameRun(runId!),
    enabled: Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" ? false : 15000;
    },
  });
  const resumeMutation = useMutation({
    mutationFn: resumeGameRun,
    onSuccess: (newRun) => {
      queryClient.invalidateQueries({ queryKey: ["games"] });
      navigate(`/games/live/${newRun.run_id}`);
    },
  });

  const terminalEvent = events.find(
    (event) => event.type === "game_completed" || event.type === "game_failed",
  );
  const canResumeRun =
    run?.status === "failed" || terminalEvent?.type === "game_failed";
  const spectatorState = useMemo(
    () => deriveLiveSpectatorState(events),
    [events],
  );
  if (run && runId && !(runId in terminalStartByRunId)) {
    setTerminalStartByRunId({
      ...terminalStartByRunId,
      [runId]: isTerminalRunStatus(run.status),
    });
  }

  const shouldStartAtTerminal =
    run && runId
      ? terminalStartByRunId[runId] ?? isTerminalRunStatus(run.status)
      : false;
  const director = useLiveDirector(events, {
    resetKey: runId,
    startAtLatestTerminal: shouldStartAtTerminal,
  });
  const autoFocusName =
    director.currentCue?.actor ?? spectatorState.activePlayerName;
  const focusedPlayerName = autoFollow
    ? autoFocusName
    : manualFocusName ?? autoFocusName;
  const topNavActions = (
    <>
      {run ? (
        <LiveDirectorControls
          backlogCount={director.backlogCount}
          isCatchingUp={director.isCatchingUp}
          isPaused={director.isPaused}
          onCatchUpToLatest={director.catchUpToLatest}
          onSpeedChange={director.setSpeed}
          onTogglePaused={director.togglePaused}
          speed={director.speed}
          variant="nav"
        />
      ) : null}
      {canResumeRun && run ? (
        <Button
          disabled={resumeMutation.isPending}
          highContrast
          loading={resumeMutation.isPending}
          onClick={() => resumeMutation.mutate(run.session_id)}
          size="1"
          type="button"
        >
          继续对局
        </Button>
      ) : null}
      {terminalEvent && run ? (
        <Button asChild color="gray" highContrast size="1" variant="surface">
          <Link to={`/games/${run.session_id}`}>查看完整复盘</Link>
        </Button>
      ) : null}
      <Link
        aria-label="返回大厅"
        className="live-command-exit flex h-10 w-10 items-center justify-center rounded-md border border-slate-500/35 bg-white/5 text-lg text-slate-100 shadow-[inset_0_0_12px_rgba(255,255,255,0.04)] transition hover:border-amber-300/55 hover:bg-amber-300/10 focus:outline-none focus:ring-2 focus:ring-amber-300/70"
        to="/games"
      >
        <span className="sr-only">返回大厅</span>
        <span aria-hidden="true">↪</span>
      </Link>
    </>
  );
  const topNavContext = run ? (
    <div
      className="live-nav-context live-command-context flex min-w-0 flex-1 flex-nowrap items-center gap-x-3 overflow-hidden"
      data-testid="live-nav-context"
    >
      <h1 className="sr-only">实时观战</h1>
      <LiveStatusStrip run={run} connectionState={connectionState} variant="nav" />
      <span
        aria-hidden="true"
        className="h-6 w-px bg-slate-500/45"
        data-testid="live-command-rule-separator"
      />
      <RuleSetSummary ruleSet={run.rule_set} variant="nav" />
      <span
        aria-hidden="true"
        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-slate-500/35 bg-white/5 text-slate-300"
      >
        ⌄
      </span>
    </div>
  ) : null;
  const rosterPlayers = spectatorState.players.map<PlayerRosterItem>(
    (player, index) => {
      const state = liveRosterState(
        player.status,
        player.isAlive,
        player.name === autoFocusName,
      );

      return {
        seatNumber: index + 1,
        name: player.name,
        role: player.role,
        model: player.model,
        state,
        statusLabel: liveRosterStatusLabel(state),
        isFocused: player.name === focusedPlayerName,
      };
    },
  );

  useEffect(() => {
    if (!terminalEvent) {
      return;
    }
    queryClient.invalidateQueries({ queryKey: ["games"] });
    if (runId) {
      queryClient.invalidateQueries({ queryKey: ["game-run", runId] });
    }
  }, [queryClient, runId, terminalEvent]);

  if (isPending) {
    return (
      <>
        <AppTopNav
          actions={topNavActions}
          context={topNavContext}
          layout="command"
          tone="nocturne"
        />
        <main className="min-h-screen px-4 py-8 text-slate-100">
          <div className="mx-auto w-full max-w-none">
            <Text className="text-slate-300" size="2">
              正在读取实时对局...
            </Text>
          </div>
        </main>
      </>
    );
  }

  if (isError || !run) {
    return (
      <>
        <AppTopNav
          actions={topNavActions}
          context={topNavContext}
          layout="command"
          tone="nocturne"
        />
        <main className="min-h-screen px-4 py-8 text-slate-100">
          <div className="mx-auto w-full max-w-none">
            <Callout.Root color="red" size="1" variant="soft">
              <Callout.Text>无法读取实时对局</Callout.Text>
            </Callout.Root>
          </div>
        </main>
      </>
    );
  }

  return (
    <>
      <AppTopNav
        actions={topNavActions}
        context={topNavContext}
        layout="command"
        tone="nocturne"
      />
      <main
        className="live-game-page min-h-screen px-4 py-6 text-slate-100"
        data-testid="live-game-page"
      >
        <LivePageShell>
          {resumeMutation.isError ? (
            <Callout.Root className="mb-3" color="red" size="1" variant="soft">
              <Callout.Text>无法继续对局</Callout.Text>
            </Callout.Root>
          ) : null}
          <LiveStageModule
            roster={
              <PlayerRosterPanel
                onSelectPlayer={(name) => {
                  setAutoFollow(false);
                  setManualFocusName(name);
                }}
                players={rosterPlayers}
              />
            }
            stage={
              <LiveDirectorStage
                activePlayerName={autoFocusName}
                autoFollow={autoFollow}
                backlogCount={director.backlogCount}
                cue={director.currentCue}
                focusedPlayerName={focusedPlayerName}
                isCatchingUp={director.isCatchingUp}
                onAutoFollowChange={(value) => {
                  setAutoFollow(value);
                  if (value) {
                    setManualFocusName(null);
                  }
                }}
                onSelectPlayer={(name) => {
                  setAutoFollow(false);
                  setManualFocusName(name);
                }}
                players={spectatorState.players}
              />
            }
            timeline={
              <section
                className={withGlassPanel(
                  "live-timeline-panel min-w-0 overflow-hidden rounded-lg text-slate-100 shadow-[0_24px_70px_rgba(0,0,0,0.26)] md:col-span-2 xl:col-span-1 xl:max-h-[calc(100vh-8rem)] xl:overflow-auto",
                )}
                data-testid="live-timeline-panel"
              >
                <div className="border-b border-amber-500/15 px-4 py-3">
                  <h2 className="text-sm font-semibold text-amber-50">
                    剧情时间线
                  </h2>
                  <p className="mt-1 text-xs text-slate-400">
                    关键阶段、行动和结算
                  </p>
                </div>
                <LiveEventTimeline
                  currentEventId={director.currentEventId}
                  events={events}
                  variant="story"
                />
                <details className="border-t border-amber-500/15">
                  <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-300">
                    调试事件
                  </summary>
                  <LiveEventTimeline
                    currentEventId={director.currentEventId}
                    events={events}
                  />
                </details>
              </section>
            }
          />
        </LivePageShell>
      </main>
    </>
  );
}

function isTerminalRunStatus(status: string) {
  return status === "completed" || status === "failed";
}

function liveRosterState(
  status: LivePlayerStatus,
  isAlive: boolean,
  isActivePlayer: boolean,
): PlayerRosterItem["state"] {
  if (!isAlive) {
    return "dead";
  }
  if (isActivePlayer && status === "streaming") {
    return "speaking";
  }
  if (status === "thinking" || status === "requesting") {
    return "thinking";
  }
  if (status === "acted" || status === "responded") {
    return "acted";
  }
  if (isActivePlayer) {
    return "speaking";
  }
  return "alive";
}

function liveRosterStatusLabel(state: PlayerRosterItem["state"]) {
  if (state === "dead") {
    return "死亡";
  }
  if (state === "speaking") {
    return "发言中";
  }
  if (state === "thinking") {
    return "思考中";
  }
  if (state === "acted") {
    return "已行动";
  }
  return "存活";
}
