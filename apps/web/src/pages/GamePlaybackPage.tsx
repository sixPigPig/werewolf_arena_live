import { Callout, Text } from "../components/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ArenaCommandNav, ArenaNavButton } from "../app/navigation";
import { getGamePlayback } from "../features/games/api/getGamePlayback";
import { resumeGameRun } from "../features/games/api/resumeGameRun";
import { LiveNavSessionBadge } from "../features/games/components/LiveNavSessionBadge";
import { LiveNavSettingsMenu } from "../features/games/components/LiveNavSettingsMenu";
import { LiveNavStatusBadge } from "../features/games/components/LiveNavStatusBadge";
import { LiveStageExperience } from "../features/games/components/LiveStageExperience";
import { useLiveDirector } from "../features/games/hooks/useLiveDirector";
import { deriveGodViewState } from "../features/games/liveGodView";
import { deriveLiveNavStatus } from "../features/games/liveNavStatus";
import { deriveLiveSpectatorState } from "../features/games/liveSpectator";
import type {
  GamePlayback,
  GameRunStatus,
  LiveGameEvent,
  LiveStageRun,
} from "../features/games/types";

const EMPTY_EVENTS: LiveGameEvent[] = [];

export function GamePlaybackPage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data, isError, isPending } = useQuery({
    queryKey: ["game-playback", sessionId],
    queryFn: () => getGamePlayback(sessionId!),
    enabled: Boolean(sessionId),
  });
  const playback = data;
  const allEvents = playback?.events ?? EMPTY_EVENTS;
  const run = useMemo(
    () => (playback ? playbackRun(playback) : null),
    [playback],
  );
  const director = useLiveDirector(allEvents, {
    resetKey: sessionId,
    startAtLatestTerminal: false,
  });
  const currentEventId = director.currentEventId;
  const visibleEvents = useMemo(() => {
    if (currentEventId === null) {
      return EMPTY_EVENTS;
    }

    return allEvents.filter((event) => event.id <= currentEventId);
  }, [allEvents, currentEventId]);
  const visibleTerminalEvent = useMemo(
    () => terminalEventFor(visibleEvents),
    [visibleEvents],
  );
  const effectiveRunStatus = statusForVisiblePlayback(visibleTerminalEvent);
  const effectiveConnectionState = visibleTerminalEvent ? "closed" : "open";
  const canResumePlayback = Boolean(
    playback?.resumable && visibleTerminalEvent?.type === "game_failed",
  );
  const spectatorState = useMemo(
    () => deriveLiveSpectatorState(visibleEvents),
    [visibleEvents],
  );
  const godViewState = useMemo(
    () =>
      deriveGodViewState(
        visibleEvents,
        spectatorState,
        playback?.rule_set?.name ?? "历史回放",
        { sheriffEnabled: playback?.rule_set?.sheriff_enabled },
      ),
    [
      playback?.rule_set?.name,
      playback?.rule_set?.sheriff_enabled,
      spectatorState,
      visibleEvents,
    ],
  );
  const liveNavStatus = deriveLiveNavStatus({
    backlogCount: director.backlogCount,
    connectionState: effectiveConnectionState,
    hasCompletedTerminalEvent: visibleTerminalEvent?.type === "game_completed",
    hasFailedTerminalEvent: visibleTerminalEvent?.type === "game_failed",
    isPaused: director.isPaused,
    runStatus: effectiveRunStatus,
    speed: director.speed,
  });
  const resumeMutation = useMutation({
    mutationFn: resumeGameRun,
    onSuccess: (newRun) => {
      queryClient.invalidateQueries({ queryKey: ["games"] });
      queryClient.invalidateQueries({ queryKey: ["game-playback", sessionId] });
      navigate(`/games/live/${newRun.run_id}`);
    },
  });

  const topNavActions = run ? (
    <>
      <ArenaNavButton to={`/games/${run.session_id}`}>查看复盘</ArenaNavButton>
      <LiveNavSettingsMenu
        backlogCount={director.backlogCount}
        canResumeRun={canResumePlayback}
        isPaused={director.isPaused}
        isResuming={resumeMutation.isPending}
        onCatchUpToLatest={director.catchUpToLatest}
        onResumeRun={() => resumeMutation.mutate(run.session_id)}
        onSpeedChange={director.setSpeed}
        onTogglePaused={director.togglePaused}
        run={run}
        speed={director.speed}
        status={liveNavStatus}
        title="回放设置"
      />
    </>
  ) : (
    <>
      {sessionId ? (
        <ArenaNavButton to={`/games/${sessionId}`}>查看复盘</ArenaNavButton>
      ) : null}
      <ArenaNavButton to="/games/history">返回历史</ArenaNavButton>
    </>
  );
  const topNavContext = run ? (
    <div
      className="live-nav-context flex min-w-0 flex-1 flex-nowrap items-center gap-x-3 overflow-hidden"
      data-testid="live-nav-context"
    >
      <h1 className="sr-only">历史回放</h1>
      <LiveNavSessionBadge sessionId={run.session_id} />
      <LiveNavStatusBadge status={liveNavStatus} />
    </div>
  ) : null;

  if (isPending) {
    return (
      <>
        <ArenaCommandNav actions={topNavActions} context={topNavContext} />
        <main className="min-h-screen px-4 py-8 text-slate-100">
          <Text className="text-slate-300">正在准备历史播放台...</Text>
        </main>
      </>
    );
  }

  if (isError || !playback || !run) {
    return (
      <>
        <ArenaCommandNav actions={topNavActions} context={topNavContext} />
        <main className="min-h-screen px-4 py-8 text-slate-100">
          <Callout.Root color="red" size="1" variant="soft">
            <Callout.Text>无法读取历史回放</Callout.Text>
          </Callout.Root>
        </main>
      </>
    );
  }

  return (
    <>
      <ArenaCommandNav actions={topNavActions} context={topNavContext} />
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
          events={visibleEvents}
          godViewState={godViewState}
          mode="playback"
          spectatorState={spectatorState}
        />
      </main>
    </>
  );
}

function playbackRun(playback: GamePlayback): LiveStageRun {
  const terminalEvent = terminalEventFor(playback.events);
  return {
    completed_at: terminalEvent?.created_at ?? null,
    created_at: playback.events[0]?.created_at ?? "",
    error: stringPayloadValue(terminalEvent, "error"),
    event_count: playback.events.length,
    rule_set: playback.rule_set,
    run_id: `playback_${playback.session_id}`,
    session_id: playback.session_id,
    started_at: playback.events[0]?.created_at ?? null,
    status: playback.status === "complete" ? "completed" : "failed",
    winner: stringPayloadValue(terminalEvent, "winner"),
  };
}

function terminalEventFor(events: LiveGameEvent[]) {
  return events.find(
    (event) => event.type === "game_completed" || event.type === "game_failed",
  );
}

function statusForVisiblePlayback(
  terminalEvent: LiveGameEvent | undefined,
): GameRunStatus {
  if (terminalEvent?.type === "game_completed") {
    return "completed";
  }

  if (terminalEvent?.type === "game_failed") {
    return "failed";
  }

  return "running";
}

function stringPayloadValue(
  event: LiveGameEvent | undefined,
  key: "error" | "winner",
) {
  const value = event?.payload[key];
  return typeof value === "string" ? value : null;
}
