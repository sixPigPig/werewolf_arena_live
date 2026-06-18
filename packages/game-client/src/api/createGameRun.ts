import { apiFetch } from "./client";
import type { CreateGameRunRequest, GameRun } from "../types";

export function createGameRun(request: CreateGameRunRequest): Promise<GameRun> {
  return apiFetch<GameRun>("/api/v1/games/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}
