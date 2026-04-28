import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getGameRun } from "../features/games/api/getGameRun";
import { LiveDirectorControls } from "../features/games/components/LiveDirectorControls";
import { LiveDirectorStage } from "../features/games/components/LiveDirectorStage";
import { LiveEventTimeline } from "../features/games/components/LiveEventTimeline";
import { LivePlayerPanel } from "../features/games/components/LivePlayerPanel";
import { LiveStatusStrip } from "../features/games/components/LiveStatusStrip";
import { RuleSetSummary } from "../features/games/components/RuleSetSummary";
import { useGameRunEvents } from "../features/games/hooks/useGameRunEvents";
import { useLiveDirector } from "../features/games/hooks/useLiveDirector";
import { deriveLiveSpectatorState } from "../features/games/liveSpectator";

export function LiveGamePage() {
  const { runId } = useParams();
  const queryClient = useQueryClient();
  const { events, connectionState } = useGameRunEvents(runId);
  const [autoFollow, setAutoFollow] = useState(true);
  const [manualFocusName, setManualFocusName] = useState<string | null>(null);
  const [initialRunTerminalStart, setInitialRunTerminalStart] = useState<
    { runId: string | undefined; shouldStart: boolean } | null
  >(null);
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

  const terminalEvent = events.find(
    (event) => event.type === "game_completed" || event.type === "game_failed",
  );
  const spectatorState = useMemo(
    () => deriveLiveSpectatorState(events),
    [events],
  );
  const shouldStartAtTerminal =
    initialRunTerminalStart?.runId === runId &&
    initialRunTerminalStart.shouldStart;
  const director = useLiveDirector(events, {
    startAtLatestTerminal: shouldStartAtTerminal,
  });
  const autoFocusName =
    director.currentCue?.actor ?? spectatorState.activePlayerName;
  const focusedPlayerName = autoFollow
    ? autoFocusName
    : manualFocusName ?? autoFocusName;

  useEffect(() => {
    if (!terminalEvent) {
      return;
    }
    queryClient.invalidateQueries({ queryKey: ["games"] });
    if (runId) {
      queryClient.invalidateQueries({ queryKey: ["game-run", runId] });
    }
  }, [queryClient, runId, terminalEvent]);

  useEffect(() => {
    if (!run || initialRunTerminalStart?.runId === runId) {
      return;
    }

    setInitialRunTerminalStart({
      runId,
      shouldStart: run.status === "completed" || run.status === "failed",
    });
  }, [initialRunTerminalStart?.runId, run, runId]);

  if (isPending) {
    return (
      <main className="mx-auto w-full max-w-5xl px-4 py-8">
        <p className="text-sm text-slate-600">正在读取实时对局...</p>
      </main>
    );
  }

  if (isError || !run) {
    return (
      <main className="mx-auto w-full max-w-5xl px-4 py-8">
        <p className="text-sm text-red-700">无法读取实时对局</p>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8">
      <div className="mb-4 flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold text-slate-950">实时观战</h1>
        {terminalEvent ? (
          <Link
            className="rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white"
            to={`/games/${run.session_id}`}
          >
            查看完整复盘
          </Link>
        ) : null}
      </div>
      <section className="overflow-hidden rounded-md border border-slate-200 bg-white">
        <LiveStatusStrip run={run} connectionState={connectionState} />
      </section>
      <div className="mt-4">
        <RuleSetSummary ruleSet={run.rule_set} />
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)_22rem]">
        <LivePlayerPanel
          activePlayerName={spectatorState.activePlayerName}
          autoFollow={autoFollow}
          focusedPlayerName={focusedPlayerName}
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
        <div className="space-y-3">
          <LiveDirectorStage
            backlogCount={director.backlogCount}
            cue={director.currentCue}
            isCatchingUp={director.isCatchingUp}
          />
          <LiveDirectorControls
            backlogCount={director.backlogCount}
            isCatchingUp={director.isCatchingUp}
            isPaused={director.isPaused}
            onCatchUpToLatest={director.catchUpToLatest}
            onSpeedChange={director.setSpeed}
            onTogglePaused={director.togglePaused}
            speed={director.speed}
          />
        </div>
        <section className="overflow-hidden rounded-md border border-slate-200 bg-white lg:max-h-[calc(100vh-8rem)] lg:overflow-auto">
          <div className="border-b border-slate-200 px-4 py-3">
            <h2 className="text-sm font-semibold text-slate-950">原始事件</h2>
          </div>
          <LiveEventTimeline
            currentEventId={director.currentEventId}
            events={events}
          />
        </section>
      </div>
    </main>
  );
}
