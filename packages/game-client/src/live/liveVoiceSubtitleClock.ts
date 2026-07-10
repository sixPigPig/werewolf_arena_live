import type {
  LiveVoiceQueueItem,
  LiveVoiceSubtitle,
  LiveVoiceSubtitleCue,
} from "./liveVoiceStream";

export const SUBTITLE_CLOCK_POLL_INTERVAL_MS = 50;
export const SUBTITLE_CUE_LEAD_MS = 40;

export type LiveVoiceSubtitleClock = {
  elapsedMs: number;
  utteranceId: string;
} | null;

export function isPcmAudioFormat(audioFormat: string) {
  return audioFormat.toLowerCase() === "pcm";
}

export function subtitleElapsedMsForItem({
  audio,
  context,
  item,
  pcmStartTimes,
}: {
  audio: HTMLAudioElement | null;
  context: AudioContext | null;
  item: LiveVoiceQueueItem;
  pcmStartTimes: Map<string, number>;
}) {
  if (isPcmAudioFormat(item.audioFormat)) {
    if (!context) {
      return null;
    }
    const startTime = pcmStartTimes.get(item.utteranceId);
    if (startTime === undefined) {
      return null;
    }
    return Math.max(0, Math.round((context.currentTime - startTime) * 1000));
  }

  if (!audio) {
    return null;
  }
  return Math.max(0, Math.round(audio.currentTime * 1000));
}

export function currentSubtitleForItem({
  isPaused,
  item,
  subtitleClock,
}: {
  isPaused: boolean;
  item: LiveVoiceQueueItem | null;
  subtitleClock: LiveVoiceSubtitleClock;
}): LiveVoiceSubtitle | null {
  if (
    isPaused ||
    !item ||
    item.status !== "playing" ||
    item.subtitleCues.length === 0 ||
    subtitleClock?.utteranceId !== item.utteranceId
  ) {
    return null;
  }

  const text = subtitleTextForElapsedMs(item.subtitleCues, subtitleClock.elapsedMs);
  if (!text) {
    return null;
  }

  return {
    speakerKind: item.speakerKind,
    speakerName: item.speakerName,
    text,
    utteranceId: item.utteranceId,
  };
}

export function subtitleTextForElapsedMs(
  cues: LiveVoiceSubtitleCue[],
  elapsedMs: number,
) {
  return cues
    .filter((cue) => cue.startMs <= elapsedMs + SUBTITLE_CUE_LEAD_MS)
    .map((cue) => cue.text)
    .join("")
    .trim();
}
