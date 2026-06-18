import { apiFetch } from "./client";
import type {
  CreateGameRunRequest,
  GamePlaybackResponse,
  GameRun,
  GameSessionsResponse,
  ModelOptionsResponse,
  RuleSetsResponse,
} from "./types";

export function listGames() {
  return apiFetch<GameSessionsResponse>("/api/v1/games");
}

export function listRuleSets() {
  return apiFetch<RuleSetsResponse>("/api/v1/games/rule-sets");
}

export function listModelOptions() {
  return apiFetch<ModelOptionsResponse>("/api/v1/games/model-options");
}

export function createGameRun(request: CreateGameRunRequest) {
  return apiFetch<GameRun>("/api/v1/games/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

export function getGameRun(runId: string) {
  return apiFetch<GameRun>(`/api/v1/games/runs/${runId}`);
}

export function resumeGameRun(sessionId: string) {
  return apiFetch<GameRun>(`/api/v1/games/${sessionId}/resume`, {
    method: "POST",
  });
}

export function getGamePlayback(sessionId: string) {
  return apiFetch<GamePlaybackResponse>(`/api/v1/games/${sessionId}/playback`);
}
