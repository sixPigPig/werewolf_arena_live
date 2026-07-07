import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  buildLivePhaseSegments,
  deriveGodViewState,
  deriveLiveNarrativeState,
  deriveLiveNavStatus,
  deriveLiveSpectatorState,
  getGameRun,
  resumeGameRun,
  useGameRunEvents,
  useLiveDirector,
  type LiveGameEvent,
} from "@werewolf-arena/game-client";

import {
  MobileLiveTheater,
  MobileLiveTheaterTopBar,
} from "../components/MobileLiveTheater";
import { deriveMobileLiveSubtitle } from "../components/mobileLiveSubtitle";

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
    startAtEventType: "game_started",
    startAtLatestTerminal: isTerminalRunStatus(run?.status),
  });
  const stageEvents = useMemo(() => {
    const currentEventId = director.currentEventId;
    if (currentEventId === null) {
      return EMPTY_EVENTS;
    }

    const visibleEvents = events.filter((event) => event.id <= currentEventId);
    if (
      !director.isPaused &&
      director.backlogCount === 0 &&
      latestEvent &&
      latestEvent.id > currentEventId &&
      isLiveSpeakerDelta(latestEvent) &&
      !visibleEvents.some((event) => event.id === latestEvent.id)
    ) {
      return [...visibleEvents, latestEvent];
    }

    return visibleEvents;
  }, [
    director.backlogCount,
    director.currentEventId,
    director.isPaused,
    events,
    latestEvent,
  ]);
  const phaseSegments = useMemo(
    () => buildLivePhaseSegments(events, director.currentEventId),
    [director.currentEventId, events],
  );
  const currentEvent = stageEvents.at(-1) ?? latestEvent;
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
  const narrativeState = useMemo(
    () =>
      deriveLiveNarrativeState({
        cue: director.currentCue,
        events: stageEvents,
        godViewState,
        spectatorState,
      }),
    [director.currentCue, godViewState, spectatorState, stageEvents],
  );
  const subtitle = useMemo(
    () =>
      deriveMobileLiveSubtitle({
        godViewState,
        narrativeState,
      }),
    [godViewState, narrativeState],
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
      <h1 className="mobile-sr-only">实时观战</h1>

      {runQuery.isPending ? (
        <p className="mobile-status-banner" role="status">
          正在读取实时对局...
        </p>
      ) : null}
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

      {!run && runQuery.isPending ? (
        <section className="mobile-live-theater" aria-label="实时观战剧场">
          <MobileLiveTheaterTopBar
            liveStatusLabel={liveStatus.label}
            onBack={() => navigateBackToGames(navigate)}
            ruleName="实时对局"
          />
        </section>
      ) : null}

      {run ? (
        <MobileLiveTheater
          canResumeRun={canResumeRun}
          currentEvent={currentEvent}
          director={director}
          godViewState={godViewState}
          liveStatusLabel={liveStatus.label}
          onBack={() => navigateBackToGames(navigate)}
          onSelectPhase={(segment) =>
            director.seekToEventId(segment.startEventId)
          }
          onResumeRun={() => resumeMutation.mutate(run.session_id)}
          phaseSegments={phaseSegments}
          replayLinkVisible={
            isTerminalRunStatus(run.status) || Boolean(terminalEvent)
          }
          resumeIsPending={resumeMutation.isPending}
          run={run}
          subtitle={subtitle}
          terminalEvent={terminalEvent}
        />
      ) : null}
    </main>
  );
}

function isLiveSpeakerDelta(event: LiveGameEvent) {
  return (
    event.type === "model_response_delta" &&
    (event.action === "debate" ||
      event.action === "sheriff_speech" ||
      event.action === "sheriff_pk_speech")
  );
}

function navigateBackToGames(navigate: ReturnType<typeof useNavigate>) {
  const historyState = window.history.state as { idx?: number } | null;
  if (typeof historyState?.idx === "number" && historyState.idx > 0) {
    navigate(-1);
    return;
  }

  navigate("/games");
}

function isTerminalEvent(event: LiveGameEvent) {
  return event.type === "game_completed" || event.type === "game_failed";
}

function isTerminalRunStatus(status: string | undefined) {
  return status === "completed" || status === "failed";
}
