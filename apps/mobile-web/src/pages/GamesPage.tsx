import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  useCallback,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";

import lobbyHeroBanner from "../assets/mobile-lobby-hero-banner.png";
import { LobbyRulePicker } from "../components/lobby/LobbyRulePicker";
import { LobbyRuleSummary } from "../components/lobby/LobbyRuleSummary";
import { LobbyLineupSection } from "../components/lobby/LobbyLineupSection";
import { LobbyAdvancedSettings } from "../components/lobby/LobbyAdvancedSettings";
import { LobbyLaunchBar } from "../components/lobby/LobbyLaunchBar";
import { LobbyPlayerPicker } from "../components/lobby/LobbyPlayerPicker";
import {
  buildLineupLaunchStatus,
  clampSeat,
  findNextEmptySeat,
  normalizePlayerConfigs,
  updateFavoriteProfileIds,
  upsertSeatProfile,
} from "../components/lobby/lobbyModel";
import {
  createGameRun,
  favoritePlayerProfile,
  listPlayerProfileFavorites,
  listPublicPlayerProfiles,
  listRuleSets,
  mergePlayerProfileFavorites,
  previewGameLineup,
  randomFillEmptySeats,
  removeInvalidProfileRefs,
  resizeLineupForPlayerCount,
  unfavoritePlayerProfile,
  type LineupQualityReport,
  type PlayerConfig,
  type PlayerProfileFavoritesResponse,
  type PublicPlayerProfileWithFavorite,
} from "@werewolf-arena/game-client";
import {
  publicPlayerProfileFavoritesQueryKey,
  publicPlayerProfilesQueryKey,
} from "../lib/player-profile-query-keys";

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
  const [isPlayerPickerOpen, setIsPlayerPickerOpen] = useState(false);
  const [isRulePickerOpen, setIsRulePickerOpen] = useState(false);
  const [pendingProfileId, setPendingProfileId] = useState<string | null>(null);
  const [favoriteUpdateError, setFavoriteUpdateError] = useState<string | null>(null);
  const [lineupQualityError, setLineupQualityError] = useState<string | null>(null);
  const [lineupQualityReport, setLineupQualityReport] =
    useState<LineupQualityReport | null>(null);
  const [qualityOverrideConfirmed, setQualityOverrideConfirmed] = useState(false);
  const [pendingFavoriteProfileIds, setPendingFavoriteProfileIds] = useState(
    () => new Set<string>(),
  );
  const lobbyContentRef = useRef<HTMLDivElement | null>(null);
  const rulePickerTriggerRef = useRef<HTMLButtonElement | null>(null);
  const playerPickerTriggerRef = useRef<HTMLButtonElement | null>(null);

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
  const previewLineupMutation = useMutation({
    mutationFn: (request: Parameters<typeof previewGameLineup>[0]) =>
      previewGameLineup(request),
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
  const pendingNextConfigs = pendingProfile
    ? upsertSeatProfile(
        visiblePlayerConfigs,
        safeActiveSeat,
        pendingProfile.id,
      )
    : null;
  const nextEmptySeatAfterConfirm = pendingNextConfigs
    ? findNextEmptySeat(
        pendingNextConfigs,
        playerCount,
        safeActiveSeat,
      )
    : undefined;
  const playerPickerConfirmLabel = !pendingProfile
    ? "请选择玩家"
    : pendingAssignedSeat && pendingAssignedSeat !== safeActiveSeat
      ? `移动到 ${safeActiveSeat} 号座位`
      : nextEmptySeatAfterConfirm
        ? "确认并下一位"
        : "完成阵容";
  const isLoading = ruleSetsQuery.isPending || playerProfilesQuery.isPending;
  const isSubmitDisabled =
    isLoading ||
    ruleSetsQuery.isError ||
    playerProfilesQuery.isError ||
    !selectedRuleSet ||
    createGameRunMutation.isPending ||
    previewLineupMutation.isPending;
  const isLaunchDisabled = isSubmitDisabled || !launchStatus.canLaunch;
  const canFillSeats =
    !isSubmitDisabled &&
    launchStatus.emptySeatCount > 0 &&
    launchStatus.profileShortageCount === 0;
  const isProfileDataFetching =
    playerProfilesQuery.isFetching || favoritesQuery.isFetching;

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
    clearLineupQuality();

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
    setValidationError(null);
    setShortage(false);
    clearLineupQuality();
    playerPickerTriggerRef.current = trigger;
    setIsPlayerPickerOpen(true);
  }

  function closeProfileDrawer() {
    setIsPlayerPickerOpen(false);
    setPendingProfileId(null);
  }

  function confirmPendingProfile() {
    if (!pendingProfile) {
      return;
    }

    const nextConfigs = upsertSeatProfile(
      visiblePlayerConfigs,
      safeActiveSeat,
      pendingProfile.id,
    );

    setValidationError(null);
    setShortage(false);
    setPlayerConfigs(nextConfigs);
    clearLineupQuality();
    setPendingProfileId(null);

    const nextEmptySeat = findNextEmptySeat(
      nextConfigs,
      playerCount,
      safeActiveSeat,
    );
    if (nextEmptySeat) {
      setActiveSeat(nextEmptySeat);
      return;
    }

    setIsPlayerPickerOpen(false);
  }

  function fillEmptySeats(options?: { favoritesOnly?: boolean }) {
    if (!selectedRuleSet || (options?.favoritesOnly && !favoritesAvailable)) {
      return;
    }
    setValidationError(null);
    setShortage(false);
    if (options?.favoritesOnly) {
      setPlayerConfigs(
        randomFillEmptySeats(
          visiblePlayerConfigs,
          profiles,
          selectedRuleSet.player_count,
          options,
        ),
      );
      clearLineupQuality();
      return;
    }
    requestLineupPreview("empty_only", [
      ...new Set(
        visiblePlayerConfigs
          .filter((config) => Boolean(config.profile_id))
          .map((config) => config.seat),
      ),
    ]);
  }

  function reshuffleLineup() {
    if (!selectedRuleSet) return;
    setValidationError(null);
    setShortage(false);
    requestLineupPreview("unlocked_all", []);
  }

  function requestLineupPreview(
    repairScope: "empty_only" | "unlocked_all",
    lockedSeats: number[],
    onSuccess?: (
      configs: PlayerConfig[],
      report: LineupQualityReport,
    ) => void,
  ) {
    if (!selectedRuleSet) return;
    setLineupQualityError(null);
    setQualityOverrideConfirmed(false);
    previewLineupMutation.mutate(
      {
        rule_set_id: selectedRuleSet.id,
        seed: seed ? Number(seed) : null,
        player_configs: normalizePlayerConfigs(
          visiblePlayerConfigs,
          selectedRuleSet.player_count,
        ),
        locked_seats: lockedSeats,
        repair_scope: repairScope,
        lineup_quality_policy_version: 1,
      },
      {
        onError: () => {
          setLineupQualityError("阵容质量检查失败，请保留当前阵容后重试。");
        },
        onSuccess: (result) => {
          setPlayerConfigs(result.player_configs);
          setLineupQualityReport(result.lineup_quality_report);
          setLineupQualityError(null);
          onSuccess?.(result.player_configs, result.lineup_quality_report);
        },
      },
    );
  }

  function clearLineupQuality() {
    setLineupQualityReport(null);
    setLineupQualityError(null);
    setQualityOverrideConfirmed(false);
  }

  function handleToggleProfileFavorite(profile: PublicPlayerProfileWithFavorite) {
    if (!favoritesAvailable) {
      return;
    }
    setValidationError(null);
    setShortage(false);
    updateProfileFavoriteMutation.mutate({
      isFavorite: !profile.is_favorite,
      profileId: profile.id,
    });
  }

  function handleClearSeats() {
    setPlayerConfigs([]);
    setShortage(false);
    setValidationError(null);
    clearLineupQuality();
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

    requestLineupPreview(
      "empty_only",
      normalizedPlayerConfigs.map((config) => config.seat),
      (validatedConfigs, report) => {
        if (report.is_blocked && !qualityOverrideConfirmed) {
          return;
        }
        createGameRunMutation.mutate({
          rule_set_id: selectedRuleSet.id,
          seed: seed ? Number(seed) : null,
          max_rounds: parsedMaxRounds,
          player_configs: validatedConfigs,
          lineup_quality_policy_version: 1,
          allow_lineup_quality_warnings:
            report.is_blocked && qualityOverrideConfirmed,
        });
      },
    );
  }

  return (
    <main
      className="mobile-page mobile-lobby-page"
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

      <LobbyRuleSummary
        changeButtonRef={rulePickerTriggerRef}
        disabled={
          createGameRunMutation.isPending ||
          previewLineupMutation.isPending ||
          ruleSetsQuery.isFetching
        }
        isError={ruleSetsQuery.isError}
        isLoading={ruleSetsQuery.isPending}
        onOpenPicker={openRulePicker}
        onRetry={() => void ruleSetsQuery.refetch()}
        ruleSet={selectedRuleSet}
      />

      {selectedRuleSet ? (
        <LobbyLineupSection
          activeSeat={safeActiveSeat}
          canFillSeats={canFillSeats}
          favoritesAvailable={favoritesAvailable}
          isBusy={
            createGameRunMutation.isPending || previewLineupMutation.isPending
          }
          launchStatus={launchStatus}
          qualityError={lineupQualityError}
          qualityOverrideConfirmed={qualityOverrideConfirmed}
          qualityReport={lineupQualityReport}
          onClear={handleClearSeats}
          onConfirmQualityOverride={() => setQualityOverrideConfirmed(true)}
          onFill={fillEmptySeats}
          onReshuffle={reshuffleLineup}
          onSelectSeat={openProfileDrawer}
          playerCount={playerCount}
          profilesBySeat={selectedProfilesBySeat}
        />
      ) : null}

      {playerProfilesQuery.isError ? (
        <p className="mobile-lobby-inline-error">玩家库加载失败</p>
      ) : null}

      <LobbyAdvancedSettings
        disabled={
          createGameRunMutation.isPending || previewLineupMutation.isPending
        }
        maxRounds={maxRounds}
        maxRoundsError={validationError}
        onMaxRoundsChange={(value) => {
          setMaxRounds(value);
          setValidationError(null);
        }}
        onSeedChange={(value) => {
          setSeed(value);
          clearLineupQuality();
        }}
        seed={seed}
      />

      <LobbyLaunchBar
        error={
          createGameRunMutation.isError
            ? "无法发起对局"
            : lineupQualityError
              ? lineupQualityError
            : shortage
              ? "玩家库玩家不足"
              : null
        }
        isLaunchDisabled={isLaunchDisabled}
        isPending={
          createGameRunMutation.isPending || previewLineupMutation.isPending
        }
        onLaunch={handleSubmit}
        status={launchStatus}
      />
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

      {isPlayerPickerOpen ? (
        <LobbyPlayerPicker
          activeSeat={safeActiveSeat}
          assignedSeatByProfileId={assignedSeatByProfileId}
          backgroundRef={lobbyContentRef}
          canConfirm={pendingProfile !== null}
          confirmLabel={playerPickerConfirmLabel}
          favoriteUpdateError={favoriteUpdateError}
          favoritesAvailable={favoritesAvailable}
          isRefreshing={isProfileDataFetching}
          onClose={closeProfileDrawer}
          onConfirm={confirmPendingProfile}
          onPendingProfileIdChange={setPendingProfileId}
          onRefresh={() =>
            Promise.all([
              playerProfilesQuery.refetch(),
              favoritesQuery.refetch(),
            ])
          }
          onToggleFavorite={handleToggleProfileFavorite}
          pendingFavoriteProfileIds={pendingFavoriteProfileIds}
          pendingProfileId={pendingProfileId}
          playerCount={playerCount}
          profiles={profiles}
          profilesError={playerProfilesQuery.isError}
          restoreFocusRef={playerPickerTriggerRef}
        />
      ) : null}
    </main>
  );
}
