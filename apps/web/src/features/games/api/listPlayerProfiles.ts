import { apiFetch } from "../../../api/client";
import type { PlayerProfilesResponse } from "../types";

export function listPlayerProfiles(): Promise<PlayerProfilesResponse> {
  return apiFetch<PlayerProfilesResponse>("/api/v1/player-profiles");
}
