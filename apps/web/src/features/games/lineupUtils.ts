import type { PlayerConfig, VirtualPlayerProfile } from "./types";

export type DuplicateProfileSelection = {
  profileId: string;
  seats: number[];
};

export type LineupCount = {
  label: string;
  count: number;
};

export type LineupSummary = {
  assignedCount: number;
  emptySeatCount: number;
  favoriteCount: number;
  invalidSeatCount: number;
  modelCounts: LineupCount[];
  personalityCounts: LineupCount[];
};

type RandomFillOptions = {
  favoritesOnly?: boolean;
  random?: () => number;
};

export function applyProfileToSeat(
  configs: PlayerConfig[],
  seat: number,
  profileId: string,
) {
  if (
    configs.some(
      (config) => config.seat !== seat && config.profile_id === profileId,
    )
  ) {
    return configs;
  }

  const existing = configs.find((config) => config.seat === seat);
  return upsertSeatConfig(configs, {
    ...(existing ?? { seat }),
    seat,
    profile_id: profileId,
  });
}

export function clearSeat(configs: PlayerConfig[], seat: number) {
  return configs.filter((config) => config.seat !== seat);
}

export function clearAllSeats() {
  return [];
}

export function randomFillEmptySeats(
  configs: PlayerConfig[],
  profiles: VirtualPlayerProfile[],
  playerCount: number,
  options: RandomFillOptions = {},
) {
  const random = options.random ?? Math.random;
  const usedProfileIds = new Set(
    configs
      .map((config) => config.profile_id)
      .filter((profileId): profileId is string => Boolean(profileId)),
  );
  const seatsNeedingProfiles = Array.from(
    { length: playerCount },
    (_, index) => index + 1,
  ).filter(
    (seat) => !configs.some((config) => config.seat === seat && config.profile_id),
  );
  const availableProfiles = profiles.filter(
    (profile) =>
      !usedProfileIds.has(profile.id) && (!options.favoritesOnly || profile.favorite),
  );
  let nextConfigs = [...configs];
  const nextProfiles = [...availableProfiles];

  for (const seat of seatsNeedingProfiles) {
    if (nextProfiles.length === 0) {
      break;
    }

    const profileIndex = Math.min(
      Math.floor(random() * nextProfiles.length),
      nextProfiles.length - 1,
    );
    const [profile] = nextProfiles.splice(profileIndex, 1);
    if (!profile) {
      break;
    }
    const existingConfig = nextConfigs.find((config) => config.seat === seat);
    nextConfigs = upsertSeatConfig(nextConfigs, {
      ...existingConfig,
      seat,
      profile_id: profile.id,
    });
  }

  return sortConfigs(nextConfigs);
}

export function findDuplicateProfileSelections(
  configs: PlayerConfig[],
): DuplicateProfileSelection[] {
  const seatsByProfile = new Map<string, number[]>();

  configs.forEach((config) => {
    if (!config.profile_id) {
      return;
    }
    seatsByProfile.set(config.profile_id, [
      ...(seatsByProfile.get(config.profile_id) ?? []),
      config.seat,
    ]);
  });

  return [...seatsByProfile.entries()]
    .filter(([, seats]) => seats.length > 1)
    .map(([profileId, seats]) => ({ profileId, seats: [...seats].sort() }));
}

export function summarizeLineup(
  configs: PlayerConfig[],
  profiles: VirtualPlayerProfile[],
  playerCount: number,
): LineupSummary {
  const profileById = new Map(profiles.map((profile) => [profile.id, profile]));
  let assignedCount = 0;
  let favoriteCount = 0;
  let invalidSeatCount = 0;
  const modelCounts = new Map<string, number>();
  const personalityCounts = new Map<string, number>();

  configs.forEach((config) => {
    if (!config.profile_id) {
      return;
    }

    const profile = profileById.get(config.profile_id);
    if (!profile) {
      invalidSeatCount += 1;
      return;
    }

    assignedCount += 1;
    if (profile.favorite) {
      favoriteCount += 1;
    }
    incrementCount(modelCounts, config.model?.trim() || profile.model);
    incrementCount(personalityCounts, profile.personality_id);
  });

  return {
    assignedCount,
    emptySeatCount: Math.max(playerCount - assignedCount, 0),
    favoriteCount,
    invalidSeatCount,
    modelCounts: mapToSortedCounts(modelCounts),
    personalityCounts: mapToSortedCounts(personalityCounts),
  };
}

export function removeInvalidProfileRefs(
  configs: PlayerConfig[],
  validProfileIds: Set<string>,
) {
  return configs
    .map((config) => {
      if (!config.profile_id || validProfileIds.has(config.profile_id)) {
        return config;
      }

      const nextConfig = { ...config };
      delete nextConfig.profile_id;
      return hasPlayerConfig(nextConfig) ? nextConfig : null;
    })
    .filter((config): config is PlayerConfig => config !== null);
}

export function hasPlayerConfig(config: PlayerConfig) {
  return Boolean(
    config.profile_id ||
      config.model ||
      config.personality_id ||
      config.appearance_id,
  );
}

function upsertSeatConfig(configs: PlayerConfig[], nextConfig: PlayerConfig) {
  return sortConfigs(
    configs
      .filter((config) => config.seat !== nextConfig.seat)
      .concat(nextConfig),
  );
}

function sortConfigs(configs: PlayerConfig[]) {
  return [...configs].sort((left, right) => left.seat - right.seat);
}

function incrementCount(counts: Map<string, number>, label: string | undefined) {
  const normalizedLabel = label?.trim();
  if (!normalizedLabel) {
    return;
  }
  counts.set(normalizedLabel, (counts.get(normalizedLabel) ?? 0) + 1);
}

function mapToSortedCounts(counts: Map<string, number>) {
  return [...counts.entries()]
    .map(([label, count]) => ({ label, count }))
    .sort(
      (left, right) =>
        right.count - left.count || left.label.localeCompare(right.label),
    );
}
