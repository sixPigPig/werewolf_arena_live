import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import {
  buildLivePhaseSegments,
  deriveGodViewState,
  deriveLiveNarrativeState,
  deriveLiveSpectatorState,
  getGamePlayback,
  resumeGameRun,
  useLiveDirector,
  usePlaybackVoice,
  type GamePlayback,
  type GameRunStatus,
  type LiveGameEvent,
} from "@werewolf-arena/game-client";

import {
  MobileLiveTheater,
  type MobileLiveTheaterRun,
} from "../components/MobileLiveTheater";
import { deriveMobileLiveSubtitle } from "../components/mobileLiveSubtitle";

const EMPTY_EVENTS: LiveGameEvent[] = [];

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
  const director = useLiveDirector(allEvents, {
    resetKey: gameId,
    startAtLatestTerminal: false,
  });
  const currentEventId = director.currentEventId;
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const voice = usePlaybackVoice(playback?.voices ?? [], {
    currentEventId,
    enabled: voiceEnabled,
    isPaused: director.isPaused,
  });
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
