import { apiFetch } from "./client";
import type { GameSessionsResponse } from "../types";

export function listGames() {
  return apiFetch<GameSessionsResponse>("/api/v1/games");
}
