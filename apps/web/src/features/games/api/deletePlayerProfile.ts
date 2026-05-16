import { apiFetch } from "../../../api/client";

export function deletePlayerProfile(profileId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/player-profiles/${profileId}`, {
    method: "DELETE",
  });
}
