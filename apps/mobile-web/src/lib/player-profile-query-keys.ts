export const publicPlayerProfilesQueryKey = ["public-player-profiles"] as const;

export const publicPlayerProfileFavoritesQueryKey = [
  "public-player-profile-favorites",
] as const;

export function publicPlayerProfileQueryKey(profileId: string) {
  return ["public-player-profile", profileId] as const;
}
