import type {
  deriveGodViewState,
  deriveLiveNarrativeState,
  LiveVoiceSubtitle,
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

    const speakerKey =
      cue.actorName?.trim() || narrativeState.speaker?.name || "";
    const speakerName = playerSeatSubtitleName(
      speakerKey,
      godViewState.players,
    );

    return {
      speakerName,
      text,
      tone: "player",
      colorIndex: playerColorIndex(speakerKey || speakerName, godViewState.players),
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

export function voiceSubtitleToMobileSubtitle(
  subtitle: LiveVoiceSubtitle | null | undefined,
): MobileLiveSubtitle | null {
  if (!subtitle) {
    return null;
  }

  if (subtitle.speakerKind === "judge") {
    return {
      colorIndex: 0,
      speakerName: subtitle.speakerName,
      text: subtitle.text,
      tone: "judge",
    };
  }

  return {
    colorIndex: playerColorIndexFromSeatLabel(subtitle.speakerName),
    speakerName: subtitle.speakerName,
    text: subtitle.text,
    tone: "player",
  };
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

function playerSeatSubtitleName(
  speakerName: string,
  players: Pick<GodViewState["players"][number], "name" | "seatNumber">[],
) {
  const player = players.find((item) => item.name === speakerName);
  return player ? `${player.seatNumber}号玩家` : "当前玩家";
}

function hashSpeakerName(value: string) {
  return Array.from(value).reduce(
    (hash, character) => hash + character.codePointAt(0)!,
    0,
  );
}

function playerColorIndexFromSeatLabel(speakerName: string) {
  const seatMatch = speakerName.trim().match(/^(\d+)号玩家$/);
  if (!seatMatch) {
    return 0;
  }
  return modulo(Number(seatMatch[1]) - 1, PLAYER_COLOR_COUNT);
}

function modulo(value: number, divisor: number) {
  return ((value % divisor) + divisor) % divisor;
}
