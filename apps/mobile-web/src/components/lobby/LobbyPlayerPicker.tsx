import {
  resolveAvatarImageUrl,
  type PublicPlayerProfileWithFavorite,
} from "@werewolf-arena/game-client";
import { LoaderCircle, Star, StarCheck } from "lucide-react";
import { type RefObject, useEffect, useMemo, useRef, useState } from "react";

import { MobileBottomSelect } from "../MobileBottomSelect";
import {
  filterProfiles,
  formatStrategyLabel,
  getProfileChoiceAriaLabel,
  getProfileSeatStatusLabel,
  getStrategyFilterOptions,
} from "./lobbyModel";
import { LobbyModal } from "./LobbyModal";

type LobbyPlayerPickerProps = {
  activeSeat: number;
  assignedSeatByProfileId: ReadonlyMap<string, number>;
  backgroundRef: RefObject<HTMLElement | null>;
  canConfirm: boolean;
  confirmLabel: string;
  favoriteUpdateError: string | null;
  favoritesAvailable: boolean;
  isRefreshing: boolean;
  onClose: () => void;
  onConfirm: () => void;
  onPendingProfileIdChange: (profileId: string | null) => void;
  onRefresh: () => Promise<unknown>;
  onToggleFavorite: (profile: PublicPlayerProfileWithFavorite) => void;
  pendingFavoriteProfileIds: ReadonlySet<string>;
  pendingProfileId: string | null;
  playerCount: number;
  profiles: PublicPlayerProfileWithFavorite[];
  profilesError: boolean;
  restoreFocusRef: RefObject<HTMLElement | null>;
};

