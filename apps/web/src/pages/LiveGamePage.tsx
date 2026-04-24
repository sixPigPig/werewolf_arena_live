import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { getGameRun } from "../features/games/api/getGameRun";
import { LiveEventTimeline } from "../features/games/components/LiveEventTimeline";
import { LiveFocusStage } from "../features/games/components/LiveFocusStage";
import { LivePlayerPanel } from "../features/games/components/LivePlayerPanel";
import { LiveStatusStrip } from "../features/games/components/LiveStatusStrip";
import { RuleSetSummary } from "../features/games/components/RuleSetSummary";
import { useGameRunEvents } from "../features/games/hooks/useGameRunEvents";
import { deriveLiveSpectatorState } from "../features/games/liveSpectator";

export function LiveGamePage() {
  const { runId } = useParams();
  const queryClient = useQueryClient();
  const { events, connectionState } = useGameRunEvents(runId);
  const [autoFollow, setAutoFollow] = useState(true);
  const [manualFocusName, setManualFocusName] = useState<string | null>(null);
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
  const focusedPlayerName = autoFollow
    ? spectatorState.activePlayerName
    : manualFocusName ?? spectatorState.activePlayerName;
  const focusedPlayer =
    spectatorState.players.find((player) => player.name === focusedPlayerName) ??
    null;

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
        <LiveFocusStage
          currentPhase={spectatorState.currentPhase}
          currentRound={spectatorState.currentRound}
          latestEvent={spectatorState.latestActorEvent}
          player={focusedPlayer}
        />
        <section className="overflow-hidden rounded-md border border-slate-200 bg-white lg:max-h-[calc(100vh-8rem)] lg:overflow-auto">
          <div className="border-b border-slate-200 px-4 py-3">
            <h2 className="text-sm font-semibold text-slate-950">原始事件</h2>
          </div>
          <LiveEventTimeline events={events} />
        </section>
      </div>
    </main>
  );
}
