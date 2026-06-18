import { apiFetch } from "./client";
import type { GameReplay, RawGameReplayResponse } from "../types";

import { normalizeGameReplay } from "../replay/adapters";

export async function getGameDetail(sessionId: string): Promise<GameReplay> {
  const response = await apiFetch<RawGameReplayResponse>(
    `/api/v1/games/${sessionId}`,
  );
  return normalizeGameReplay(response);
}