export function LobbyPlayerPicker({
  activeSeat,
  assignedSeatByProfileId,
  backgroundRef,
  canConfirm,
  confirmLabel,
  favoriteUpdateError,
  favoritesAvailable,
  isRefreshing,
  onClose,
  onConfirm,
  onPendingProfileIdChange,
  onRefresh,
  onToggleFavorite,
  pendingFavoriteProfileIds,
  pendingProfileId,
  playerCount,
  profiles,
  profilesError,
  restoreFocusRef,
}: LobbyPlayerPickerProps) {
  const [search, setSearch] = useState("");
  const [favoriteFilter, setFavoriteFilter] = useState<"all" | "favorite">(
    "all",
  );
  const [strategyFilter, setStrategyFilter] = useState("all");
  const [isFilterPanelOpen, setIsFilterPanelOpen] = useState(false);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const filterPortalRef = useRef<HTMLDivElement | null>(null);
  const pullStartRef = useRef<number | null>(null);
  const pullDistanceRef = useRef(0);
  const [pullDistance, setPullDistance] = useState(0);
  const appliedFavoriteFilter = favoritesAvailable ? favoriteFilter : "all";
  const filteredProfiles = useMemo(
    () =>
      filterProfiles(profiles, {
        favoriteFilter: appliedFavoriteFilter,
        search,
        strategy: strategyFilter,
      }),
    [appliedFavoriteFilter, profiles, search, strategyFilter],
  );
  const strategyOptions = useMemo(
    () => getStrategyFilterOptions(profiles),
    [profiles],
  );

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      setSearch("");
      searchRef.current?.focus();
    });

    return () => window.cancelAnimationFrame(frame);
  }, [activeSeat]);

  function setPull(distance: number) {
    pullDistanceRef.current = distance;
    setPullDistance(distance);
  }

  function startPull(clientY: number) {
    if (!isRefreshing && (listRef.current?.scrollTop ?? 0) <= 0) {
      pullStartRef.current = clientY;
    }
  }

  function movePull(clientY: number) {
    if (pullStartRef.current === null) {
      return;
    }

    setPull(Math.max(0, Math.min(clientY - pullStartRef.current, 96)));
  }

  function endPull() {
    if (pullDistanceRef.current >= 64) {
      void onRefresh().finally(() => {
        pullStartRef.current = null;
        setPull(0);
      });
      return;
    }

    pullStartRef.current = null;
    setPull(0);
  }

  return (
    <LobbyModal
      backgroundRef={backgroundRef}
      className="mobile-profile-picker"
      initialFocusRef={searchRef}
      labelledBy="mobile-profile-picker-title"
      onClose={onClose}
      restoreFocusRef={restoreFocusRef}
    >
      <header className="mobile-lobby-modal-header">
        <div>
          <h2 id="mobile-profile-picker-title">玩家卡牌库</h2>
          <p>{`当前选择：${activeSeat}号座位 · 已选 ${assignedSeatByProfileId.size}/${playerCount}`}</p>
        </div>
        <button aria-label="关闭玩家卡牌库" onClick={onClose} type="button">
          ×
        </button>
      </header>

      <label className="mobile-profile-search">
        <span>搜索玩家</span>
        <input
          aria-label="搜索玩家"
          onChange={(event) => setSearch(event.target.value)}
          ref={searchRef}
          type="search"
          value={search}
        />
      </label>

      <button
        aria-expanded={isFilterPanelOpen}
        aria-label={`筛选玩家，当前 ${appliedFavoriteFilter === "favorite" ? "只看收藏" : "全部玩家"}、${strategyFilter === "all" ? "全部策略" : formatStrategyLabel(strategyFilter)}`}
        className="mobile-profile-filter-trigger"
        onClick={() => setIsFilterPanelOpen((open) => !open)}
        type="button"
      >
        筛选
      </button>

      {isFilterPanelOpen ? (
        <div
          aria-label="玩家筛选"
          className="mobile-profile-filter-panel"
          role="group"
        >
          <MobileBottomSelect
            disabled={!favoritesAvailable}
            getContainer={() => filterPortalRef.current ?? document.body}
            label="收藏"
            onChange={setFavoriteFilter}
            options={[
              { label: "全部玩家", value: "all" },
              { label: "只看收藏", value: "favorite" },
            ]}
            value={appliedFavoriteFilter}
          />
          <MobileBottomSelect
            getContainer={() => filterPortalRef.current ?? document.body}
            label="策略"
            onChange={setStrategyFilter}
            options={[
              { label: "全部策略", value: "all" },
              ...strategyOptions.map((strategy) => ({
                label: formatStrategyLabel(strategy),
                value: strategy,
              })),
            ]}
            value={strategyFilter}
          />
        </div>
      ) : null}
      <div className="mobile-profile-filter-portal" ref={filterPortalRef} />

      {!favoritesAvailable ? (
        <p role="status">收藏状态暂不可用，仍可正常选择玩家。</p>
      ) : null}
      {favoriteUpdateError ? <p role="alert">{favoriteUpdateError}</p> : null}

      <div
        className="mobile-profile-picker-list"
        onMouseDown={(event) => startPull(event.clientY)}
        onMouseLeave={endPull}
        onMouseMove={(event) => movePull(event.clientY)}
        onMouseUp={endPull}
        onTouchCancel={endPull}
        onTouchEnd={endPull}
        onTouchMove={(event) => movePull(event.touches[0]?.clientY ?? 0)}
        onTouchStart={(event) => startPull(event.touches[0]?.clientY ?? 0)}
        ref={listRef}
      >
        <div aria-live="polite" className="mobile-profile-refresh-status">
          {isRefreshing ? <LoaderCircle aria-hidden="true" /> : null}
          <span>
            {isRefreshing
              ? "正在刷新玩家"
              : pullDistance >= 64
                ? "松开刷新玩家"
                : ""}
          </span>
        </div>

        {profilesError ? (
          <button onClick={() => void onRefresh()} type="button">
            重新加载玩家
          </button>
        ) : null}
        {!profilesError && filteredProfiles.length === 0 ? (
          <div className="mobile-profile-empty">
            <p>没有匹配的玩家</p>
            <button
              onClick={() => {
                setSearch("");
                setFavoriteFilter("all");
                setStrategyFilter("all");
              }}
              type="button"
            >
              清除筛选
            </button>
          </div>
        ) : null}

        {filteredProfiles.map((profile) => {
          const seatStatusLabel = getProfileSeatStatusLabel(
            assignedSeatByProfileId.get(profile.id),
            activeSeat,
          );
          const avatarUrl = resolveAvatarImageUrl(profile);

          return (
            <article className="mobile-profile-row" key={profile.id}>
              <button
                aria-label={getProfileChoiceAriaLabel(
                  activeSeat,
                  profile,
                  seatStatusLabel,
                )}
                aria-pressed={pendingProfileId === profile.id}
                className="mobile-profile-row-select"
                onClick={() => onPendingProfileIdChange(profile.id)}
                type="button"
              >
                {avatarUrl ? (
                  <img alt="" aria-hidden="true" src={avatarUrl} />
                ) : (
                  <span
                    aria-hidden="true"
                    className="mobile-profile-row-avatar-fallback"
                  />
                )}
                <span className="mobile-profile-row-copy">
                  <strong>{profile.display_name}</strong>
                  <small>{formatStrategyLabel(profile.strategy_profile)}</small>
                  {seatStatusLabel ? <em>{seatStatusLabel}</em> : null}
                </span>
              </button>
              <button
                aria-label={`${profile.is_favorite ? "取消收藏" : "收藏"} ${profile.display_name}`}
                aria-pressed={profile.is_favorite}
                className="mobile-profile-row-favorite"
                disabled={
                  !favoritesAvailable ||
                  pendingFavoriteProfileIds.has(profile.id)
                }
                onClick={() => onToggleFavorite(profile)}
                type="button"
              >
                {profile.is_favorite ? (
                  <StarCheck
                    aria-hidden="true"
                    className="mobile-profile-row-favorite-icon"
                  />
                ) : (
                  <Star
                    aria-hidden="true"
                    className="mobile-profile-row-favorite-icon"
                  />
                )}
              </button>
            </article>
          );
        })}
      </div>

      <footer className="mobile-profile-picker-footer">
        {pendingProfileId && !canConfirm ? (
          <span role="status">候选已失效，请重新选择</span>
        ) : null}
        <button disabled={!canConfirm} onClick={onConfirm} type="button">
          {confirmLabel}
        </button>
      </footer>
    </LobbyModal>
  );
}
