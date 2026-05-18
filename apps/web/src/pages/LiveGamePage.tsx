import { Button, Callout, Text } from "../components/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { ArenaCommandNav, ArenaNavButton } from "../app/navigation";
import { getGameRun } from "../features/games/api/getGameRun";
import { resumeGameRun } from "../features/games/api/resumeGameRun";
import { GodViewBottomBoard } from "../features/games/components/GodViewBottomBoard";
import { GodViewIntelPanel } from "../features/games/components/GodViewIntelPanel";
import { GodViewSituationPanel } from "../features/games/components/GodViewSituationPanel";
import { GodViewTopBar } from "../features/games/components/GodViewTopBar";
import { LiveDirectorControls } from "../features/games/components/LiveDirectorControls";
import { LiveDirectorStage } from "../features/games/components/LiveDirectorStage";
import { LiveEventTimeline } from "../features/games/components/LiveEventTimeline";
import { LiveStatusStrip } from "../features/games/components/LiveStatusStrip";
import { RuleSetSummary } from "../features/games/components/RuleSetSummary";
import { useGameRunEvents } from "../features/games/hooks/useGameRunEvents";
import { useLiveDirector } from "../features/games/hooks/useLiveDirector";
import { deriveGodViewState } from "../features/games/liveGodView";
import { deriveLiveSpectatorState } from "../features/games/liveSpectator";
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
  const autoFocusName =
    director.currentCue?.actor ?? spectatorState.activePlayerName;
  const focusedPlayerName = autoFollow
    ? autoFocusName
    : manualFocusName ?? autoFocusName;
  const handleSelectPlayer = (name: string) => {
    setAutoFollow(false);
    setManualFocusName(name);
  };
  const topNavCommands = run ? (
    <LiveDirectorControls
      backlogCount={director.backlogCount}
      isPaused={director.isPaused}
      onCatchUpToLatest={director.catchUpToLatest}
      onSpeedChange={director.setSpeed}
      onTogglePaused={director.togglePaused}
      speed={director.speed}
    />
  ) : null;
  const topNavActions = (
    <>
      {canResumeRun && run ? (
        <ArenaNavButton
          disabled={resumeMutation.isPending}
          intent="primary"
          loading={resumeMutation.isPending}
          onClick={() => resumeMutation.mutate(run.session_id)}
        >
          继续对局
        </ArenaNavButton>
      ) : null}
      {terminalEvent && run ? (
        <ArenaNavButton to={`/games/${run.session_id}`}>
          查看完整复盘
        </ArenaNavButton>
      ) : null}
      <Button
        asChild
        className="h-10 w-10 px-0 text-lg"
        color="gray"
        highContrast
        size="2"
        variant="surface"
      >
        <Link aria-label="返回大厅" to="/games">
          <span aria-hidden="true">↪</span>
        </Link>
      </Button>
    </>
  );
  const topNavContext = run ? (
    <div
      className="live-nav-context flex min-w-0 flex-1 flex-nowrap items-center gap-x-3 overflow-hidden"
      data-testid="live-nav-context"
    >
      <h1 className="sr-only">实时观战</h1>
      <LiveStatusStrip run={run} connectionState={connectionState} variant="nav" />
      <span aria-hidden="true" className="h-6 w-px bg-slate-500/45" />
      <RuleSetSummary ruleSet={run.rule_set} variant="nav" />
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
        <LivePageShell>
          {resumeMutation.isError ? (
            <Callout.Root className="mb-3" color="red" size="1" variant="soft">
              <Callout.Text>无法继续对局</Callout.Text>
            </Callout.Root>
          ) : null}
          <LiveStageModule
            bottom={<GodViewBottomBoard state={godViewState} />}
            left={<GodViewSituationPanel state={godViewState} />}
            right={
              <GodViewIntelPanel
                debugTimeline={
                  <LiveEventTimeline
                    currentEventId={director.currentEventId}
                    events={events}
                  />
                }
                state={godViewState}
              />
            }
            stage={
              <LiveDirectorStage
                activePlayerName={autoFocusName}
                autoFollow={autoFollow}
                backlogCount={director.backlogCount}
                cue={director.currentCue}
                focusedPlayerName={focusedPlayerName}
                godViewState={godViewState}
                isCatchingUp={director.isCatchingUp}
                onAutoFollowChange={(value) => {
                  setAutoFollow(value);
                  if (value) {
                    setManualFocusName(null);
                  }
                }}
                onSelectPlayer={handleSelectPlayer}
                players={spectatorState.players}
              />
            }
            top={
              <GodViewTopBar state={godViewState} />
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
