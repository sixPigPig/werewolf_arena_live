import {
  useMutation,
  useQuery,
} from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import lobbyHeroBanner from "../assets/mobile-lobby-hero-banner.png";
import classic12SelectedCard from "../assets/rule-cards/classic-12-selected.png";
import classic12UnselectedCard from "../assets/rule-cards/classic-12-unselected.png";
import classic8SelectedCard from "../assets/rule-cards/classic-8-selected.png";
import classic8UnselectedCard from "../assets/rule-cards/classic-8-unselected.png";
import social8SelectedCard from "../assets/rule-cards/social-8-selected.png";
import social8UnselectedCard from "../assets/rule-cards/social-8-unselected.png";
import starter6SelectedCard from "../assets/rule-cards/starter-6-selected.png";
import starter6UnselectedCard from "../assets/rule-cards/starter-6-unselected.png";
import {
  createGameRun,
  hasPlayerConfig,
  listPlayerProfiles,
  listRuleSets,
  randomFillEmptySeats,
  removeInvalidProfileRefs,
  resolveAvatarImageUrl,
  resizeLineupForPlayerCount,
  type PlayerConfig,
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
  const [isClearConfirming, setIsClearConfirming] = useState(false);
  const [pendingProfileId, setPendingProfileId] = useState<string | null>(null);
  const [profileSearch, setProfileSearch] = useState("");
  const [favoriteFilter, setFavoriteFilter] = useState<"all" | "favorite">("all");
  const [profileStrategyFilter, setProfileStrategyFilter] = useState("all");
  const lobbyContentRef = useRef<HTMLDivElement | null>(null);
  const profileDrawerRef = useRef<HTMLElement | null>(null);
  const profileDrawerTriggerRef = useRef<HTMLButtonElement | null>(null);
  const ruleScrollRef = useRef<HTMLDivElement | null>(null);
  const ruleCardRefs = useRef(new Map<string, HTMLLabelElement>());

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
  const isLaunchDisabled = isSubmitDisabled || !launchStatus.canLaunch;
  const launchButtonStateClass = createGameRunMutation.isPending
    ? "mobile-lobby-launch-pending"
    : getLaunchButtonStateClass(launchStatus);
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

  useEffect(() => {
    const lobbyContent = lobbyContentRef.current as
      | (HTMLDivElement & { inert?: boolean })
      | null;

    if (!lobbyContent) {
      return;
    }

    lobbyContent.inert = isProfileDrawerOpen;
    if (isProfileDrawerOpen) {
      lobbyContent.setAttribute("inert", "");
    } else {
      lobbyContent.removeAttribute("inert");
    }

    return () => {
      lobbyContent.inert = false;
      lobbyContent.removeAttribute("inert");
    };
  }, [isProfileDrawerOpen]);

  useEffect(() => {
    if (!isProfileDrawerOpen) {
      return;
    }

    const drawer = profileDrawerRef.current;
    if (!drawer) {
      return;
    }

    const previouslyFocusedElement =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const initialFocusTarget = getFocusableElements(drawer)[0] ?? drawer;
    initialFocusTarget.focus();

    function handleDrawerKeyDown(event: KeyboardEvent) {
      if (event.key !== "Tab" || !drawer) {
        return;
      }

      const focusableElements = getFocusableElements(drawer);
      if (focusableElements.length === 0) {
        event.preventDefault();
        drawer.focus();
        return;
      }

      const firstFocusable = focusableElements[0];
      const lastFocusable = focusableElements[focusableElements.length - 1];
      const activeElement =
        document.activeElement instanceof HTMLElement
          ? document.activeElement
          : null;

      if (!activeElement || !drawer.contains(activeElement)) {
        event.preventDefault();
        firstFocusable.focus();
        return;
      }

      if (event.shiftKey && activeElement === firstFocusable) {
        event.preventDefault();
        lastFocusable.focus();
        return;
      }

      if (!event.shiftKey && activeElement === lastFocusable) {
        event.preventDefault();
        firstFocusable.focus();
      }
    }

    document.addEventListener("keydown", handleDrawerKeyDown);

    return () => {
      document.removeEventListener("keydown", handleDrawerKeyDown);
      const focusTarget =
        profileDrawerTriggerRef.current ?? previouslyFocusedElement;

      if (focusTarget && document.contains(focusTarget)) {
        focusTarget.focus();
      }

      profileDrawerTriggerRef.current = null;
    };
  }, [isProfileDrawerOpen]);

  useEffect(() => {
    if (!isClearConfirming) {
      return;
    }

    const timeoutId = window.setTimeout(() => {
      setIsClearConfirming(false);
    }, 3000);

    return () => window.clearTimeout(timeoutId);
  }, [isClearConfirming]);

  function handleRuleSetChange(
    ruleSetId: string,
    options: { scrollCardIntoView?: boolean } = {},
  ) {
    const nextRuleSet = ruleSets.find((ruleSet) => ruleSet.id === ruleSetId);
    setSelectedRuleSetId(ruleSetId);
    setValidationError(null);
    setShortage(false);
    setIsClearConfirming(false);

    if (options.scrollCardIntoView) {
      scrollRuleCardIntoView(ruleSetId);
    }

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

  function scrollRuleCardIntoView(ruleSetId: string) {
    const ruleCard = ruleCardRefs.current.get(ruleSetId);
    const ruleScroll = ruleScrollRef.current;

    if (!ruleCard || !ruleScroll) {
      return;
    }

    const scrollLeft =
      ruleCard.offsetLeft - (ruleScroll.clientWidth - ruleCard.offsetWidth) / 2;

    ruleScroll.scrollTo({
      left: Math.max(0, scrollLeft),
      behavior: "smooth",
    });
  }

  function openProfileDrawer(seat: number, trigger: HTMLButtonElement) {
    const profile = selectedProfilesBySeat.get(seat) ?? null;
    profileDrawerTriggerRef.current = trigger;
    setActiveSeat(seat);
    setPendingProfileId(profile?.id ?? null);
    setProfileSearch("");
    setFavoriteFilter("all");
    setProfileStrategyFilter("all");
    setValidationError(null);
    setShortage(false);
    setIsClearConfirming(false);
    setIsProfileDrawerOpen(true);
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
    setPlayerConfigs(nextConfigs);

    if (options.advanceToNextEmpty && nextEmptySeat) {
      setActiveSeat(nextEmptySeat);
      setPendingProfileId(null);
      return;
    }

    setIsProfileDrawerOpen(false);
    setPendingProfileId(null);
  }

  function fillEmptySeats(options?: { favoritesOnly?: boolean }) {
    if (!selectedRuleSet) {
      return;
    }
    setValidationError(null);
    setShortage(false);
    setIsClearConfirming(false);
    setPlayerConfigs(
      randomFillEmptySeats(
        visiblePlayerConfigs,
        profiles,
        selectedRuleSet.player_count,
        options,
      ),
    );
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
  }

  function handleSubmit() {
    setIsClearConfirming(false);

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

    if (launchStatus.emptySeatCount > 0) {
      return;
    }

    createGameRunMutation.mutate({
      rule_set_id: selectedRuleSet.id,
      seed: seed ? Number(seed) : null,
      max_rounds: parsedMaxRounds,
      player_configs: filledPlayerConfigs,
    });
  }

  return (
    <main className="mobile-page mobile-lobby-page" data-testid="mobile-games-page">
      <div
        className="mobile-lobby-content"
        ref={lobbyContentRef}
      >
        <header className="mobile-lobby-hero" aria-labelledby="mobile-lobby-title">
          <img
            alt="狼人杀对局大厅"
            className="mobile-lobby-hero-image"
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

      <section
        aria-labelledby="mobile-rule-title"
        className="mobile-lobby-section mobile-lobby-board-section"
      >
        <div className="mobile-lobby-section-heading">
          <h2 id="mobile-rule-title">规则选择</h2>
        </div>
        {ruleSetsQuery.isError ? <p>规则加载失败</p> : null}
        <div className="mobile-lobby-rule-picker">
          <div className="mobile-lobby-rule-scroll" ref={ruleScrollRef}>
            {ruleSets.map((ruleSet) => {
              const isSelected = selectedRuleSet?.id === ruleSet.id;
              const ruleCardImage = getRuleCardImage(ruleSet.id, isSelected);
              const ruleCardFallbackSummary =
                ruleSet.role_summary ?? ruleSet.complexity ?? "自定义规则";
              const ruleCardAccessibleName = ruleCardImage
                ? `选择规则 ${ruleSet.name}`
                : [
                    `选择规则 ${ruleSet.name}`,
                    `${ruleSet.player_count} 人局`,
                    ruleCardFallbackSummary,
                  ].join("，");

              return (
                <label
                  className={[
                    "mobile-lobby-rule-card",
                    isSelected ? "mobile-lobby-rule-card-active" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  key={ruleSet.id}
                  ref={(element) => {
                    if (element) {
                      ruleCardRefs.current.set(ruleSet.id, element);
                    } else {
                      ruleCardRefs.current.delete(ruleSet.id);
                    }
                  }}
                >
                  <input
                    aria-label={ruleCardAccessibleName}
                    checked={isSelected}
                    name="mobile-rule-set"
                    onChange={() => handleRuleSetChange(ruleSet.id)}
                    type="radio"
                    value={ruleSet.id}
                  />
                  {ruleCardImage ? (
                    <img
                      alt=""
                      aria-hidden="true"
                      className="mobile-lobby-rule-card-image"
                      src={ruleCardImage}
                    />
                  ) : (
                    <span className="mobile-lobby-rule-card-fallback">
                      <strong>{ruleSet.name}</strong>
                      <span>{ruleSet.player_count} 人局</span>
                      <small>{ruleCardFallbackSummary}</small>
                    </span>
                  )}
                </label>
              );
            })}
            {isLoading ? <p>加载中</p> : null}
          </div>
          {ruleSets.length > 0 ? (
            <div
              aria-label="规则选择指示"
              className="mobile-lobby-rule-dots"
              role="group"
            >
              {ruleSets.map((ruleSet) => {
                const isSelected = selectedRuleSet?.id === ruleSet.id;
                const tone = getRuleCardTone(ruleSet.id);

                return (
                  <button
                    aria-current={isSelected ? "true" : undefined}
                    aria-label={`切换到规则 ${ruleSet.name}`}
                    className={[
                      "mobile-lobby-rule-dot",
                      `mobile-lobby-rule-dot-${tone}`,
                      isSelected ? "mobile-lobby-rule-dot-active" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    key={ruleSet.id}
                    onClick={() =>
                      handleRuleSetChange(ruleSet.id, {
                        scrollCardIntoView: true,
                      })
                    }
                    type="button"
                  />
                );
              })}
            </div>
          ) : null}
        </div>
      </section>

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
          <button
            className="mobile-button mobile-lobby-favorite-fill"
            disabled={!selectedRuleSet}
            onClick={() => fillEmptySeats({ favoritesOnly: true })}
            type="button"
          >
            <span>收藏补齐</span>
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
            ref={profileDrawerRef}
            role="dialog"
            tabIndex={-1}
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
                const assignedSeat = assignedSeatByProfileId.get(profile.id);
                const seatStatusLabel = getProfileSeatStatusLabel(
                  assignedSeat,
                  safeActiveSeat,
                );
                const avatarImageUrl = resolveAvatarImageUrl(profile);

                return (
                  <button
                    aria-label={getProfileChoiceAriaLabel(
                      safeActiveSeat,
                      profile,
                      seatStatusLabel,
                    )}
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
                      {avatarImageUrl ? (
                        <img
                          alt=""
                          onError={(event) => {
                            event.currentTarget.hidden = true;
                          }}
                          src={avatarImageUrl}
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
                    {seatStatusLabel ? (
                      <span className="mobile-profile-card-seat-status">
                        {seatStatusLabel}
                      </span>
                    ) : null}
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

function getProfileSeatStatusLabel(
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

function getProfileChoiceAriaLabel(
  activeSeat: number,
  profile: VirtualPlayerProfile,
  seatStatusLabel: string | null,
) {
  return [
    `为 ${activeSeat} 号座位候选 ${profile.display_name}`,
    seatStatusLabel,
  ]
    .filter(Boolean)
    .join("，");
}

function getConfirmProfileButtonLabel(
  pendingProfile: VirtualPlayerProfile | null,
  assignedSeat: number | undefined,
  activeSeat: number,
) {
  if (!pendingProfile) {
    return "确认选择";
  }

  if (assignedSeat && assignedSeat !== activeSeat) {
    return `移动到 ${activeSeat} 号座位`;
  }

  return "确认选择";
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

type LineupLaunchStatus = {
  assignedCount: number;
  emptySeatCount: number;
  profileShortageCount: number;
  summaryText: string;
  ctaLabel: string;
  canLaunch: boolean;
};

function getLaunchButtonStateClass(status: LineupLaunchStatus) {
  if (status.canLaunch) {
    return status.emptySeatCount > 0
      ? "mobile-lobby-launch-auto-fill"
      : "mobile-lobby-launch-ready";
  }

  return status.profileShortageCount > 0
    ? "mobile-lobby-launch-shortage"
    : "";
}

function buildLineupLaunchStatus(
  configs: PlayerConfig[],
  profiles: VirtualPlayerProfile[],
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

  if (playerCount === 0) {
    return {
      assignedCount,
      emptySeatCount,
      profileShortageCount: 0,
      summaryText: "等待规则加载",
      ctaLabel: "发起对局",
      canLaunch: false,
    };
  }

  if (profileShortageCount > 0) {
    return {
      assignedCount,
      emptySeatCount,
      profileShortageCount,
      summaryText: `${countPrefix} · 还差 ${profileShortageCount} 名玩家`,
      ctaLabel: `还差 ${profileShortageCount} 名玩家`,
      canLaunch: false,
    };
  }

  if (emptySeatCount > 0) {
    return {
      assignedCount,
      emptySeatCount,
      profileShortageCount,
      summaryText: `${countPrefix} · 可自动补齐`,
      ctaLabel: "补齐发起",
      canLaunch: true,
    };
  }

  return {
    assignedCount,
    emptySeatCount,
    profileShortageCount,
    summaryText: `${countPrefix} · 阵容已就绪`,
    ctaLabel: "发起对局",
    canLaunch: true,
  };
}

function clampSeat(seat: number, playerCount: number) {
  return seat >= 1 && seat <= playerCount ? seat : 1;
}

function findNextEmptySeat(
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

function hasNextEmptySeat(
  configs: PlayerConfig[],
  playerCount: number,
  currentSeat: number,
) {
  return findNextEmptySeat(configs, playerCount, currentSeat) !== undefined;
}

function getFocusableElements(container: HTMLElement) {
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      [
        "a[href]",
        "button:not([disabled])",
        "input:not([disabled])",
        "select:not([disabled])",
        "textarea:not([disabled])",
        "[tabindex]:not([tabindex='-1'])",
      ].join(","),
    ),
  ).filter((element) => {
    const ariaHidden = element.getAttribute("aria-hidden") === "true";
    return !ariaHidden && !element.hidden;
  });
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

type RuleCardImages = {
  selected: string;
  unselected: string;
};

const ruleCardImagesById: Partial<Record<string, RuleCardImages>> = {
  classic_8: {
    selected: classic8SelectedCard,
    unselected: classic8UnselectedCard,
  },
  starter_6: {
    selected: starter6SelectedCard,
    unselected: starter6UnselectedCard,
  },
  social_8: {
    selected: social8SelectedCard,
    unselected: social8UnselectedCard,
  },
  classic_12_seer_witch_hunter_idiot: {
    selected: classic12SelectedCard,
    unselected: classic12UnselectedCard,
  },
};

function getRuleCardImage(
  ruleSetId: string,
  isSelected: boolean,
): string | null {
  const images = ruleCardImagesById[ruleSetId];

  if (!images) {
    return null;
  }

  return isSelected ? images.selected : images.unselected;
}

function getRuleCardTone(ruleSetId: string) {
  const tones: Record<string, string> = {
    classic_8: "classic",
    starter_6: "starter",
    social_8: "social",
    classic_12_seer_witch_hunter_idiot: "advanced",
  };

  return tones[ruleSetId] ?? "classic";
}
