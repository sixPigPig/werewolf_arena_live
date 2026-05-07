import { Button, Callout, Card, Heading, Text } from "@radix-ui/themes";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { getGameRun } from "../features/games/api/getGameRun";
import { resumeGameRun } from "../features/games/api/resumeGameRun";
import { LiveDirectorControls } from "../features/games/components/LiveDirectorControls";
import { LiveDirectorStage } from "../features/games/components/LiveDirectorStage";
import { LiveEventTimeline } from "../features/games/components/LiveEventTimeline";
import { LiveStatusStrip } from "../features/games/components/LiveStatusStrip";
import { RuleSetSummary } from "../features/games/components/RuleSetSummary";
import { useGameRunEvents } from "../features/games/hooks/useGameRunEvents";
import { useLiveDirector } from "../features/games/hooks/useLiveDirector";
import { deriveLiveSpectatorState } from "../features/games/liveSpectator";

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
        <Text color="gray" size="2">正在读取实时对局...</Text>
      </main>
    );
  }

  if (isError || !run) {
    return (
      <main className="mx-auto w-full max-w-5xl px-4 py-8">
        <Callout.Root color="red" size="1" variant="soft">
          <Callout.Text>无法读取实时对局</Callout.Text>
        </Callout.Root>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-7xl px-4 py-6">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div>
          <Text color="gray" size="1" weight="medium">
            WEREWOLF LIVE
          </Text>
          <Heading as="h1" size="6">
            实时观战
          </Heading>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {canResumeRun ? (
            <Button
              disabled={resumeMutation.isPending}
              highContrast
              loading={resumeMutation.isPending}
              onClick={() => resumeMutation.mutate(run.session_id)}
              type="button"
            >
              继续对局
            </Button>
          ) : null}
          {terminalEvent ? (
            <Button asChild color="gray" variant="surface">
              <Link to={`/games/${run.session_id}`}>查看完整复盘</Link>
            </Button>
          ) : null}
        </div>
      </div>
      {resumeMutation.isError ? (
        <Callout.Root className="mb-3" color="red" size="1" variant="soft">
          <Callout.Text>无法继续对局</Callout.Text>
        </Callout.Root>
      ) : null}
      <div className="sticky top-0 z-10">
        <Card asChild size="1">
          <section className="overflow-hidden">
            <LiveStatusStrip run={run} connectionState={connectionState} />
          </section>
        </Card>
      </div>
      <div className="mt-4">
        <RuleSetSummary ruleSet={run.rule_set} />
      </div>
      <div
        className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]"
        data-testid="live-stage-layout"
      >
        <div className="min-w-0 space-y-3">
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
        <Card asChild size="1">
          <section className="min-w-0 overflow-hidden xl:max-h-[calc(100vh-8rem)] xl:overflow-auto">
            <div className="border-b border-slate-200 px-4 py-3">
              <h2 className="text-sm font-semibold text-slate-950">
                剧情时间线
              </h2>
              <p className="mt-1 text-xs text-slate-500">
                关键阶段、行动和结算
              </p>
            </div>
            <LiveEventTimeline
              currentEventId={director.currentEventId}
              events={events}
              variant="story"
            />
            <details className="border-t border-slate-200">
              <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-slate-700">
                调试事件
              </summary>
              <LiveEventTimeline
                currentEventId={director.currentEventId}
                events={events}
              />
            </details>
          </section>
        </Card>
      </div>
    </main>
  );
}

function isTerminalRunStatus(status: string) {
  return status === "completed" || status === "failed";
}
