import { apiFetch } from "../../../api/client";
import type { GamePlayback } from "../types";

export function getGamePlayback(sessionId: string): Promise<GamePlayback> {
  return apiFetch<GamePlayback>(`/api/v1/games/${sessionId}/playback`);
}
