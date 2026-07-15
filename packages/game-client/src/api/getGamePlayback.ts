import { apiFetch } from "./client";
import { withFreshPublicSession } from "./publicSession";
import type { GamePlayback } from "../types";

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
