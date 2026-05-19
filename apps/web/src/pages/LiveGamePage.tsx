import { Callout, Text } from "../components/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ArenaCommandNav, ArenaNavButton } from "../app/navigation";
import { getGameRun } from "../features/games/api/getGameRun";
import { resumeGameRun } from "../features/games/api/resumeGameRun";
import { LiveNavSessionBadge } from "../features/games/components/LiveNavSessionBadge";
import { LiveNavSettingsMenu } from "../features/games/components/LiveNavSettingsMenu";
import { LiveNavStatusBadge } from "../features/games/components/LiveNavStatusBadge";
import { LiveStageExperience } from "../features/games/components/LiveStageExperience";
import { useGameRunEvents } from "../features/games/hooks/useGameRunEvents";
import { useLiveDirector } from "../features/games/hooks/useLiveDirector";
import { deriveGodViewState } from "../features/games/liveGodView";
import { deriveLiveNavStatus } from "../features/games/liveNavStatus";
import { deriveLiveSpectatorState } from "../features/games/liveSpectator";

export function LiveGamePage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { events, connectionState } = useGameRunEvents(runId);
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
  const godViewState = useMemo(
    () =>
      deriveGodViewState(
        events,
        spectatorState,
        run?.rule_set?.name ?? "实时对局",
        { sheriffEnabled: run?.rule_set?.sheriff_enabled },
      ),
    [events, run?.rule_set?.name, run?.rule_set?.sheriff_enabled, spectatorState],
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
  const liveNavStatus = deriveLiveNavStatus({
    backlogCount: director.backlogCount,
    connectionState,
    hasCompletedTerminalEvent: terminalEvent?.type === "game_completed",
    hasFailedTerminalEvent: terminalEvent?.type === "game_failed",
    isPaused: director.isPaused,
    runStatus: run?.status ?? "queued",
    speed: director.speed,
  });
  const topNavCommands = null;
  const topNavActions = run ? (
    <>
      {terminalEvent ? (
        <ArenaNavButton to={`/games/${run.session_id}`}>
          查看完整复盘
        </ArenaNavButton>
      ) : null}
      <LiveNavSettingsMenu
        backlogCount={director.backlogCount}
        canResumeRun={canResumeRun}
        isPaused={director.isPaused}
        isResuming={resumeMutation.isPending}
        onCatchUpToLatest={director.catchUpToLatest}
        onResumeRun={() => resumeMutation.mutate(run.session_id)}
        onSpeedChange={director.setSpeed}
        onTogglePaused={director.togglePaused}
        run={run}
        speed={director.speed}
        status={liveNavStatus}
      />
    </>
  ) : null;
  const topNavContext = run ? (
    <div
      className="live-nav-context flex min-w-0 flex-1 flex-nowrap items-center gap-x-3 overflow-hidden"
      data-testid="live-nav-context"
    >
      <h1 className="sr-only">实时观战</h1>
      <LiveNavSessionBadge sessionId={run.session_id} />
      <LiveNavStatusBadge status={liveNavStatus} />
    </div>
  ) : null;
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
        <ArenaCommandNav
          actions={topNavActions}
          commands={topNavCommands}
          context={topNavContext}
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
        <ArenaCommandNav
          actions={topNavActions}
          commands={topNavCommands}
          context={topNavContext}
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
      <ArenaCommandNav
        actions={topNavActions}
        commands={topNavCommands}
        context={topNavContext}
      />
      <main
        className="live-game-page min-h-screen px-4 py-6 text-slate-100"
        data-testid="live-game-page"
      >
        {resumeMutation.isError ? (
          <Callout.Root className="mb-3" color="red" size="1" variant="soft">
            <Callout.Text>无法继续对局</Callout.Text>
          </Callout.Root>
        ) : null}
        <LiveStageExperience
          director={director}
          events={events}
          godViewState={godViewState}
          mode="live"
          spectatorState={spectatorState}
        />
      </main>
    </>
  );
}

function isTerminalRunStatus(status: string) {
  return status === "completed" || status === "failed";
}
