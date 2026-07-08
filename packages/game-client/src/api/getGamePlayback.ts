import { apiFetch } from "./client";
import type { GamePlayback } from "../types";

type GamePlaybackResponse = Omit<GamePlayback, "voices"> & {
  voices?: GamePlayback["voices"];
};

export async function getGamePlayback(sessionId: string): Promise<GamePlayback> {
  const playback = await apiFetch<GamePlaybackResponse>(
    `/api/v1/games/${sessionId}/playback`,
  );

  return { ...playback, voices: playback.voices ?? [] };
}
