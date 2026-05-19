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
import type { LiveSpectatorState } from "../liveSpectator";
import type { LiveGameEvent } from "../types";
import { GodViewBottomBoard } from "./GodViewBottomBoard";
import { GodViewIntelPanel } from "./GodViewIntelPanel";
import { GodViewSituationPanel } from "./GodViewSituationPanel";
import { GodViewTopBar } from "./GodViewTopBar";
import { LiveDebugTraceRail } from "./LiveDebugTraceRail";
import { LiveDirectorStage } from "./LiveDirectorStage";

type LiveStageExperienceProps = {
  director: UseLiveDirectorResult;
  events: LiveGameEvent[];
  godViewState: GodViewState;
  mode: "live" | "playback";
  spectatorState: LiveSpectatorState;
};

export function LiveStageExperience({
  director,
  events,
  godViewState,
  mode,
  spectatorState,
}: LiveStageExperienceProps) {
  const [autoFollow, setAutoFollow] = useState(true);
  const [manualFocusName, setManualFocusName] = useState<string | null>(null);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const traces = useMemo(() => buildLiveDebugTraces(events), [events]);
  const autoFocusName =
    director.currentCue?.actor ?? spectatorState.activePlayerName;
  const focusedPlayerName = autoFollow
    ? autoFocusName
    : manualFocusName ?? autoFocusName;
  const selectTrace = (trace: LiveDebugTrace | null) => {
    if (!trace) {
      setSelectedTraceId(null);
      return;
    }

    setSelectedTraceId(trace.id);
    const focusName = trace.actor ?? trace.relatedPlayers[0] ?? null;
    if (focusName) {
      setAutoFollow(false);
      setManualFocusName(focusName);
    }
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
        right={
          <GodViewIntelPanel
            debugRail={
              <LiveDebugTraceRail
                onSelectTrace={selectTrace}
                selectedTraceId={selectedTraceId}
                traces={traces}
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
            onSelectPlayer={(name) => {
              setAutoFollow(false);
              setManualFocusName(name);
            }}
            players={spectatorState.players}
          />
        }
        top={<GodViewTopBar state={godViewState} />}
      />
    </LivePageShell>
  );
}
