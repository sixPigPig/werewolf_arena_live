import { apiFetch } from "./client";
import { withFreshPublicSession } from "./publicSession";
import type { GamePlayback, PlaybackVoiceUtterance } from "../types";

type GamePlaybackResponse = Omit<GamePlayback, "voices"> & {
  voices?: GamePlayback["voices"];
};

export type GamePlaybackAudience = "player_public" | "spectator_god_view";

export async function getGamePlayback(
  sessionId: string,
  audience: GamePlaybackAudience = "player_public",
): Promise<GamePlayback> {
  const path =
    audience === "spectator_god_view"
      ? `/api/v1/games/${sessionId}/god-view/playback`
      : `/api/v1/games/${sessionId}/playback`;
  const playback =
    audience === "spectator_god_view"
      ? await withFreshPublicSession(() =>
          apiFetch<GamePlaybackResponse>(path, { credentials: "include" }),
        )
      : await apiFetch<GamePlaybackResponse>(path);

  return { ...playback, voices: playback.voices ?? [] };
}

export async function getGamePlaybackVoice(
  sessionId: string,
  utteranceId: string,
  audience: GamePlaybackAudience = "player_public",
): Promise<PlaybackVoiceUtterance> {
  const encodedSessionId = encodeURIComponent(sessionId);
  const encodedUtteranceId = encodeURIComponent(utteranceId);
  const path =
    audience === "spectator_god_view"
      ? `/api/v1/games/${encodedSessionId}/god-view/playback/voices/${encodedUtteranceId}`
      : `/api/v1/games/${encodedSessionId}/playback/voices/${encodedUtteranceId}`;
  return audience === "spectator_god_view"
    ? withFreshPublicSession(() =>
        apiFetch<PlaybackVoiceUtterance>(path, { credentials: "include" }),
      )
    : apiFetch<PlaybackVoiceUtterance>(path);
}
