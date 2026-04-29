import { apiFetch } from "../../../api/client";
import type { GameRun } from "../types";

export function resumeGameRun(sessionId: string): Promise<GameRun> {
  return apiFetch<GameRun>(`/api/v1/games/${sessionId}/resume`, {
    method: "POST",
  });
}
