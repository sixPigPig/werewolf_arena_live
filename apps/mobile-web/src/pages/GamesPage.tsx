import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  type CSSProperties,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  LoaderCircle,
  Star,
  StarCheck,
} from "lucide-react";
import { useNavigate } from "react-router-dom";

import lobbyHeroBanner from "../assets/mobile-lobby-hero-banner.png";
import {
  MobileBottomSelect,
  type MobileBottomSelectOption,
} from "../components/MobileBottomSelect";
import { LobbyRulePicker } from "../components/lobby/LobbyRulePicker";
import { LobbyRuleSummary } from "../components/lobby/LobbyRuleSummary";
import {
  buildLineupLaunchStatus,
  clampSeat,
  filterProfiles,
  findNextEmptySeat,
  formatStrategyLabel,
  getConfirmProfileButtonLabel,
  getProfileCardDescriptionLines,
  getProfileChoiceAriaLabel,
  getProfileSeatStatusLabel,
  getStrategyFilterOptions,
  hasNextEmptySeat,
  normalizePlayerConfigs,
  updateFavoriteProfileIds,
  upsertSeatProfile,
} from "../components/lobby/lobbyModel";
import {
  createGameRun,
  favoritePlayerProfile,
  hasPlayerConfig,
  listPlayerProfileFavorites,
  listPublicPlayerProfiles,
  listRuleSets,
  mergePlayerProfileFavorites,
  randomFillEmptySeats,
  removeInvalidProfileRefs,
  resolveAvatarImageUrl,
  resizeLineupForPlayerCount,
  unfavoritePlayerProfile,
  type PlayerConfig,
  type PlayerProfileFavoritesResponse,
  type PublicPlayerProfileWithFavorite,
} from "@werewolf-arena/game-client";
import {
  publicPlayerProfileFavoritesQueryKey,
  publicPlayerProfilesQueryKey,
} from "../lib/player-profile-query-keys";

const FAVORITE_FILTER_OPTIONS: MobileBottomSelectOption<"all" | "favorite">[] = [
  { label: "全部玩家", value: "all" },
  { label: "只看收藏", value: "favorite" },
];

