import type {
  deriveGodViewState,
  deriveLiveNarrativeState,
} from "@werewolf-arena/game-client";

type GodViewState = ReturnType<typeof deriveGodViewState>;
type LiveNarrativeState = ReturnType<typeof deriveLiveNarrativeState>;

export const PUBLIC_SPEECH_ACTIONS = [
  "debate",
  "sheriff_speech",
  "sheriff_pk_speech",
] as const;

export type MobileLiveSubtitle = {
  speakerName: string;
  text: string;
  tone: "judge" | "player";
  colorIndex: number;
};

const PLAYER_COLOR_COUNT = 8;
const DEFAULT_SUBTITLE_LINE_LENGTH = 18;
const SUBTITLE_CHARS_PER_SECOND = 5;
const SUBTITLE_MIN_SEGMENT_MS = 1800;
const SUBTITLE_MAX_SEGMENT_MS = 4200;

export function deriveMobileLiveSubtitle({
  godViewState,
  narrativeState,
}: {
  godViewState: Pick<GodViewState, "players">;
  narrativeState: LiveNarrativeState;
}): MobileLiveSubtitle | null {
  const cue = narrativeState.cue;

  if (cue.kind === "player-speaking") {
    const text = cue.speechText.trim();
    if (!text) {
      return null;
    }

    const speakerName =
      cue.actorName?.trim() || narrativeState.speaker?.name || "当前玩家";

    return {
      speakerName,
      text,
      tone: "player",
      colorIndex: playerColorIndex(speakerName, godViewState.players),
    };
  }

  if (
    cue.kind === "judge" ||
    (cue.kind === "player-thinking" && isPublicSpeechAction(cue.action))
  ) {
    const text = cue.judgeLine.trim();
    if (!text) {
      return null;
    }

    return {
      speakerName: "法官",
      text,
      tone: "judge",
      colorIndex: 0,
    };
  }

  return null;
}

export function splitMobileSubtitleText(
  text: string,
  maxLineLength = DEFAULT_SUBTITLE_LINE_LENGTH,
): string[] {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return [];
  }

  const phrases =
    normalized.match(/[^，。！？；,.!?;]+[，。！？；,.!?;]?/g) ?? [normalized];
  const segments: string[] = [];
  let currentSegment = "";

  for (const phrase of phrases) {
    for (const piece of chunkByLength(phrase, maxLineLength)) {
      const nextSegment = currentSegment + piece;
      if (
        currentSegment &&
        Array.from(nextSegment).length > maxLineLength
      ) {
        segments.push(currentSegment);
        currentSegment = piece;
      } else {
        currentSegment = nextSegment;
      }
    }
  }

  if (currentSegment) {
    segments.push(currentSegment);
  }

  return segments;
}

export function subtitleSegmentDurationMs(segment: string): number {
  const readableLength = Math.max(1, Array.from(segment.trim()).length);
  const duration = Math.round(
    (readableLength / SUBTITLE_CHARS_PER_SECOND) * 1000,
  );

  return Math.min(
    SUBTITLE_MAX_SEGMENT_MS,
    Math.max(SUBTITLE_MIN_SEGMENT_MS, duration),
  );
}

function isPublicSpeechAction(action: string | null) {
  return PUBLIC_SPEECH_ACTIONS.includes(
    action as (typeof PUBLIC_SPEECH_ACTIONS)[number],
  );
}

function playerColorIndex(
  speakerName: string,
  players: Pick<GodViewState["players"][number], "name" | "seatNumber">[],
) {
  const player = players.find((item) => item.name === speakerName);
  if (player && Number.isFinite(player.seatNumber)) {
    return modulo(player.seatNumber - 1, PLAYER_COLOR_COUNT);
  }

  return modulo(hashSpeakerName(speakerName), PLAYER_COLOR_COUNT);
}

function hashSpeakerName(value: string) {
  return Array.from(value).reduce(
    (hash, character) => hash + character.codePointAt(0)!,
    0,
  );
}

function modulo(value: number, divisor: number) {
  return ((value % divisor) + divisor) % divisor;
}

function chunkByLength(value: string, maxLength: number): string[] {
  const characters = Array.from(value);
  if (characters.length <= maxLength) {
    return [value];
  }

  const chunks: string[] = [];
  for (let index = 0; index < characters.length; index += maxLength) {
    chunks.push(characters.slice(index, index + maxLength).join(""));
  }

  return chunks;
}
