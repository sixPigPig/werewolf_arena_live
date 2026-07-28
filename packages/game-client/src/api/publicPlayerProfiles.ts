import { apiFetch } from "./client";
import type {
  PublicPlayerProfile,
  PublicPlayerProfileListResponse,
  PublicPlayerProfileWithFavorite,
} from "../types";

const PUBLIC_PLAYER_PROFILE_PAGE_SIZE = 100;

export async function listPublicPlayerProfiles(): Promise<PublicPlayerProfile[]> {
  const firstPage = await fetchPublicPlayerProfilePage(1);
  const remainingPageNumbers = Array.from(
    { length: Math.max(firstPage.pagination.pages - 1, 0) },
    (_, index) => index + 2,
  );
  const remainingPages = await Promise.all(
    remainingPageNumbers.map(fetchPublicPlayerProfilePage),
  );

  return [firstPage, ...remainingPages].flatMap((page) => page.items);
}

export function getPublicPlayerProfile(
  profileId: string,
): Promise<PublicPlayerProfile> {
  return apiFetch<PublicPlayerProfile>(
    `/api/v1/public/player-profiles/${encodeURIComponent(profileId)}`,
  );
}

export function mergePlayerProfileFavorites(
  profiles: PublicPlayerProfile[],
  favoriteProfileIds: Iterable<string>,
): PublicPlayerProfileWithFavorite[] {
  const favoriteIds = new Set(favoriteProfileIds);
  return profiles
    .map((profile) => ({
      ...profile,
      is_favorite: favoriteIds.has(profile.id),
    }))
    .sort(
      (left, right) =>
        Number(right.is_favorite) - Number(left.is_favorite) ||
        left.display_order - right.display_order ||
        left.id.localeCompare(right.id),
    );
}

function fetchPublicPlayerProfilePage(
  page: number,
): Promise<PublicPlayerProfileListResponse> {
  return apiFetch<PublicPlayerProfileListResponse>(
    `/api/v1/public/player-profiles?page=${page}&page_size=${PUBLIC_PLAYER_PROFILE_PAGE_SIZE}`,
  );
}
