import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  buildLivePhaseSegments,
  currentSubtitleForPlaybackVoices,
  deriveGodViewState,
  deriveLiveSpectatorState,
  getGamePlayback,
  resumeGameRun,
  useLiveDirector,
  usePlaybackVoice,
  type GamePlayback,
  type GameRunStatus,
  type LiveGameEvent,
  type PlaybackVoiceUtterance,
} from "@werewolf-arena/game-client";

import {
  MobileLiveTheater,
  type MobileLiveTheaterRun,
} from "../components/MobileLiveTheater";
import { voiceSubtitleToMobileSubtitle } from "../components/mobileLiveSubtitle";

const EMPTY_EVENTS: LiveGameEvent[] = [];
const EMPTY_VOICES: PlaybackVoiceUtterance[] = [];
const REPLAY_SUBTITLE_CLOCK_INTERVAL_MS = 50;

export function LiveReplayPage() {
  const { gameId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const playbackQuery = useQuery({
    queryKey: ["game-playback", gameId],
    queryFn: () => getGamePlayback(gameId ?? ""),
    enabled: Boolean(gameId),
  });
  const playback = playbackQuery.data;
  const allEvents = playback?.events ?? EMPTY_EVENTS;
  const playbackVoices = playback?.voices ?? EMPTY_VOICES;
  const [voiceEnabled, setVoiceEnabled] = useState(true);
  const [voiceAdvanceHold, setVoiceAdvanceHold] = useState(false);
  const director = useLiveDirector(allEvents, {
    holdAdvance: voiceAdvanceHold,
    resetKey: gameId,
    startAtLatestTerminal: false,
  });
  const currentEventId = director.currentEventId;
  const voice = usePlaybackVoice(playbackVoices, {
    currentEventId,
    enabled: voiceEnabled,
    isPaused: director.isPaused,
  });
  const voiceCurrentItem = voice.currentItem;
  const unlockVoiceAudio = voice.unlockAudio;
  useEffect(() => {
    if (!gameId || !voiceEnabled) {
      return;
    }

    void unlockVoiceAudio();
  }, [gameId, unlockVoiceAudio, voiceEnabled]);
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
  useEffect(() => {
    const shouldHold =
      voiceEnabled &&
      isVoicePlaybackBlocking(voiceCurrentItem, director.currentEventId);
    // Voice playback depends on the current director event, so this feeds the
    // next render's hold flag back into the director without marking a user pause.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setVoiceAdvanceHold((current) =>
      current === shouldHold ? current : shouldHold,
    );
  }, [director.currentEventId, voiceCurrentItem, voiceEnabled]);
  const stageEvents = useMemo(() => {
    if (currentEventId === null) {
      return EMPTY_EVENTS;
    }

    return allEvents.filter((event) => event.id <= currentEventId);
  }, [allEvents, currentEventId]);
  const currentEvent = stageEvents.at(-1) ?? null;
  const phaseSegments = useMemo(
    () => buildLivePhaseSegments(allEvents, currentEventId),
    [allEvents, currentEventId],
  );
  const spectatorState = useMemo(
    () => deriveLiveSpectatorState(stageEvents),
    [stageEvents],
  );
  const godViewState = useMemo(
    () =>
      deriveGodViewState(
        stageEvents,
        spectatorState,
        playback?.rule_set?.name ?? "历史回放",
        { sheriffEnabled: playback?.rule_set?.sheriff_enabled },
      ),
    [
      playback?.rule_set?.name,
      playback?.rule_set?.sheriff_enabled,
      spectatorState,
      stageEvents,
    ],
  );
  const replaySubtitleElapsedMs = useReplaySubtitleElapsedMs({
    currentEventId,
    isPaused: director.isPaused,
    speed: director.speed,
  });
  const replaySubtitle = useMemo(
    () =>
      currentSubtitleForPlaybackVoices({
        currentEventId,
        elapsedMs: replaySubtitleElapsedMs,
        isPaused: director.isPaused,
        voices: playbackVoices,
      }),
    [currentEventId, director.isPaused, playbackVoices, replaySubtitleElapsedMs],
  );
  const subtitle = useMemo(
    () => voiceSubtitleToMobileSubtitle(voice.currentSubtitle ?? replaySubtitle),
    [replaySubtitle, voice.currentSubtitle],
  );
  const visibleTerminalEvent = terminalEventFor(stageEvents);
  const terminalEvent = terminalEventFor(allEvents);
  const run = playback
    ? playbackRun(playback, statusForVisiblePlayback(visibleTerminalEvent))
    : null;
  const resumeMutation = useMutation({
    mutationFn: (sessionId: string) => resumeGameRun(sessionId),
    onSuccess: (newRun) => {
      void queryClient.invalidateQueries({ queryKey: ["games"] });
      void queryClient.invalidateQueries({ queryKey: ["game-playback", gameId] });
      navigate(`/games/${newRun.run_id}/live`);
    },
  });
  const canResumeRun = playback?.resumable === true;

  return (
    <main className="mobile-page mobile-live-page">
      <h1 className="mobile-sr-only">历史直播回放</h1>

      {playbackQuery.isPending ? (
        <p className="mobile-status-banner" role="status">
          正在准备历史播放台...
        </p>
      ) : null}
      {playbackQuery.isError ? (
        <p className="mobile-status-banner" role="alert">
          无法读取历史回放
        </p>
      ) : null}
      {resumeMutation.isError ? (
        <p className="mobile-status-banner" role="alert">
          无法继续对局
        </p>
      ) : null}

      {run ? (
        <MobileLiveTheater
          canResumeRun={canResumeRun}
          currentEvent={currentEvent}
          director={director}
          godViewState={godViewState}
          liveStatusLabel={playbackStatusLabel({
            isPaused: director.isPaused,
            terminalEvent: visibleTerminalEvent,
          })}
          onBack={() => navigateBackToHistory(navigate)}
          onSelectPhase={(segment) =>
            director.seekToEventId(segment.startEventId)
          }
          onResumeRun={() => resumeMutation.mutate(run.session_id)}
          onToggleVoice={handleToggleVoice}
          phaseSegments={phaseSegments}
          replayLinkVisible={true}
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

function terminalEventFor(events: LiveGameEvent[]) {
  return events.find(
    (event) =>
      event.type === "game_completed" ||
      event.type === "game_failed" ||
      event.type === "game_canceled",
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

  if (terminalEvent?.type === "game_canceled") {
    return "canceled";
  }

  return "running";
}

function playbackRun(
  playback: GamePlayback,
  status: GameRunStatus,
): MobileLiveTheaterRun {
  return {
    rule_set: playback.rule_set,
    session_id: playback.session_id,
    status,
  };
}

function playbackStatusLabel({
  isPaused,
  terminalEvent,
}: {
  isPaused: boolean;
  terminalEvent: LiveGameEvent | undefined;
}) {
  if (terminalEvent?.type === "game_completed") {
    return "已完成";
  }

  if (terminalEvent?.type === "game_failed") {
    return "对局失败";
  }

  if (terminalEvent?.type === "game_canceled") {
    return "已取消";
  }

  if (isPaused) {
    return "已暂停";
  }

  return "历史回放";
}

function navigateBackToHistory(navigate: ReturnType<typeof useNavigate>) {
  const historyState = window.history.state as { idx?: number } | null;
  if (typeof historyState?.idx === "number" && historyState.idx > 0) {
    navigate(-1);
    return;
  }

  navigate("/history");
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

  const playbackEventId = currentItem.lastSourceEventId ?? currentItem.sourceEventId;
  if (playbackEventId > currentEventId) {
    return false;
  }

  return currentItem.status !== "played" && currentItem.status !== "error";
}

function useReplaySubtitleElapsedMs({
  currentEventId,
  isPaused,
  speed,
}: {
  currentEventId: number | null;
  isPaused: boolean;
  speed: number;
}) {
  const [clock, setClock] = useState<{
    currentEventId: number | null;
    elapsedMs: number;
  }>({ currentEventId: null, elapsedMs: 0 });
  const activeEventIdRef = useRef<number | null>(null);
  const startedAtRef = useRef(0);
  const pausedAtRef = useRef<number | null>(null);

  useEffect(() => {
    activeEventIdRef.current = currentEventId;
    startedAtRef.current = Date.now();
    pausedAtRef.current = null;
  }, [currentEventId]);

  useEffect(() => {
    if (currentEventId === null) {
      return;
    }

    if (isPaused) {
      if (pausedAtRef.current === null) {
        pausedAtRef.current = Date.now();
      }
      return;
    }

    if (pausedAtRef.current !== null) {
      startedAtRef.current += Date.now() - pausedAtRef.current;
      pausedAtRef.current = null;
    }

    const updateElapsedMs = () => {
      const nextElapsedMs = Math.max(
        0,
        Math.round((Date.now() - startedAtRef.current) * speed),
      );
      setClock((current) => {
        if (activeEventIdRef.current !== currentEventId) {
          return current;
        }
        if (
          current.currentEventId === currentEventId &&
          current.elapsedMs === nextElapsedMs
        ) {
          return current;
        }
        return { currentEventId, elapsedMs: nextElapsedMs };
      });
    };

    const intervalId = window.setInterval(
      updateElapsedMs,
      REPLAY_SUBTITLE_CLOCK_INTERVAL_MS,
    );

    return () => {
      window.clearInterval(intervalId);
    };
  }, [currentEventId, isPaused, speed]);

  return clock.currentEventId === currentEventId ? clock.elapsedMs : 0;
}
