import { apiFetch } from "./client";
import type { UpdatePlayerProfileRequest, VirtualPlayerProfile } from "../types";

export function updatePlayerProfile(
  profileId: string,
  request: UpdatePlayerProfileRequest,
): Promise<VirtualPlayerProfile> {
  return apiFetch<VirtualPlayerProfile>(
    `/api/v1/player-profiles/${profileId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
  );
}