export function GamesPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [selectedRuleSetId, setSelectedRuleSetId] = useState("");
  const [playerConfigs, setPlayerConfigs] = useState<PlayerConfig[]>([]);
  const [seed, setSeed] = useState("");
  const [maxRounds, setMaxRounds] = useState("8");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [shortage, setShortage] = useState(false);
  const [activeSeat, setActiveSeat] = useState(1);
  const [isProfileDrawerOpen, setIsProfileDrawerOpen] = useState(false);
  const [isRulePickerOpen, setIsRulePickerOpen] = useState(false);
  const [isClearConfirming, setIsClearConfirming] = useState(false);
  const [isFillOptionsOpen, setIsFillOptionsOpen] = useState(false);
  const [pendingProfileId, setPendingProfileId] = useState<string | null>(null);
  const [profileSearch, setProfileSearch] = useState("");
  const [favoriteFilter, setFavoriteFilter] = useState<"all" | "favorite">("all");
  const [profileStrategyFilter, setProfileStrategyFilter] = useState("all");
  const [favoriteUpdateError, setFavoriteUpdateError] = useState<string | null>(null);
  const [pendingFavoriteProfileIds, setPendingFavoriteProfileIds] = useState(
    () => new Set<string>(),
  );
  const lobbyContentRef = useRef<HTMLDivElement | null>(null);
  const profileCardScrollRef = useRef<HTMLDivElement | null>(null);
  const profilePullDistanceRef = useRef(0);
  const profilePullStartYRef = useRef<number | null>(null);
  const rulePickerTriggerRef = useRef<HTMLButtonElement | null>(null);
  const seatButtonRefs = useRef(new Map<number, HTMLButtonElement>());
  const [profilePullDistance, setProfilePullDistance] = useState(0);

  const ruleSetsQuery = useQuery({
    queryKey: ["rule-sets"],
    queryFn: listRuleSets,
  });
  const playerProfilesQuery = useQuery({
    queryKey: publicPlayerProfilesQueryKey,
    queryFn: listPublicPlayerProfiles,
  });
  const favoritesQuery = useQuery({
    queryKey: publicPlayerProfileFavoritesQueryKey,
    queryFn: listPlayerProfileFavorites,
  });
  const createGameRunMutation = useMutation({
    mutationFn: (request: Parameters<typeof createGameRun>[0]) =>
      createGameRun(request),
    onSuccess: (run) => navigate(`/games/${run.run_id}/live`),
  });
  const updateProfileFavoriteMutation = useMutation({
    mutationFn: ({
      isFavorite,
      profileId,
    }: {
      isFavorite: boolean;
      profileId: string;
    }) =>
      isFavorite
        ? favoritePlayerProfile(profileId)
        : unfavoritePlayerProfile(profileId),
    onMutate: async ({ isFavorite, profileId }) => {
      setFavoriteUpdateError(null);
      setPendingFavoriteProfileIds((currentProfileIds) => {
        const nextProfileIds = new Set(currentProfileIds);
        nextProfileIds.add(profileId);
        return nextProfileIds;
      });
      await queryClient.cancelQueries({
        queryKey: publicPlayerProfileFavoritesQueryKey,
      });
      const currentFavorites =
        queryClient.getQueryData<PlayerProfileFavoritesResponse>(
          publicPlayerProfileFavoritesQueryKey,
        );
      const wasFavorite = currentFavorites?.profile_ids.includes(profileId) ?? false;
      queryClient.setQueryData<PlayerProfileFavoritesResponse>(
        publicPlayerProfileFavoritesQueryKey,
        (favorites) =>
          updateFavoriteProfileIds(favorites, profileId, isFavorite),
      );
      return { wasFavorite };
    },
    onError: (_error, variables, context) => {
      queryClient.setQueryData<PlayerProfileFavoritesResponse>(
        publicPlayerProfileFavoritesQueryKey,
        (favorites) =>
          updateFavoriteProfileIds(
            favorites,
            variables.profileId,
            context?.wasFavorite ?? !variables.isFavorite,
          ),
      );
      setFavoriteUpdateError("收藏更新失败，请稍后重试。");
    },
    onSuccess: (updatedFavorite) => {
      queryClient.setQueryData<PlayerProfileFavoritesResponse>(
        publicPlayerProfileFavoritesQueryKey,
        (favorites) =>
          updateFavoriteProfileIds(
            favorites,
            updatedFavorite.profile_id,
            updatedFavorite.is_favorite,
          ),
      );
    },
    onSettled: (_updatedProfile, _error, variables) => {
      setPendingFavoriteProfileIds((currentProfileIds) => {
        const nextProfileIds = new Set(currentProfileIds);
        nextProfileIds.delete(variables.profileId);
        return nextProfileIds;
      });
      return queryClient.invalidateQueries({
        queryKey: publicPlayerProfileFavoritesQueryKey,
      });
    },
  });

  const ruleSets = useMemo(
    () => ruleSetsQuery.data?.rule_sets ?? [],
    [ruleSetsQuery.data?.rule_sets],
  );
  const profiles = useMemo(
    () =>
      mergePlayerProfileFavorites(
        playerProfilesQuery.data ?? [],
        favoritesQuery.data?.profile_ids ?? [],
      ),
    [favoritesQuery.data?.profile_ids, playerProfilesQuery.data],
  );
  const favoritesAvailable = favoritesQuery.isSuccess && !favoritesQuery.isError;
  const appliedFavoriteFilter = favoritesAvailable ? favoriteFilter : "all";
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
  const assignedSeatByProfileId = useMemo(
    () =>
      new Map(
        visiblePlayerConfigs
          .filter((config) => Boolean(config.profile_id))
          .map((config) => [config.profile_id as string, config.seat]),
      ),
    [visiblePlayerConfigs],
  );
  const safeActiveSeat = clampSeat(activeSeat, playerCount);
  const launchStatus = useMemo(
    () => buildLineupLaunchStatus(visiblePlayerConfigs, profiles, playerCount),
    [playerCount, profiles, visiblePlayerConfigs],
  );
  const pendingProfile =
    profiles.find((profile) => profile.id === pendingProfileId) ?? null;
  const pendingAssignedSeat = pendingProfile
    ? assignedSeatByProfileId.get(pendingProfile.id)
    : undefined;
  const strategyFilterOptions = useMemo(
    () => getStrategyFilterOptions(profiles),
    [profiles],
  );
  const filteredProfiles = useMemo(
    () =>
      filterProfiles(profiles, {
        favoriteFilter: appliedFavoriteFilter,
        search: profileSearch,
        strategy: profileStrategyFilter,
      }),
    [appliedFavoriteFilter, profileSearch, profileStrategyFilter, profiles],
  );
  const isLoading = ruleSetsQuery.isPending || playerProfilesQuery.isPending;
  const isSubmitDisabled =
    isLoading ||
    ruleSetsQuery.isError ||
    playerProfilesQuery.isError ||
    !selectedRuleSet ||
    createGameRunMutation.isPending;
  const isLaunchDisabled = isSubmitDisabled || !launchStatus.canLaunch;
  const canFillSeats =
    !isSubmitDisabled &&
    launchStatus.emptySeatCount > 0 &&
    launchStatus.profileShortageCount === 0;
  const showFillOptions = isFillOptionsOpen && canFillSeats;
  const launchButtonStateClass = createGameRunMutation.isPending
    ? "mobile-lobby-launch-pending"
    : "mobile-lobby-launch-ready";
  const canAdvanceAfterConfirm = pendingProfile
    ? hasNextEmptySeat(
        upsertSeatProfile(
          visiblePlayerConfigs,
          safeActiveSeat,
          pendingProfile.id,
        ),
        playerCount,
        safeActiveSeat,
      )
    : false;
  const isProfileDataFetching =
    playerProfilesQuery.isFetching || favoritesQuery.isFetching;
  const profileRefreshStatus = isProfileDataFetching
    ? "refreshing"
    : profilePullDistance >= 64
      ? "ready"
      : profilePullDistance > 0
        ? "pulling"
        : "idle";
  const profileRefreshIndicatorStyle = {
    "--mobile-profile-refresh-offset": `${Math.min(
      Math.max(profilePullDistance, isProfileDataFetching ? 48 : 0),
      72,
    )}px`,
  } as CSSProperties;

  useEffect(() => {
    if (!isClearConfirming) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setIsClearConfirming(false);
    }, 3000);

    return () => window.clearTimeout(timeoutId);
  }, [isClearConfirming]);

  const openRulePicker = useCallback(() => {
    setIsRulePickerOpen(true);
  }, []);

  const closeRulePicker = useCallback(() => {
    setIsRulePickerOpen(false);
  }, []);

  function handleRuleSetChange(ruleSetId: string) {
    const nextRuleSet = ruleSets.find((ruleSet) => ruleSet.id === ruleSetId);
    setSelectedRuleSetId(ruleSetId);
    setValidationError(null);
    setShortage(false);
    setIsClearConfirming(false);
    setIsFillOptionsOpen(false);

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

  function openProfileDrawer(seat: number, trigger: HTMLButtonElement) {
    const profile = selectedProfilesBySeat.get(seat) ?? null;
    setActiveSeat(seat);
    setPendingProfileId(profile?.id ?? null);
    setProfileSearch("");
    setFavoriteFilter("all");
    setProfileStrategyFilter("all");
    setValidationError(null);
    setShortage(false);
    setIsClearConfirming(false);
    setIsFillOptionsOpen(false);
    setIsProfileDrawerOpen(true);
    focusSeatAndScrollRowToTop(seat, trigger);
  }

  function closeProfileDrawer() {
    setIsProfileDrawerOpen(false);
    setPendingProfileId(null);
  }

  function confirmPendingProfile(
    options: { advanceToNextEmpty?: boolean } = {},
  ) {
    if (!pendingProfile) {
      return;
    }

    const nextConfigs = upsertSeatProfile(
      visiblePlayerConfigs,
      safeActiveSeat,
      pendingProfile.id,
    );
    const nextEmptySeat = findNextEmptySeat(
      nextConfigs,
      playerCount,
      safeActiveSeat,
    );

    setValidationError(null);
    setShortage(false);
    setIsClearConfirming(false);
    setIsFillOptionsOpen(false);
    setPlayerConfigs(nextConfigs);

    if (options.advanceToNextEmpty && nextEmptySeat) {
      setActiveSeat(nextEmptySeat);
      setPendingProfileId(null);
      focusSeatAndScrollRowToTop(nextEmptySeat);
      return;
    }

    setIsProfileDrawerOpen(false);
    setPendingProfileId(null);
  }

  function fillEmptySeats(options?: { favoritesOnly?: boolean }) {
    if (!selectedRuleSet || (options?.favoritesOnly && !favoritesAvailable)) {
      return;
    }
    setValidationError(null);
    setShortage(false);
    setIsClearConfirming(false);
    setIsFillOptionsOpen(false);
    setPlayerConfigs(
      randomFillEmptySeats(
        visiblePlayerConfigs,
        profiles,
        selectedRuleSet.player_count,
        options,
      ),
    );
  }

  function handleToggleProfileFavorite(profile: PublicPlayerProfileWithFavorite) {
    if (!favoritesAvailable) {
      return;
    }
    setValidationError(null);
    setShortage(false);
    setIsClearConfirming(false);
    setIsFillOptionsOpen(false);
    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
    updateProfileFavoriteMutation.mutate({
      isFavorite: !profile.is_favorite,
      profileId: profile.id,
    });
  }

  function setProfilePullDistanceValue(distance: number) {
    profilePullDistanceRef.current = distance;
    setProfilePullDistance(distance);
  }

  function resetProfilePull() {
    profilePullStartYRef.current = null;
    setProfilePullDistanceValue(0);
  }

  function handleProfilePullStart(clientY: number) {
    if (isProfileDataFetching) {
      return;
    }

    if ((profileCardScrollRef.current?.scrollTop ?? 0) > 0) {
      return;
    }

    profilePullStartYRef.current = clientY;
    setProfilePullDistanceValue(0);
  }

  function handleProfilePullMove(clientY: number, preventDefault: () => void) {
    const startY = profilePullStartYRef.current;

    if (startY === null) {
      return;
    }

    if ((profileCardScrollRef.current?.scrollTop ?? 0) > 0) {
      resetProfilePull();
      return;
    }

    const distance = clientY - startY;

    if (distance <= 0) {
      setProfilePullDistanceValue(0);
      return;
    }

    if (distance > 8) {
      preventDefault();
    }

    setProfilePullDistanceValue(Math.min(distance, 96));
  }

  function handleProfilePullEnd() {
    const shouldRefresh = profilePullDistanceRef.current >= 64;

    profilePullStartYRef.current = null;

    if (!shouldRefresh) {
      setProfilePullDistanceValue(0);
      return;
    }

    void Promise.all([
      playerProfilesQuery.refetch(),
      favoritesQuery.refetch(),
    ]).finally(() => {
      setProfilePullDistanceValue(0);
    });
  }

  function handleClearSeats() {
    const hasAssignedSeats = visiblePlayerConfigs.some((config) =>
      hasPlayerConfig(config),
    );

    if (!hasAssignedSeats) {
      setPlayerConfigs([]);
      setShortage(false);
      setValidationError(null);
      setIsClearConfirming(false);
      setIsFillOptionsOpen(false);
      return;
    }

    if (!isClearConfirming) {
      setIsClearConfirming(true);
      return;
    }

    setPlayerConfigs([]);
    setShortage(false);
    setValidationError(null);
    setIsClearConfirming(false);
    setIsFillOptionsOpen(false);
  }

  function handleSubmit() {
    setIsClearConfirming(false);
    setIsFillOptionsOpen(false);

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

    const normalizedPlayerConfigs = normalizePlayerConfigs(
      visiblePlayerConfigs,
      selectedRuleSet.player_count,
    );
    const selectedProfileCount = new Set(
      normalizedPlayerConfigs
        .map((config) => config.profile_id)
        .filter((profileId): profileId is string => Boolean(profileId)),
    ).size;

    if (selectedProfileCount < selectedRuleSet.player_count) {
      setShortage(true);
      setValidationError(null);
      setPlayerConfigs(normalizedPlayerConfigs);
      return;
    }

    setShortage(false);
    setValidationError(null);
    setPlayerConfigs(normalizedPlayerConfigs);

    createGameRunMutation.mutate({
      rule_set_id: selectedRuleSet.id,
      seed: seed ? Number(seed) : null,
      max_rounds: parsedMaxRounds,
      player_configs: normalizedPlayerConfigs,
    });
  }

  function focusSeatAndScrollRowToTop(
    seat: number,
    fallbackButton?: HTMLButtonElement,
  ) {
    const seatButton = seatButtonRefs.current.get(seat) ?? fallbackButton;

    if (!seatButton) {
      return;
    }

    seatButton.focus({ preventScroll: true });
    window.requestAnimationFrame(() => {
      seatButton.scrollIntoView({
        behavior: "smooth",
        block: "start",
        inline: "nearest",
      });
    });
  }

  return (
    <main
      className={[
        "mobile-page",
        "mobile-lobby-page",
        isProfileDrawerOpen ? "mobile-lobby-page-drawer-open" : "",
      ]
        .filter(Boolean)
        .join(" ")}
      data-testid="mobile-games-page"
    >
      <div
        className="mobile-lobby-content"
        ref={lobbyContentRef}
      >
        <header className="mobile-lobby-hero" aria-labelledby="mobile-lobby-title">
          <img
            alt="狼人杀对局大厅"
            className="mobile-lobby-hero-image"
            decoding="async"
            fetchPriority="high"
            src={lobbyHeroBanner}
          />
          <h1 className="mobile-sr-only" id="mobile-lobby-title">
            狼人杀对局大厅
          </h1>
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

      <LobbyRuleSummary
        changeButtonRef={rulePickerTriggerRef}
        disabled={createGameRunMutation.isPending || ruleSetsQuery.isFetching}
        isError={ruleSetsQuery.isError}
        isLoading={ruleSetsQuery.isPending}
        onOpenPicker={openRulePicker}
        onRetry={() => void ruleSetsQuery.refetch()}
        ruleSet={selectedRuleSet}
      />

      {selectedRuleSet ? (
        <section
          aria-labelledby="mobile-seat-title"
          className="mobile-lobby-section mobile-lobby-board-section"
        >
          <div className="mobile-lobby-section-heading">
            <h2 id="mobile-seat-title">组建阵容</h2>
            <span className="mobile-lobby-seat-summary">
              {selectedRuleSet.name} · {playerCount} 个座位
            </span>
          </div>
          <div className="mobile-lobby-seat-grid">
            {Array.from({ length: playerCount }, (_, index) => index + 1).map(
              (seat) => {
                const profile = selectedProfilesBySeat.get(seat);
                const avatarImageUrl = profile
                  ? resolveAvatarImageUrl(profile)
                  : "";
                const isActive = safeActiveSeat === seat;
                const seatDisplayName = profile?.display_name ?? "请选择";

                return (
                  <button
                    aria-label={`选择 ${seat} 号座位，当前为 ${
                      seatDisplayName
                    }`}
                    aria-pressed={isActive}
                    className={[
                      "mobile-lobby-seat-card",
                      isActive ? "mobile-lobby-seat-card-active" : "",
                      profile ? "mobile-lobby-seat-card-filled" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    key={seat}
                    onClick={(event) => openProfileDrawer(seat, event.currentTarget)}
                    ref={(element) => {
                      if (element) {
                        seatButtonRefs.current.set(seat, element);
                      } else {
                        seatButtonRefs.current.delete(seat);
                      }
                    }}
                    type="button"
                  >
                    {profile ? (
                      <span className="mobile-lobby-seat-avatar">
                        <span aria-hidden="true" />
                        {avatarImageUrl ? (
                          <img
                            alt=""
                            onError={(event) => {
                              event.currentTarget.hidden = true;
                            }}
                            src={avatarImageUrl}
                          />
                        ) : null}
                      </span>
                    ) : null}
                    <strong>{seatDisplayName}</strong>
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

      <section
        aria-labelledby="mobile-create-title"
        className="mobile-lobby-section mobile-lobby-board-section"
      >
        <div className="mobile-lobby-section-heading">
          <h2 id="mobile-create-title">填充设置</h2>
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
          <span className="mobile-lobby-launch-status">
            {launchStatus.summaryText}
          </span>
          {showFillOptions ? (
            <div className="mobile-lobby-fill-options">
              <button
                className="mobile-button mobile-lobby-favorite-fill"
                disabled={!favoritesAvailable}
                onClick={() => fillEmptySeats({ favoritesOnly: true })}
                type="button"
              >
                <span>收藏补齐</span>
              </button>
              <button
                className="mobile-button mobile-lobby-random-fill"
                onClick={() => fillEmptySeats()}
                type="button"
              >
                <span>随机补齐</span>
              </button>
            </div>
          ) : null}
          <button
            aria-expanded={showFillOptions}
            className="mobile-button mobile-lobby-fill-toggle"
            disabled={!canFillSeats}
            onClick={() => {
              setValidationError(null);
              setShortage(false);
              setIsClearConfirming(false);
              setIsFillOptionsOpen((currentIsOpen) => !currentIsOpen);
            }}
            type="button"
          >
            <span>补齐席位</span>
          </button>
          <button
            className={[
              "mobile-button",
              "mobile-lobby-clear-seats",
              isClearConfirming ? "mobile-lobby-clear-confirming" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            disabled={createGameRunMutation.isPending}
            onClick={handleClearSeats}
            type="button"
          >
            <span>{isClearConfirming ? "确认清空" : "清空席位"}</span>
          </button>
          <button
            className={[
              "mobile-button",
              "mobile-button-primary",
              launchButtonStateClass,
            ]
              .filter(Boolean)
              .join(" ")}
            disabled={isLaunchDisabled}
            onClick={handleSubmit}
            type="button"
          >
            <span>
              {createGameRunMutation.isPending ? "发起中" : launchStatus.ctaLabel}
            </span>
          </button>
        </div>
      </div>

      {isRulePickerOpen ? (
        <LobbyRulePicker
          backgroundRef={lobbyContentRef}
          onClose={closeRulePicker}
          onSelect={handleRuleSetChange}
          restoreFocusRef={rulePickerTriggerRef}
          ruleSets={ruleSets}
          selectedRuleSetId={selectedRuleSet?.id ?? null}
        />
      ) : null}

      {isProfileDrawerOpen ? (
        <div className="mobile-profile-drawer-layer">
          <div
            aria-hidden="true"
            className="mobile-profile-drawer-backdrop"
          />
          <section
            aria-labelledby="mobile-profile-drawer-title"
            aria-modal="false"
            className="mobile-profile-drawer"
            role="dialog"
            tabIndex={-1}
          >
            <div className="mobile-profile-drawer-top">
              <div className="mobile-profile-drawer-handle" aria-hidden="true" />
              <div className="mobile-profile-drawer-heading">
                <div className="mobile-profile-drawer-title-row">
                  <h2 id="mobile-profile-drawer-title">玩家卡牌库</h2>
                  <button
                    aria-label="关闭玩家卡牌库"
                    className="mobile-profile-drawer-close"
                    onClick={closeProfileDrawer}
                    type="button"
                  >
                    ×
                  </button>
                </div>
                <p>当前选择：{safeActiveSeat}号座位</p>
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
                <MobileBottomSelect
                  className="mobile-profile-select-favorite"
                  disabled={!favoritesAvailable}
                  label="收藏"
                  onChange={setFavoriteFilter}
                  options={FAVORITE_FILTER_OPTIONS}
                  value={appliedFavoriteFilter}
                />
                <MobileBottomSelect
                  className="mobile-profile-select-strategy"
                  label="策略"
                  onChange={setProfileStrategyFilter}
                  options={[
                    { label: "全部策略", value: "all" },
                    ...strategyFilterOptions.map((strategy) => ({
                      label: formatStrategyLabel(strategy),
                      value: strategy,
                    })),
                  ]}
                  value={profileStrategyFilter}
                />
              </div>

              {playerProfilesQuery.isError ? (
                <p className="mobile-lobby-inline-error">玩家库加载失败</p>
              ) : null}
              {favoritesQuery.isError ? (
                <p className="mobile-lobby-inline-error" role="status">
                  收藏状态暂不可用，仍可正常选择玩家。
                </p>
              ) : null}
              {favoriteUpdateError ? (
                <p className="mobile-lobby-inline-error" role="alert">
                  {favoriteUpdateError}
                </p>
              ) : null}
            </div>

            <div
              className="mobile-profile-card-scroll"
              onTouchCancel={resetProfilePull}
              onTouchEnd={handleProfilePullEnd}
              onTouchMove={(event) => {
                const touch = event.touches[0];
                if (!touch) {
                  return;
                }
                handleProfilePullMove(touch.clientY, () => {
                  if (event.cancelable) {
                    event.preventDefault();
                  }
                });
              }}
              onTouchStart={(event) => {
                const touch = event.touches[0];
                if (touch) {
                  handleProfilePullStart(touch.clientY);
                }
              }}
              ref={profileCardScrollRef}
            >
              <div
                aria-hidden="true"
                className={[
                  "mobile-profile-refresh-indicator",
                  `mobile-profile-refresh-indicator-${profileRefreshStatus}`,
                ].join(" ")}
                style={profileRefreshIndicatorStyle}
              >
                <span className="mobile-profile-refresh-orbit">
                  <LoaderCircle
                    aria-hidden="true"
                    className="mobile-profile-refresh-spinner"
                  />
                </span>
              </div>
              <span aria-live="polite" className="mobile-sr-only">
                {isProfileDataFetching
                  ? "玩家库刷新中"
                  : profilePullDistance >= 64
                    ? "释放刷新玩家库"
                    : profilePullDistance > 0
                      ? "下拉刷新玩家库"
                      : ""}
              </span>
              {filteredProfiles.length > 0 ? (
                <div className="mobile-profile-card-grid">
                  {filteredProfiles.map((profile) => {
                    const isPending = pendingProfileId === profile.id;
                    const isFavoriteUpdatePending =
                      pendingFavoriteProfileIds.has(profile.id);
                    const assignedSeat = assignedSeatByProfileId.get(profile.id);
                    const seatStatusLabel = getProfileSeatStatusLabel(
                      assignedSeat,
                      safeActiveSeat,
                    );
                    const avatarImageUrl = resolveAvatarImageUrl(profile);
                    const descriptionLines =
                      getProfileCardDescriptionLines(profile);

                    return (
                      <div
                        className={[
                          "mobile-profile-card-choice",
                          isPending ? "mobile-profile-card-choice-active" : "",
                        ]
                          .filter(Boolean)
                          .join(" ")}
                        key={profile.id}
                      >
                        <button
                          aria-label={getProfileChoiceAriaLabel(
                            safeActiveSeat,
                            profile,
                            seatStatusLabel,
                          )}
                          className="mobile-profile-card-select-button"
                          onClick={() => setPendingProfileId(profile.id)}
                          type="button"
                        >
                          <span className="mobile-profile-card-image">
                            <span aria-hidden="true" />
                            {avatarImageUrl ? (
                              <img
                                alt=""
                                onError={(event) => {
                                  event.currentTarget.hidden = true;
                                }}
                                src={avatarImageUrl}
                              />
                            ) : null}
                          </span>
                          {isPending ? (
                            <em
                              aria-hidden="true"
                              className="mobile-profile-card-check"
                            />
                          ) : null}
                          <span className="mobile-profile-card-name-row">
                            {seatStatusLabel ? (
                              <span className="mobile-profile-card-seat-status">
                                {seatStatusLabel}
                              </span>
                            ) : null}
                            <strong>{profile.display_name}</strong>
                          </span>
                          <span className="mobile-profile-card-strategy">
                            {formatStrategyLabel(profile.strategy_profile)}
                          </span>
                          <small>
                            {descriptionLines.map((descriptionLine, index) => (
                              <span
                                className="mobile-profile-card-description-line"
                                key={`${profile.id}-description-${index}`}
                              >
                                {descriptionLine}
                              </span>
                            ))}
                          </small>
                        </button>
                        <button
                          aria-label={`${
                            profile.is_favorite ? "取消收藏" : "收藏"
                          } ${profile.display_name}`}
                          aria-pressed={profile.is_favorite}
                          className={[
                            "mobile-profile-card-favorite-button",
                            profile.is_favorite
                              ? "mobile-profile-card-favorite-button-active"
                              : "",
                          ]
                            .filter(Boolean)
                            .join(" ")}
                          disabled={!favoritesAvailable || isFavoriteUpdatePending}
                          onClick={() => handleToggleProfileFavorite(profile)}
                          onPointerDown={(event) => {
                            event.preventDefault();
                          }}
                          type="button"
                        >
                          {profile.is_favorite ? (
                            <StarCheck
                              aria-hidden="true"
                              className="mobile-profile-card-favorite-icon"
                            />
                          ) : (
                            <Star
                              aria-hidden="true"
                              className="mobile-profile-card-favorite-icon"
                            />
                          )}
                        </button>
                      </div>
                    );
                  })}
                </div>
              ) : null}
              {!playerProfilesQuery.isPending && filteredProfiles.length === 0 ? (
                <p className="mobile-profile-empty">没有匹配玩家</p>
              ) : null}
            </div>
            <div className="mobile-profile-drawer-footer">
              <span>
                {pendingProfile ? pendingProfile.display_name : "请选择玩家"}
              </span>
              <button
                className="mobile-button mobile-profile-drawer-secondary-action"
                disabled={!canAdvanceAfterConfirm}
                onClick={() =>
                  confirmPendingProfile({ advanceToNextEmpty: true })
                }
                type="button"
              >
                确认并下一位
              </button>
              <button
                className="mobile-button mobile-button-primary"
                disabled={!pendingProfile}
                onClick={() => confirmPendingProfile()}
                type="button"
              >
                {getConfirmProfileButtonLabel(
                  pendingProfile,
                  pendingAssignedSeat,
                  safeActiveSeat,
                )}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}
