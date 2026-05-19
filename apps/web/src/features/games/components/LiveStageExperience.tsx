import { useMemo, useState } from "react";

import { Callout } from "../../../components/ui";
import { LivePageShell } from "../../../pages/components/LivePageShell";
import { LiveStageModule } from "../../../pages/components/LiveStageModule";
import type { UseLiveDirectorResult } from "../hooks/useLiveDirector";
import type { GodViewState } from "../liveGodView";
import {
  buildLiveDebugTraces,
  type LiveDebugTrace,
} from "../liveDebugTrace";
import { deriveLiveNarrativeState } from "../liveNarrative";
import type { LiveSpectatorState } from "../liveSpectator";
import type { LiveGameEvent } from "../types";
import { GodViewBottomBoard } from "./GodViewBottomBoard";
import { GodViewIntelPanel } from "./GodViewIntelPanel";
import { GodViewSituationPanel } from "./GodViewSituationPanel";
import { GodViewTopBar } from "./GodViewTopBar";
import { LiveDebugPanelDialog } from "./LiveDebugPanelDialog";
import { LiveDirectorStage } from "./LiveDirectorStage";

type LiveStageExperienceProps = {
  debugPanelOpen?: boolean;
  director: UseLiveDirectorResult;
  events: LiveGameEvent[];
  godViewState: GodViewState;
  mode: "live" | "playback";
  onDebugPanelOpenChange?: (isOpen: boolean) => void;
  spectatorState: LiveSpectatorState;
};

export function LiveStageExperience({
  debugPanelOpen = false,
  director,
  events,
  godViewState,
  mode,
  onDebugPanelOpenChange,
  spectatorState,
}: LiveStageExperienceProps) {
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const traces = useMemo(() => buildLiveDebugTraces(events), [events]);
  const selectedTrace =
    traces.find((trace) => trace.id === selectedTraceId) ?? null;
  const activePlayerName =
    director.currentCue?.actor ?? spectatorState.activePlayerName;
  const narrativeState = useMemo(
    () =>
      deriveLiveNarrativeState({
        cue: director.currentCue,
        events,
        godViewState,
        spectatorState,
      }),
    [director.currentCue, events, godViewState, spectatorState],
  );
  const selectTrace = (trace: LiveDebugTrace | null) => {
    setSelectedTraceId(trace?.id ?? null);
  };

  return (
    <LivePageShell>
      {mode === "playback" && events.length === 0 ? (
        <Callout.Root className="mb-3" color="amber" size="1" variant="soft">
          <Callout.Text>该对局没有可播放事件</Callout.Text>
        </Callout.Root>
      ) : null}
      <LiveStageModule
        bottom={<GodViewBottomBoard state={godViewState} />}
        left={<GodViewSituationPanel state={godViewState} />}
        right={<GodViewIntelPanel state={godViewState} />}
        stage={
          <LiveDirectorStage
            activePlayerName={activePlayerName}
            backlogCount={director.backlogCount}
            cue={director.currentCue}
            debugTrace={selectedTrace}
            godViewState={godViewState}
            isCatchingUp={director.isCatchingUp}
            narrativeState={narrativeState}
            players={spectatorState.players}
          />
        }
        top={<GodViewTopBar state={godViewState} />}
      />
      <LiveDebugPanelDialog
        isOpen={debugPanelOpen}
        onClose={() => onDebugPanelOpenChange?.(false)}
        onSelectTrace={selectTrace}
        selectedTraceId={selectedTraceId}
        traces={traces}
      />
    </LivePageShell>
  );
}
