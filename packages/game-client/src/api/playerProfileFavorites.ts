import { apiFetch } from "./client";
import type {
  PlayerProfileFavoriteMutationResponse,
  PlayerProfileFavoritesResponse,
} from "../types";
import { withFreshPublicSession } from "./publicSession";

const FAVORITES_PATH = "/api/v1/public/me/favorite-player-profiles";

export async function listPlayerProfileFavorites(): Promise<PlayerProfileFavoritesResponse> {
  return withFreshPublicSession(async () => {
    return apiFetch<PlayerProfileFavoritesResponse>(FAVORITES_PATH, {
      credentials: "include",
    });
  });
}

export async function favoritePlayerProfile(
  profileId: string,
): Promise<PlayerProfileFavoriteMutationResponse> {
  return writePlayerProfileFavorite(profileId, "PUT");
}

export async function unfavoritePlayerProfile(
  profileId: string,
): Promise<PlayerProfileFavoriteMutationResponse> {
  return writePlayerProfileFavorite(profileId, "DELETE");
}

async function writePlayerProfileFavorite(
  profileId: string,
  method: "DELETE" | "PUT",
) {
  return withFreshPublicSession(async (session) => {
    return apiFetch<PlayerProfileFavoriteMutationResponse>(
      `${FAVORITES_PATH}/${encodeURIComponent(profileId)}`,
      {
        credentials: "include",
        headers: { "X-CSRF-Token": session.csrf_token },
        method,
      },
    );
  });
}
