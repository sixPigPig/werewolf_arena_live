import type {
  LiveGameEvent,
  VoicePlaybackCompletion,
} from "@werewolf-arena/game-client";

export function isVoicePlaybackBlocking(
  currentItem:
    | {
        sourceEventId: number;
        lastSourceEventId?: number;
        speechId?: string;
        status: string;
      }
    | null
    | undefined,
  currentEventId: number | null,
  currentSpeechId: string | undefined,
) {
  if (!currentItem || currentEventId === null) {
    return false;
  }
  if (currentItem.speechId) {
    if (!currentSpeechId || currentItem.speechId !== currentSpeechId) {
      return false;
    }
  } else if (currentItem.sourceEventId > currentEventId) {
    return false;
  }

  return currentItem.status !== "played" && currentItem.status !== "error";
}

export function mapVoiceCompletionToTimeline(
  events: LiveGameEvent[],
  completion: VoicePlaybackCompletion | null,
  currentRunId: string | undefined,
): VoicePlaybackCompletion | null {
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
    ...(completion.speechId ? { speechId: completion.speechId } : {}),
    sourceEventId: Math.min(...coveredTimelineIds),
    lastSourceEventId: Math.max(...coveredTimelineIds),
  };
}
