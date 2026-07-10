import { ApiError, apiFetch } from "./client";
import type {
  PlayerProfileFavoriteMutationResponse,
  PlayerProfileFavoritesResponse,
} from "../types";
import { clearPublicSessionCache, ensurePublicSession } from "./publicSession";

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

async function withFreshPublicSession<T>(
  request: (session: Awaited<ReturnType<typeof ensurePublicSession>>) => Promise<T>,
): Promise<T> {
  const session = await ensurePublicSession();
  try {
    return await request(session);
  } catch (error) {
    if (!(error instanceof ApiError) || (error.status !== 401 && error.status !== 403)) {
      throw error;
    }

    clearPublicSessionCache(session);
    return request(await ensurePublicSession());
  }
}
