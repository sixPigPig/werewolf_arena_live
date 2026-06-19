import {
  useMutation,
  useQuery,
} from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  createGameRun,
  hasPlayerConfig,
  listPlayerProfiles,
  listRuleSets,
  randomFillEmptySeats,
  removeInvalidProfileRefs,
  resizeLineupForPlayerCount,
  type PlayerConfig,
  type RuleSetSummary,
  type VirtualPlayerProfile,
} from "@werewolf-arena/game-client";

export function GamesPage() {
  const navigate = useNavigate();
  const [selectedRuleSetId, setSelectedRuleSetId] = useState("");
  const [playerConfigs, setPlayerConfigs] = useState<PlayerConfig[]>([]);
  const [seed, setSeed] = useState("");
  const [maxRounds, setMaxRounds] = useState("8");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [shortage, setShortage] = useState(false);
  const [activeSeat, setActiveSeat] = useState(1);
  const [isProfileDrawerOpen, setIsProfileDrawerOpen] = useState(false);
  const [pendingProfileId, setPendingProfileId] = useState<string | null>(null);
  const [profileSearch, setProfileSearch] = useState("");
  const [favoriteFilter, setFavoriteFilter] = useState<"all" | "favorite">("all");
  const [profileStrategyFilter, setProfileStrategyFilter] = useState("all");

  const ruleSetsQuery = useQuery({
    queryKey: ["rule-sets"],
    queryFn: listRuleSets,
  });
  const playerProfilesQuery = useQuery({
    queryKey: ["player-profiles"],
    queryFn: listPlayerProfiles,
  });
  const createGameRunMutation = useMutation({
    mutationFn: (request: Parameters<typeof createGameRun>[0]) =>
      createGameRun(request),
    onSuccess: (run) => navigate(`/games/${run.run_id}/live`),
  });

  const ruleSets = useMemo(
    () => ruleSetsQuery.data?.rule_sets ?? [],
    [ruleSetsQuery.data?.rule_sets],
  );
  const profiles = useMemo(
    () => playerProfilesQuery.data?.profiles ?? [],
    [playerProfilesQuery.data?.profiles],
  );
  const selectedRuleSet =
    ruleSets.find((ruleSet) => ruleSet.id === selectedRuleSetId) ??
    ruleSets[0] ??
    null;
  const validProfileIds = useMemo(
    () => new Set(profiles.map((profile) => profile.id)),
    [profiles],
  );
  const playerCount = selectedRuleSet?.player_count ?? 0;
  const visiblePlayerConfigs = useMemo(
    () => {
      const validConfigs = removeInvalidProfileRefs(
        playerConfigs,
        validProfileIds,
      );

      return selectedRuleSet
        ? resizeLineupForPlayerCount(validConfigs, selectedRuleSet.player_count)
            .configs
        : validConfigs;
    },
    [playerConfigs, selectedRuleSet, validProfileIds],
  );
  const selectedProfilesBySeat = useMemo(() => {
    const profilesById = new Map(profiles.map((profile) => [profile.id, profile]));

    return new Map(
      visiblePlayerConfigs.map((config) => [
        config.seat,
        config.profile_id ? profilesById.get(config.profile_id) ?? null : null,
      ]),
    );
  }, [profiles, visiblePlayerConfigs]);
  const safeActiveSeat = clampSeat(activeSeat, playerCount);
  const activeSeatProfile = selectedProfilesBySeat.get(safeActiveSeat) ?? null;
  const pendingProfile =
    profiles.find((profile) => profile.id === pendingProfileId) ?? null;
  const strategyFilterOptions = useMemo(
    () => getStrategyFilterOptions(profiles),
    [profiles],
  );
  const filteredProfiles = useMemo(
    () =>
      filterProfiles(profiles, {
        favoriteFilter,
        search: profileSearch,
        strategy: profileStrategyFilter,
      }),
    [favoriteFilter, profileSearch, profileStrategyFilter, profiles],
  );
  const isLoading = ruleSetsQuery.isPending || playerProfilesQuery.isPending;
  const isSubmitDisabled =
    isLoading ||
    ruleSetsQuery.isError ||
    playerProfilesQuery.isError ||
    !selectedRuleSet ||
    createGameRunMutation.isPending;

  function handleRuleSetChange(ruleSetId: string) {
    const nextRuleSet = ruleSets.find((ruleSet) => ruleSet.id === ruleSetId);
    setSelectedRuleSetId(ruleSetId);
    setValidationError(null);
    setShortage(false);

    if (nextRuleSet) {
      setActiveSeat((currentSeat) =>
        clampSeat(currentSeat, nextRuleSet.player_count),
      );
      setPlayerConfigs((currentConfigs) =>
        resizeLineupForPlayerCount(
          removeInvalidProfileRefs(currentConfigs, validProfileIds),
          nextRuleSet.player_count,
        ).configs,
      );
    }
  }

  function assignProfileToActiveSeat(profileId: string) {
    setValidationError(null);
    setShortage(false);
    setPlayerConfigs((currentConfigs) =>
      upsertSeatProfile(currentConfigs, safeActiveSeat, profileId),
    );
  }

  function openProfileDrawer(seat: number) {
    const profile = selectedProfilesBySeat.get(seat) ?? null;
    setActiveSeat(seat);
    setPendingProfileId(profile?.id ?? null);
    setProfileSearch("");
    setFavoriteFilter("all");
    setProfileStrategyFilter("all");
    setValidationError(null);
    setShortage(false);
    setIsProfileDrawerOpen(true);
  }

  function closeProfileDrawer() {
    setIsProfileDrawerOpen(false);
    setPendingProfileId(null);
  }

  function confirmPendingProfile() {
    if (!pendingProfileId) {
      return;
    }
    assignProfileToActiveSeat(pendingProfileId);
    setIsProfileDrawerOpen(false);
    setPendingProfileId(null);
  }

  function fillEmptySeats(options?: { favoritesOnly?: boolean }) {
    if (!selectedRuleSet) {
      return;
    }
    setValidationError(null);
    setShortage(false);
    setPlayerConfigs(
      randomFillEmptySeats(
        visiblePlayerConfigs,
        profiles,
        selectedRuleSet.player_count,
        options,
      ),
    );
  }

  function handleSubmit() {
    if (!selectedRuleSet) {
      return;
    }

    const parsedMaxRounds = Number(maxRounds);
    if (
      !maxRounds ||
      !Number.isInteger(parsedMaxRounds) ||
      parsedMaxRounds < 1 ||
      parsedMaxRounds > 20
    ) {
      setValidationError("最大轮数必须是 1 到 20 的整数");
      setShortage(false);
      return;
    }

    const normalizedBaseConfigs = normalizePlayerConfigs(
      visiblePlayerConfigs,
      selectedRuleSet.player_count,
    );
    const filledPlayerConfigs = normalizePlayerConfigs(
      randomFillEmptySeats(
        normalizedBaseConfigs,
        profiles,
        selectedRuleSet.player_count,
      ),
      selectedRuleSet.player_count,
    );
    const selectedProfileCount = new Set(
      filledPlayerConfigs
        .map((config) => config.profile_id)
        .filter((profileId): profileId is string => Boolean(profileId)),
    ).size;

    if (selectedProfileCount < selectedRuleSet.player_count) {
      setShortage(true);
      setValidationError(null);
      setPlayerConfigs(filledPlayerConfigs);
      return;
    }

    setShortage(false);
    setValidationError(null);
    setPlayerConfigs(filledPlayerConfigs);
    createGameRunMutation.mutate({
      rule_set_id: selectedRuleSet.id,
      seed: seed ? Number(seed) : null,
      max_rounds: parsedMaxRounds,
      player_configs: filledPlayerConfigs,
    });
  }

  return (
    <main className="mobile-page" data-testid="mobile-games-page">
      <header className="mobile-page-section">
        <h1>移动大厅</h1>
        <p>选择规则和虚拟玩家，发起一局新的狼人杀对局。</p>
      </header>

      {validationError ? (
        <p className="mobile-status-banner" role="alert">
          {validationError}
        </p>
      ) : null}
      {shortage ? (
        <p className="mobile-status-banner" role="alert">
          玩家库玩家不足
        </p>
      ) : null}
      {createGameRunMutation.isError ? (
        <p className="mobile-status-banner" role="alert">
          无法发起对局
        </p>
      ) : null}

      <section aria-labelledby="mobile-rule-title" className="mobile-page-section">
        <h2 id="mobile-rule-title">规则</h2>
        {ruleSetsQuery.isError ? <p>规则加载失败</p> : null}
        <div className="mobile-rule-list">
          {ruleSets.map((ruleSet) => (
            <label className="mobile-card" key={ruleSet.id}>
              <input
                checked={selectedRuleSet?.id === ruleSet.id}
                name="mobile-rule-set"
                onChange={() => handleRuleSetChange(ruleSet.id)}
                type="radio"
                value={ruleSet.id}
              />
              <span>
                <strong>{ruleSet.name}</strong>
                <span>{ruleSet.role_summary ?? `${ruleSet.player_count} 人局`}</span>
              </span>
            </label>
          ))}
          {isLoading ? <p>加载中</p> : null}
        </div>
      </section>

      {selectedRuleSet ? (
        <>
          <section aria-labelledby="mobile-seat-title" className="mobile-page-section">
            <h2 id="mobile-seat-title">席位</h2>
            <div className="mobile-seat-grid">
              {Array.from({ length: playerCount }, (_, index) => index + 1).map(
                (seat) => {
                  const profile = selectedProfilesBySeat.get(seat);

                  return (
                    <button
                      className={[
                        "mobile-seat-button",
                        safeActiveSeat === seat ? "mobile-seat-button-active" : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                      aria-pressed={safeActiveSeat === seat}
                      key={seat}
                      onClick={() => setActiveSeat(seat)}
                      type="button"
                    >
                      <span>{seat} 号位</span>
                      <strong>{profile?.display_name ?? "待选择"}</strong>
                    </button>
                  );
                },
              )}
            </div>
          </section>

          <section aria-labelledby="mobile-profile-title" className="mobile-page-section">
            <h2 id="mobile-profile-title">玩家库</h2>
            {playerProfilesQuery.isError ? <p>玩家库加载失败</p> : null}
            <div className="mobile-choice-row">
              {profiles.map((profile) => (
                <button
                  className="mobile-button"
                  key={profile.id}
                  onClick={() => assignProfileToActiveSeat(profile.id)}
                  type="button"
                >
                  {profile.display_name}
                </button>
              ))}
            </div>
          </section>
        </>
      ) : null}

      <section aria-labelledby="mobile-create-title" className="mobile-page-section">
        <h2 id="mobile-create-title">设置</h2>
        <label className="mobile-card">
          <span>种子</span>
          <input
            inputMode="numeric"
            onChange={(event) => setSeed(event.target.value)}
            placeholder="随机"
            type="number"
            value={seed}
          />
        </label>
        <label className="mobile-card">
          <span>最大轮数</span>
          <input
            inputMode="numeric"
            max={20}
            min={1}
            onChange={(event) => {
              setMaxRounds(event.target.value);
              setValidationError(null);
            }}
            type="number"
            value={maxRounds}
          />
        </label>
      </section>

      <div className="mobile-action-bar">
        <button
          className="mobile-button"
          disabled={!selectedRuleSet}
          onClick={() => fillEmptySeats()}
          type="button"
        >
          随机补齐
        </button>
        <button
          className="mobile-button"
          disabled={!selectedRuleSet}
          onClick={() => fillEmptySeats({ favoritesOnly: true })}
          type="button"
        >
          收藏补齐
        </button>
        <button
          className="mobile-button"
          onClick={() => {
            setPlayerConfigs([]);
            setShortage(false);
            setValidationError(null);
          }}
          type="button"
        >
          清空席位
        </button>
        <button
          className="mobile-button mobile-button-primary"
          disabled={isSubmitDisabled}
          onClick={handleSubmit}
          type="button"
        >
          {createGameRunMutation.isPending ? "发起中" : "发起对局"}
        </button>
      </div>
    </main>
  );
}

function upsertSeatProfile(
  configs: PlayerConfig[],
  seat: number,
  profileId: string,
) {
  return configs
    .filter(
      (config) => config.seat !== seat && config.profile_id !== profileId,
    )
    .concat({ seat, profile_id: profileId })
    .sort((left, right) => left.seat - right.seat);
}

function normalizePlayerConfigs(configs: PlayerConfig[], playerCount: number) {
  return configs
    .filter((config) => config.seat >= 1 && config.seat <= playerCount)
    .map((config) => {
      const normalized: PlayerConfig = { seat: config.seat };
      if (config.profile_id) normalized.profile_id = config.profile_id;
      if (config.model?.trim()) normalized.model = config.model.trim();
      if (config.personality_id) normalized.personality_id = config.personality_id;
      if (config.appearance_id) normalized.appearance_id = config.appearance_id;
      return normalized;
    })
    .filter((config) => hasPlayerConfig(config))
    .sort((left, right) => left.seat - right.seat);
}

function clampSeat(seat: number, playerCount: number) {
  return seat >= 1 && seat <= playerCount ? seat : 1;
}

type ProfileFilters = {
  favoriteFilter: "all" | "favorite";
  search: string;
  strategy: string;
};

function filterProfiles(
  profiles: VirtualPlayerProfile[],
  filters: ProfileFilters,
) {
  const search = filters.search.trim().toLowerCase();

  return profiles.filter((profile) => {
    if (filters.favoriteFilter === "favorite" && !profile.favorite) {
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

function profileMatchesSearch(profile: VirtualPlayerProfile, search: string) {
  return [
    profile.display_name,
    profile.model,
    profile.personality_id,
    profile.personality_text,
    profile.short_description,
    profile.strategy_profile,
    ...profile.tags,
  ]
    .filter(Boolean)
    .some((value) => value.toLowerCase().includes(search));
}

function getStrategyFilterOptions(profiles: VirtualPlayerProfile[]) {
  return [...new Set(profiles.map((profile) => profile.strategy_profile))]
    .filter(Boolean)
    .sort((left, right) => left.localeCompare(right));
}

function getRuleTags(ruleSet: RuleSetSummary) {
  const tags = [
    ...(ruleSet.rule_tags ?? []),
    ruleSet.complexity,
    ruleSet.estimated_duration,
  ].filter((tag): tag is string => Boolean(tag));

  return tags.slice(0, 3);
}

function formatStrategyLabel(strategy: string) {
  const strategyLabels: Record<string, string> = {
    analysis: "分析型",
    balanced: "均衡型",
    deceptive: "策略型",
    defensive: "防御型",
    aggressive: "进攻型",
  };

  return strategyLabels[strategy] ?? strategy;
}

function getProfileDescription(profile: VirtualPlayerProfile) {
  return (
    profile.short_description ||
    profile.personality_text ||
    profile.model ||
    "暗夜牌局候选人"
  );
}
