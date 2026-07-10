import { Callout, Text } from "../components/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ArenaCommandNav, ArenaNavButton } from "../app/navigation";
import { useLiveVoiceStream } from "@werewolf-arena/game-client/live";
import { getGameRun } from "../features/games/api/getGameRun";
import { resumeGameRun } from "../features/games/api/resumeGameRun";
import { LiveNavSessionBadge } from "../features/games/components/LiveNavSessionBadge";
import { LiveNavDebugPanelButton } from "../features/games/components/LiveNavDebugPanelButton";
import { LiveNavSettingsMenu } from "../features/games/components/LiveNavSettingsMenu";
import { LiveNavStatusBadge } from "../features/games/components/LiveNavStatusBadge";
import { LiveStageExperience } from "../features/games/components/LiveStageExperience";
import { useGameRunEvents } from "../features/games/hooks/useGameRunEvents";
import { useLiveDirector } from "../features/games/hooks/useLiveDirector";
import { buildLivePhaseSegments } from "../features/games/livePhaseBar";
import { deriveGodViewState } from "../features/games/liveGodView";
import { deriveLiveNavStatus } from "../features/games/liveNavStatus";
import { deriveLiveSpectatorState } from "../features/games/liveSpectator";
import type { LiveGameEvent } from "../features/games/types";

const EMPTY_EVENTS: LiveGameEvent[] = [];

export function LiveGamePage() {
  const { runId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { events, connectionState } = useGameRunEvents(runId);
  const [isDebugPanelOpen, setIsDebugPanelOpen] = useState(false);
  const debugPanelButtonRef = useRef<HTMLButtonElement | null>(null);
  const [voiceAdvanceHold, setVoiceAdvanceHold] = useState(false);
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
  const director = useLiveDirector(events, {
    holdAdvance: voiceAdvanceHold,
    resetKey: runId,
  });
  const voice = useLiveVoiceStream(runId, {
    currentEventId: director.currentEventId,
    enabled: Boolean(runId),
    isPaused: director.isPaused,
  });
  const voiceCurrentItem = voice.currentItem;
  const unlockVoiceAudio = voice.unlockAudio;
  useEffect(() => {
    if (!runId) {
      return;
    }

    void unlockVoiceAudio();
  }, [runId, unlockVoiceAudio]);
  useEffect(() => {
    const shouldHold = isVoicePlaybackBlocking(
      voiceCurrentItem,
      director.currentEventId,
    );
    // Voice playback depends on the current director event, so this feeds the
    // next render's hold flag back into the director without marking a user pause.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setVoiceAdvanceHold((current) =>
      current === shouldHold ? current : shouldHold,
    );
  }, [director.currentEventId, voiceCurrentItem]);
  const currentEventId = director.currentEventId;
  const stageEvents = useMemo(() => {
    if (currentEventId === null) {
      return EMPTY_EVENTS;
    }

    return events.filter((event) => event.id <= currentEventId);
  }, [events, currentEventId]);
  const phaseSegments = useMemo(
    () => buildLivePhaseSegments(events, currentEventId),
    [events, currentEventId],
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
  const liveNavStatus = deriveLiveNavStatus({
    backlogCount: director.backlogCount,
    connectionState,
    hasCompletedTerminalEvent: terminalEvent?.type === "game_completed",
    hasFailedTerminalEvent: terminalEvent?.type === "game_failed",
    isPaused: director.isPaused,
    runStatus: run?.status ?? "queued",
    speed: director.speed,
  });
  const handleDebugPanelOpenChange = (isOpen: boolean) => {
    setIsDebugPanelOpen(isOpen);
    if (!isOpen) {
      debugPanelButtonRef.current?.focus();
    }
  };
  const topNavCommands = null;
  const topNavActions = run ? (
    <>
      {terminalEvent ? (
        <ArenaNavButton to={`/games/${run.session_id}`}>
          查看完整复盘
        </ArenaNavButton>
      ) : null}
      <LiveNavDebugPanelButton
        isOpen={isDebugPanelOpen}
        onClick={() => setIsDebugPanelOpen((value) => !value)}
        ref={debugPanelButtonRef}
      />
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
          debugPanelOpen={isDebugPanelOpen}
          director={director}
          events={stageEvents}
          godViewState={godViewState}
          mode="live"
          onDebugPanelOpenChange={handleDebugPanelOpenChange}
          onSelectPhase={(segment) =>
            director.seekToEventId(segment.startEventId)
          }
          phaseSegments={phaseSegments}
          spectatorState={spectatorState}
        />
      </main>
    </>
  );
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
