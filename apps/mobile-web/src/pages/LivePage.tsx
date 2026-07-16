import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  buildLivePhaseSegments,
  deriveGodViewState,
  deriveLiveNavStatus,
  deriveLiveSpectatorState,
  getGameRun,
  resumeGameRun,
  useGameRunEvents,
  useLiveDirector,
  useLiveVoiceStream,
  type LiveGameEvent,
} from "@werewolf-arena/game-client";

import {
  MobileLiveTheater,
  MobileLiveTheaterTopBar,
} from "../components/MobileLiveTheater";
import { voiceSubtitleToMobileSubtitle } from "../components/mobileLiveSubtitle";

const EMPTY_EVENTS: LiveGameEvent[] = [];

export function LivePage() {
  const { gameId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { connectionState, events, latestEvent } = useGameRunEvents(
    gameId,
    "spectator_god_view",
  );
  const runQuery = useQuery({
    queryKey: ["game-run", gameId],
    queryFn: () => getGameRun(gameId ?? ""),
    enabled: Boolean(gameId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "completed" || status === "failed" || status === "canceled"
        ? false
        : 15000;
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
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [voiceAdvanceHold, setVoiceAdvanceHold] = useState(false);
  const director = useLiveDirector(events, {
    holdAdvance: voiceAdvanceHold,
    resetKey: gameId,
    startAtEventType: run?.attempt_no && run.attempt_no > 1 ? undefined : "game_started",
    startAtLatestEventType:
      run?.attempt_no && run.attempt_no > 1 ? "game_resumed" : undefined,
  });
  const directorSourceEventId = sourceEventIdForCurrentRun(
    events,
    director.currentEventId,
    gameId,
  );
  const voice = useLiveVoiceStream(gameId, {
    audience: "spectator_god_view",
    currentEventId: directorSourceEventId,
    enabled: voiceEnabled,
    isPaused: director.isPaused,
  });
  const voiceCurrentItem = voice.currentItem;
  const unlockVoiceAudio = voice.unlockAudio;
  const completeVoicePlayback = director.completeVoicePlayback;
  const completedTimelinePlayback = useMemo(
    () =>
      mapVoiceCompletionToTimeline(
        events,
        voice.lastCompletedPlayback,
        gameId,
      ),
    [events, gameId, voice.lastCompletedPlayback],
  );
  useEffect(() => {
    completeVoicePlayback(completedTimelinePlayback);
  }, [completeVoicePlayback, completedTimelinePlayback]);
  useEffect(() => {
    if (!gameId || !voiceEnabled) {
      return;
    }

    void unlockVoiceAudio();
  }, [gameId, unlockVoiceAudio, voiceEnabled]);
  useEffect(() => {
    const shouldHold =
      voiceEnabled &&
      isVoicePlaybackBlocking(voiceCurrentItem, directorSourceEventId);
    // Voice playback depends on the current director event, so this feeds the
    // next render's hold flag back into the director without marking a user pause.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setVoiceAdvanceHold((current) =>
      current === shouldHold ? current : shouldHold,
    );
  }, [directorSourceEventId, voiceCurrentItem, voiceEnabled]);
  const handleToggleVoice = async () => {
    if (voiceEnabled && voice.connectionState === "error") {
      setVoiceEnabled(false);
      window.setTimeout(() => setVoiceEnabled(true), 0);
      return;
    }

    if (voiceEnabled) {
      setVoiceEnabled(false);
      return;
    }

    const audioUnlocked = await voice.unlockAudio();
    if (audioUnlocked) {
      setVoiceEnabled(true);
    }
  };
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
  const subtitle = useMemo(
    () => voiceSubtitleToMobileSubtitle(voice.currentSubtitle),
    [voice.currentSubtitle],
  );
  const liveStatus = deriveLiveNavStatus({
    backlogCount: director.backlogCount,
    connectionState,
    hasCompletedTerminalEvent: terminalEvent?.type === "game_completed",
    hasFailedTerminalEvent:
      terminalEvent?.type === "game_failed" ||
      terminalEvent?.type === "game_canceled",
    isPaused: director.isPaused,
    runStatus: run?.status ?? "queued",
    speed: director.speed,
  });
  const canResumeRun =
    run?.status === "failed" ||
    run?.status === "canceled" ||
    terminalEvent?.type === "game_failed" ||
    terminalEvent?.type === "game_canceled";

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
          onSelectEvent={(eventId) => director.seekToEventId(eventId)}
          onSelectPhase={(segment) =>
            director.seekToEventId(segment.startEventId)
          }
          onResumeRun={() => resumeMutation.mutate(run.session_id)}
          onToggleVoice={handleToggleVoice}
          phaseSegments={phaseSegments}
          replayLinkVisible={
            isTerminalRunStatus(run.status) || Boolean(terminalEvent)
          }
          resumeIsPending={resumeMutation.isPending}
          run={run}
          subtitle={subtitle}
          terminalEvent={terminalEvent}
          voiceEnabled={voiceEnabled}
          voiceState={voice}
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
      event.action === "sheriff_pk_speech" ||
      event.action === "exile_pk_speech")
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
  return (
    event.type === "game_completed" ||
    event.type === "game_failed" ||
    event.type === "game_canceled"
  );
}

function isTerminalRunStatus(status: string | undefined) {
  return status === "completed" || status === "failed" || status === "canceled";
}

function isVoicePlaybackBlocking(
  currentItem:
    | {
        lastSourceEventId?: number;
        sourceEventId: number;
        status: string;
      }
    | null
    | undefined,
  currentEventId: number | null,
) {
  if (!currentItem || currentEventId === null) {
    return false;
  }

  // Hold the speech cue from playback start, not after every coalesced delta.
  const playbackEventId = currentItem.sourceEventId;
  if (playbackEventId > currentEventId) {
    return false;
  }

  return currentItem.status !== "played" && currentItem.status !== "error";
}

function sourceEventIdForCurrentRun(
  events: LiveGameEvent[],
  timelineEventId: number | null,
  currentRunId: string | undefined,
) {
  if (timelineEventId === null || !currentRunId) {
    return null;
  }
  const event = events.find((candidate) => candidate.id === timelineEventId);
  if (!event || (event.source_run_id && event.source_run_id !== currentRunId)) {
    return null;
  }
  return event.source_event_id ?? event.id;
}

function mapVoiceCompletionToTimeline(
  events: LiveGameEvent[],
  completion: {
    id: string;
    sourceEventId: number;
    lastSourceEventId: number;
  } | null,
  currentRunId: string | undefined,
) {
  if (!completion || !currentRunId) {
    return null;
  }
  const coveredTimelineIds = events
    .filter((event) => {
      const sourceRunId = event.source_run_id ?? event.run_id;
      const sourceEventId = event.source_event_id ?? event.id;
      return (
        sourceRunId === currentRunId &&
        sourceEventId >= completion.sourceEventId &&
        sourceEventId <= completion.lastSourceEventId
      );
    })
    .map((event) => event.id);
  if (coveredTimelineIds.length === 0) {
    return null;
  }
  return {
    id: completion.id,
    sourceEventId: Math.min(...coveredTimelineIds),
    lastSourceEventId: Math.max(...coveredTimelineIds),
  };
}
