import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { Link, useParams } from "react-router-dom";

import { getGameRun } from "../features/games/api/getGameRun";
import { LiveEventTimeline } from "../features/games/components/LiveEventTimeline";
import { LiveStatusStrip } from "../features/games/components/LiveStatusStrip";
import { useGameRunEvents } from "../features/games/hooks/useGameRunEvents";

export function LiveGamePage() {
  const { runId } = useParams();
  const queryClient = useQueryClient();
  const { events, connectionState } = useGameRunEvents(runId);
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

  useEffect(() => {
    if (!terminalEvent) {
      return;
    }
    queryClient.invalidateQueries({ queryKey: ["games"] });
  }, [queryClient, terminalEvent]);

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
        <LiveEventTimeline events={events} />
      </section>
    </main>
  );
}
