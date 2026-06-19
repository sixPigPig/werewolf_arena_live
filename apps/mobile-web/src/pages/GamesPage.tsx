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
    <main className="mobile-page mobile-lobby-page" data-testid="mobile-games-page">
      <header className="mobile-lobby-hero">
        <div className="mobile-lobby-crest" aria-hidden="true">
          狼
        </div>
        <div className="mobile-lobby-hero-copy">
          <span>公平 · 推理 · 社交的暗夜决策</span>
          <h1>狼人杀对局大厅</h1>
          <p>选择规则，点亮座位，从卡牌库召集你的暗夜阵容。</p>
        </div>
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

      <section aria-labelledby="mobile-rule-title" className="mobile-lobby-section">
        <div className="mobile-lobby-section-heading">
          <h2 id="mobile-rule-title">规则选择</h2>
          {selectedRuleSet ? (
            <span>{selectedRuleSet.player_count} 人局</span>
          ) : null}
        </div>
        {ruleSetsQuery.isError ? <p>规则加载失败</p> : null}
        <div className="mobile-lobby-rule-scroll">
          {ruleSets.map((ruleSet) => {
            const isSelected = selectedRuleSet?.id === ruleSet.id;
            const ruleTags = getRuleTags(ruleSet);

            return (
              <label
                className={[
                  "mobile-lobby-rule-card",
                  isSelected ? "mobile-lobby-rule-card-active" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                key={ruleSet.id}
              >
                <input
                  checked={isSelected}
                  name="mobile-rule-set"
                  onChange={() => handleRuleSetChange(ruleSet.id)}
                  type="radio"
                  value={ruleSet.id}
                />
                <span className="mobile-lobby-rule-emblem" aria-hidden="true">
                  {isSelected ? "✓" : "✦"}
                </span>
                <strong>{ruleSet.name}</strong>
                <span>{ruleSet.role_summary ?? `${ruleSet.player_count} 人局`}</span>
                {ruleTags.length > 0 ? (
                  <span className="mobile-lobby-rule-tags">
                    {ruleTags.map((tag) => (
                      <em key={tag}>{tag}</em>
                    ))}
                  </span>
                ) : null}
              </label>
            );
          })}
          {isLoading ? <p>加载中</p> : null}
        </div>
      </section>

      {selectedRuleSet ? (
        <section aria-labelledby="mobile-seat-title" className="mobile-lobby-section">
          <div className="mobile-lobby-section-heading">
            <h2 id="mobile-seat-title">组建阵容</h2>
            <span>
              {selectedRuleSet.name} · {playerCount} 个座位
            </span>
          </div>
          <div className="mobile-lobby-seat-grid">
            {Array.from({ length: playerCount }, (_, index) => index + 1).map(
              (seat) => {
                const profile = selectedProfilesBySeat.get(seat);
                const isActive = safeActiveSeat === seat;

                return (
                  <button
                    aria-label={`选择 ${seat} 号座位，当前为 ${
                      profile?.display_name ?? "待选择"
                    }`}
                    aria-pressed={isActive}
                    className={[
                      "mobile-lobby-seat-card",
                      isActive ? "mobile-lobby-seat-card-active" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    key={seat}
                    onClick={() => openProfileDrawer(seat)}
                    type="button"
                  >
                    <span className="mobile-lobby-seat-avatar">
                      <span aria-hidden="true" />
                      {profile?.avatar_image_url ? (
                        <img
                          alt=""
                          onError={(event) => {
                            event.currentTarget.hidden = true;
                          }}
                          src={profile.avatar_image_url}
                        />
                      ) : null}
                    </span>
                    <span className="mobile-lobby-seat-label">{seat}号座位</span>
                    <strong>{profile?.display_name ?? "待选择"}</strong>
                  </button>
                );
              },
            )}
          </div>
          {playerProfilesQuery.isError ? (
            <p className="mobile-lobby-inline-error">玩家库加载失败</p>
          ) : null}
        </section>
      ) : null}

      <section aria-labelledby="mobile-create-title" className="mobile-lobby-section">
        <div className="mobile-lobby-section-heading">
          <h2 id="mobile-create-title">填充设置</h2>
          {activeSeatProfile ? <span>{activeSeatProfile.display_name}</span> : null}
        </div>
        <div className="mobile-lobby-settings-grid">
          <label className="mobile-lobby-field">
            <span>种子</span>
            <input
              inputMode="numeric"
              onChange={(event) => setSeed(event.target.value)}
              placeholder="随机"
              type="number"
              value={seed}
            />
          </label>
          <label className="mobile-lobby-field">
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
        </div>
      </section>

      <div className="mobile-action-bar mobile-lobby-action-bar">
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

      {isProfileDrawerOpen ? (
        <div className="mobile-profile-drawer-layer">
          <div
            aria-hidden="true"
            className="mobile-profile-drawer-backdrop"
            onClick={closeProfileDrawer}
          />
          <section
            aria-labelledby="mobile-profile-drawer-title"
            aria-modal="true"
            className="mobile-profile-drawer"
            role="dialog"
          >
            <div className="mobile-profile-drawer-handle" aria-hidden="true" />
            <div className="mobile-profile-drawer-heading">
              <div>
                <h2 id="mobile-profile-drawer-title">玩家卡牌库</h2>
                <p>当前选择：{safeActiveSeat}号座位</p>
              </div>
              <button
                aria-label="关闭玩家卡牌库"
                className="mobile-profile-drawer-close"
                onClick={closeProfileDrawer}
                type="button"
              >
                ×
              </button>
            </div>

            <div className="mobile-profile-drawer-filters">
              <label className="mobile-profile-search">
                <span>搜索玩家</span>
                <input
                  onChange={(event) => setProfileSearch(event.target.value)}
                  placeholder="搜索名称、标签、模型"
                  type="search"
                  value={profileSearch}
                />
              </label>
              <label className="mobile-profile-select">
                <span>收藏</span>
                <select
                  aria-label="收藏筛选"
                  onChange={(event) =>
                    setFavoriteFilter(event.target.value as "all" | "favorite")
                  }
                  value={favoriteFilter}
                >
                  <option value="all">全部玩家</option>
                  <option value="favorite">只看收藏</option>
                </select>
              </label>
              <label className="mobile-profile-select">
                <span>策略</span>
                <select
                  aria-label="策略筛选"
                  onChange={(event) => setProfileStrategyFilter(event.target.value)}
                  value={profileStrategyFilter}
                >
                  <option value="all">全部策略</option>
                  {strategyFilterOptions.map((strategy) => (
                    <option key={strategy} value={strategy}>
                      {formatStrategyLabel(strategy)}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            {playerProfilesQuery.isError ? (
              <p className="mobile-lobby-inline-error">玩家库加载失败</p>
            ) : null}
            <div className="mobile-profile-card-grid">
              {filteredProfiles.map((profile) => {
                const isPending = pendingProfileId === profile.id;

                return (
                  <button
                    aria-label={`为 ${safeActiveSeat} 号座位候选 ${profile.display_name}`}
                    className={[
                      "mobile-profile-card-choice",
                      isPending ? "mobile-profile-card-choice-active" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    key={profile.id}
                    onClick={() => setPendingProfileId(profile.id)}
                    type="button"
                  >
                    <span className="mobile-profile-card-image">
                      <span aria-hidden="true" />
                      {profile.avatar_image_url ? (
                        <img
                          alt=""
                          onError={(event) => {
                            event.currentTarget.hidden = true;
                          }}
                          src={profile.avatar_image_url}
                        />
                      ) : null}
                      {profile.favorite ? (
                        <em
                          aria-label="已收藏"
                          className="mobile-profile-card-star"
                        >
                          ★
                        </em>
                      ) : null}
                      {isPending ? (
                        <em
                          aria-hidden="true"
                          className="mobile-profile-card-check"
                        >
                          ✓
                        </em>
                      ) : null}
                    </span>
                    <strong>{profile.display_name}</strong>
                    <span>{formatStrategyLabel(profile.strategy_profile)}</span>
                    <small>{getProfileDescription(profile)}</small>
                  </button>
                );
              })}
            </div>
            {!playerProfilesQuery.isPending && filteredProfiles.length === 0 ? (
              <p className="mobile-profile-empty">没有匹配玩家</p>
            ) : null}
            <div className="mobile-profile-drawer-footer">
              <span>
                {pendingProfile ? pendingProfile.display_name : "请选择一张玩家卡"}
              </span>
              <button
                className="mobile-button mobile-button-primary"
                disabled={!pendingProfileId}
                onClick={confirmPendingProfile}
                type="button"
              >
                确认选择
              </button>
            </div>
          </section>
        </div>
      ) : null}
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
    ...(profile.tags ?? []),
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
