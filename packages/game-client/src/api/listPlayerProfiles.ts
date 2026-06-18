import { apiFetch } from "./client";
import type { PlayerProfilesResponse } from "../types";

export function listPlayerProfiles(): Promise<PlayerProfilesResponse> {
  return apiFetch<PlayerProfilesResponse>("/api/v1/player-profiles");
}
