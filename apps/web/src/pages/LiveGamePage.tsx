import { Button, Callout, Heading, Text } from "@radix-ui/themes";
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
      {canResumeRun && run ? (
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
      {terminalEvent && run ? (
        <Button asChild color="gray" highContrast variant="surface">
          <Link to={`/games/${run.session_id}`}>查看完整复盘</Link>
        </Button>
      ) : null}
    </>
  );
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
        <AppTopNav actions={topNavActions} showLobbyBack tone="nocturne" />
        <main className="min-h-screen bg-[#071015] px-4 py-8 text-slate-100">
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
        <AppTopNav actions={topNavActions} showLobbyBack tone="nocturne" />
        <main className="min-h-screen bg-[#071015] px-4 py-8 text-slate-100">
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
      <AppTopNav actions={topNavActions} showLobbyBack tone="nocturne" />
      <main
        className="live-game-page min-h-screen bg-[#071015] bg-[radial-gradient(circle_at_12%_0%,rgba(20,184,166,0.14),transparent_28%),radial-gradient(circle_at_88%_4%,rgba(180,83,9,0.18),transparent_30%),linear-gradient(180deg,#071015_0%,#0d1117_48%,#05070a_100%)] px-4 py-6 text-slate-100"
        data-testid="live-game-page"
      >
        <div className="live-game-content mx-auto w-full max-w-none">
          <div className="live-page-heading mb-4" data-testid="live-page-heading">
            <div>
              <Text
                className="tracking-[0.28em] text-amber-200/75"
                size="1"
                weight="medium"
              >
                WEREWOLF LIVE
              </Text>
              <Heading as="h1" className="text-amber-50" size="6">
                实时观战
              </Heading>
            </div>
          </div>
          {resumeMutation.isError ? (
            <Callout.Root className="mb-3" color="red" size="1" variant="soft">
              <Callout.Text>无法继续对局</Callout.Text>
            </Callout.Root>
          ) : null}
          <div
            className="live-status-shell lg:sticky lg:top-0 lg:z-10"
            data-testid="live-status-shell"
          >
            <section className="overflow-hidden rounded-lg border border-amber-500/20 bg-slate-950/65 shadow-[0_18px_50px_rgba(0,0,0,0.24)] backdrop-blur-xl">
              <LiveStatusStrip run={run} connectionState={connectionState} />
            </section>
          </div>
          <div
            className="live-rule-summary-shell mt-4"
            data-testid="live-rule-summary-shell"
          >
            <RuleSetSummary ruleSet={run.rule_set} />
          </div>
          <div
            className="live-stage-layout mt-4 grid gap-4 md:grid-cols-[20rem_minmax(0,1fr)] xl:grid-cols-[20rem_minmax(0,1fr)_22rem]"
            data-testid="live-stage-layout"
          >
            <div className="live-roster-column min-w-0 md:sticky md:top-4 md:self-start">
              <PlayerRosterPanel
                onSelectPlayer={(name) => {
                  setAutoFollow(false);
                  setManualFocusName(name);
                }}
                players={rosterPlayers}
              />
            </div>
            <div className="live-stage-column min-w-0 space-y-3">
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
            <section
              className="live-timeline-panel min-w-0 overflow-hidden rounded-lg border border-amber-500/20 bg-slate-950/65 text-slate-100 shadow-[0_24px_70px_rgba(0,0,0,0.35)] backdrop-blur-xl md:col-span-2 xl:col-span-1 xl:max-h-[calc(100vh-8rem)] xl:overflow-auto"
              data-testid="live-timeline-panel"
            >
              <div className="border-b border-amber-500/15 bg-gradient-to-r from-amber-500/10 via-transparent to-teal-400/10 px-4 py-3">
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
          </div>
        </div>
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
