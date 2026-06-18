import { apiFetch } from "./client";
import type { PlayerProfileListResponse } from "./types";

export function listPlayerProfiles() {
  return apiFetch<PlayerProfileListResponse>("/api/v1/player-profiles");
}
