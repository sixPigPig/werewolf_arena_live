import {
  hasPlayerConfig,
  type PlayerConfig,
  type PlayerProfileFavoritesResponse,
  type PublicPlayerProfileWithFavorite,
} from "@werewolf-arena/game-client";

export type LineupLaunchStatus = {
  assignedCount: number;
  emptySeatCount: number;
  profileShortageCount: number;
  summaryText: string;
  ctaLabel: string;
  canLaunch: boolean;
};

export type ProfileFilters = {
  favoriteFilter: "all" | "favorite";
  search: string;
  strategy: string;
};

export function upsertSeatProfile(
  configs: PlayerConfig[],
  seat: number,
  profileId: string,
): PlayerConfig[] {
  return configs
    .filter(
      (config) => config.seat !== seat && config.profile_id !== profileId,
    )
    .concat({ seat, profile_id: profileId })
    .sort((left, right) => left.seat - right.seat);
}

export function getProfileSeatStatusLabel(
  assignedSeat: number | undefined,
  activeSeat: number,
) {
  if (!assignedSeat) {
    return null;
  }

  return assignedSeat === activeSeat
    ? "当前座位"
    : `已在 ${assignedSeat} 号座位`;
}

export function getProfileChoiceAriaLabel(
  activeSeat: number,
  profile: PublicPlayerProfileWithFavorite,
  seatStatusLabel: string | null,
) {
  return [
    `为 ${activeSeat} 号座位候选 ${profile.display_name}`,
    seatStatusLabel,
  ]
    .filter(Boolean)
    .join("，");
}

export function normalizePlayerConfigs(
  configs: PlayerConfig[],
  playerCount: number,
) {
  return configs
    .filter((config) => config.seat >= 1 && config.seat <= playerCount)
    .map((config) => {
      const normalized: PlayerConfig = { seat: config.seat };
      if (config.profile_id) normalized.profile_id = config.profile_id;
      if (config.model_provider?.trim()) {
        normalized.model_provider = config.model_provider.trim();
      }
      if (config.model?.trim()) normalized.model = config.model.trim();
      if (config.personality_id) normalized.personality_id = config.personality_id;
      if (config.appearance_id) normalized.appearance_id = config.appearance_id;
      return normalized;
    })
    .filter((config) => hasPlayerConfig(config))
    .sort((left, right) => left.seat - right.seat);
}

export function buildLineupLaunchStatus(
  configs: PlayerConfig[],
  profiles: PublicPlayerProfileWithFavorite[],
  playerCount: number,
): LineupLaunchStatus {
  const assignedProfileIds = new Set(
    configs
      .map((config) => config.profile_id)
      .filter((profileId): profileId is string => Boolean(profileId)),
  );
  const assignedCount = assignedProfileIds.size;
  const emptySeatCount = Math.max(playerCount - assignedCount, 0);
  const availableProfileCount = Math.max(profiles.length - assignedCount, 0);
  const profileShortageCount = Math.max(
    emptySeatCount - availableProfileCount,
    0,
  );
  const countPrefix = `已选 ${assignedCount}/${playerCount}`;
  const ctaLabel =
    playerCount === 0
      ? "等待规则"
      : emptySeatCount > 0
        ? `还差 ${emptySeatCount} 位`
        : "开始对局";

  if (playerCount === 0) {
    return {
      assignedCount,
      emptySeatCount,
      profileShortageCount: 0,
      summaryText: "等待规则加载",
      ctaLabel,
      canLaunch: false,
    };
  }

  if (profileShortageCount > 0) {
    return {
      assignedCount,
      emptySeatCount,
      profileShortageCount,
      summaryText: `${countPrefix} · 还差 ${profileShortageCount} 名玩家`,
      ctaLabel,
      canLaunch: false,
    };
  }

  if (emptySeatCount > 0) {
    return {
      assignedCount,
      emptySeatCount,
      profileShortageCount,
      summaryText: `${countPrefix} · 可自动补齐`,
      ctaLabel,
      canLaunch: false,
    };
  }

  return {
    assignedCount,
    emptySeatCount,
    profileShortageCount,
    summaryText: `${countPrefix} · 阵容已就绪`,
    ctaLabel,
    canLaunch: true,
  };
}

export function clampSeat(seat: number, playerCount: number) {
  return seat >= 1 && seat <= playerCount ? seat : 1;
}

export function findNextEmptySeat(
  configs: PlayerConfig[],
  playerCount: number,
  currentSeat: number,
) {
  const assignedSeats = new Set(
    configs
      .filter((config) => Boolean(config.profile_id))
      .map((config) => config.seat),
  );
  const seats = Array.from({ length: playerCount }, (_, index) => index + 1);
  const afterCurrent = seats.filter((seat) => seat > currentSeat);
  const beforeOrCurrent = seats.filter((seat) => seat <= currentSeat);

  return [...afterCurrent, ...beforeOrCurrent].find(
    (seat) => !assignedSeats.has(seat),
  );
}

export function hasNextEmptySeat(
  configs: PlayerConfig[],
  playerCount: number,
  currentSeat: number,
) {
  return findNextEmptySeat(configs, playerCount, currentSeat) !== undefined;
}

export function filterProfiles(
  profiles: PublicPlayerProfileWithFavorite[],
  filters: ProfileFilters,
) {
  const search = filters.search.trim().toLowerCase();

  return profiles.filter((profile) => {
    if (filters.favoriteFilter === "favorite" && !profile.is_favorite) {
      return false;
    }

    if (
      filters.strategy !== "all" &&
      profile.strategy_profile !== filters.strategy
    ) {
      return false;
    }

    if (!search) {
      return true;
    }

    return profileMatchesSearch(profile, search);
  });
}

export function updateFavoriteProfileIds(
  favorites: PlayerProfileFavoritesResponse | undefined,
  profileId: string,
  isFavorite: boolean,
) {
  if (!favorites) {
    return favorites;
  }

  const profileIds = new Set(favorites.profile_ids);
  if (isFavorite) {
    profileIds.add(profileId);
  } else {
    profileIds.delete(profileId);
  }
  return { profile_ids: [...profileIds] };
}

function profileMatchesSearch(
  profile: PublicPlayerProfileWithFavorite,
  search: string,
) {
  return [
    profile.display_name,
    profile.model,
    profile.personality_id,
    profile.personality_text,
    profile.short_description,
    profile.strategy_profile,
    ...(profile.tags ?? []),
  ]
    .filter(Boolean)
    .some((value) => value.toLowerCase().includes(search));
}

export function getStrategyFilterOptions(
  profiles: PublicPlayerProfileWithFavorite[],
) {
  return [...new Set(profiles.map((profile) => profile.strategy_profile))]
    .filter(Boolean)
    .sort((left, right) => left.localeCompare(right));
}

export function formatStrategyLabel(strategy: string) {
  const strategyLabels: Record<string, string> = {
    analysis: "分析型",
    balanced: "均衡型",
    deceptive: "策略型",
    defensive: "防御型",
    aggressive: "进攻型",
  };

  return strategyLabels[strategy] ?? strategy;
}
