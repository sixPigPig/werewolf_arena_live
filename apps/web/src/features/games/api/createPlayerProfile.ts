import { apiFetch } from "../../../api/client";
import type { PlayerProfileRequest, VirtualPlayerProfile } from "../types";

export function createPlayerProfile(
  request: PlayerProfileRequest,
): Promise<VirtualPlayerProfile> {
  return apiFetch<VirtualPlayerProfile>("/api/v1/player-profiles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}
