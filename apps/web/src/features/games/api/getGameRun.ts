import { apiFetch } from "../../../api/client";
import type { GameRun } from "../types";

export function getGameRun(runId: string): Promise<GameRun> {
  return apiFetch<GameRun>(`/api/v1/games/runs/${runId}`);
}
