import { useEffect, useState } from "react";
import {
  resolveAvatarImageUrl,
  type PublicPlayerProfileWithFavorite,
} from "@werewolf-arena/game-client";

import type { LineupLaunchStatus } from "./lobbyModel";

type FillOptions = { favoritesOnly?: boolean };

type LobbyLineupSectionProps = {
  activeSeat: number;
  canFillSeats: boolean;
  favoritesAvailable: boolean;
  isBusy: boolean;
  launchStatus: LineupLaunchStatus;
  onClear: () => void;
  onFill: (options?: FillOptions) => void;
  onSelectSeat: (seat: number, trigger: HTMLButtonElement) => void;
  playerCount: number;
  profilesBySeat: ReadonlyMap<
    number,
    PublicPlayerProfileWithFavorite | null
  >;
};

export function LobbyLineupSection({
  activeSeat,
  canFillSeats,
  favoritesAvailable,
  isBusy,
  launchStatus,
  onClear,
  onFill,
  onSelectSeat,
  playerCount,
  profilesBySeat,
}: LobbyLineupSectionProps) {
  const [openMenu, setOpenMenu] = useState<"fill" | "more" | null>(null);
  const [isClearConfirming, setIsClearConfirming] = useState(false);

  useEffect(() => {
    if (!isClearConfirming) return;
    const timeout = window.setTimeout(() => setIsClearConfirming(false), 3000);
    return () => window.clearTimeout(timeout);
  }, [isClearConfirming]);

  return (
    <section
      aria-labelledby="mobile-seat-title"
      className="mobile-lobby-section mobile-lobby-board-section mobile-lobby-lineup-section"
    >
      <div className="mobile-lobby-section-heading mobile-lobby-lineup-heading">
        <div>
          <h2 id="mobile-seat-title">组建阵容</h2>
          <span className="mobile-lobby-seat-summary">
            {launchStatus.summaryText}
          </span>
        </div>
        <div className="mobile-lobby-lineup-actions">
          <button
            aria-expanded={openMenu === "fill"}
            disabled={!canFillSeats || isBusy}
            onClick={() =>
              setOpenMenu((menu) => (menu === "fill" ? null : "fill"))
            }
            type="button"
          >
            智能补齐
          </button>
          <button
            aria-expanded={openMenu === "more"}
            aria-label="阵容更多操作"
            disabled={isBusy}
            onClick={() =>
              setOpenMenu((menu) => (menu === "more" ? null : "more"))
            }
            type="button"
          >
            ⋯
          </button>
        </div>
      </div>

      {openMenu === "fill" ? (
        <div
          aria-label="智能补齐方式"
          className="mobile-lobby-lineup-menu"
          role="group"
        >
          <button
            disabled={!favoritesAvailable}
            onClick={() => {
              onFill({ favoritesOnly: true });
              setOpenMenu(null);
            }}
            type="button"
          >
            收藏补齐
          </button>
          <button
            onClick={() => {
              onFill();
              setOpenMenu(null);
            }}
            type="button"
          >
            随机补齐
          </button>
        </div>
      ) : null}

      {openMenu === "more" ? (
        <div
          aria-label="阵容操作"
          className="mobile-lobby-lineup-menu"
          role="group"
        >
          <button
            onClick={() => {
              if (!isClearConfirming) {
                setIsClearConfirming(true);
                return;
              }
              onClear();
              setIsClearConfirming(false);
              setOpenMenu(null);
            }}
            type="button"
          >
            {isClearConfirming ? "确认清空阵容" : "清空阵容"}
          </button>
        </div>
      ) : null}

      <div className="mobile-lobby-seat-grid">
        {Array.from({ length: playerCount }, (_, index) => index + 1).map(
          (seat) => {
            const profile = profilesBySeat.get(seat) ?? null;
            const displayName = profile?.display_name ?? "待选择";
            const avatar = profile ? resolveAvatarImageUrl(profile) : "";

            return (
              <button
                aria-label={`选择 ${seat} 号座位，当前为 ${displayName}`}
                aria-pressed={activeSeat === seat}
                className={[
                  "mobile-lobby-seat-card",
                  activeSeat === seat ? "mobile-lobby-seat-card-active" : "",
                  profile ? "mobile-lobby-seat-card-filled" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                disabled={isBusy}
                key={seat}
                onClick={(event) => onSelectSeat(seat, event.currentTarget)}
                type="button"
              >
                {profile ? (
                  <span className="mobile-lobby-seat-avatar">
                    <span aria-hidden="true" />
                    {avatar ? (
                      <img
                        alt=""
                        aria-hidden="true"
                        onError={(event) => {
                          event.currentTarget.hidden = true;
                        }}
                        src={avatar}
                      />
                    ) : null}
                  </span>
                ) : null}
                <span className="mobile-lobby-seat-number">
                  {String(seat).padStart(2, "0")}
                </span>
                <strong>{displayName}</strong>
              </button>
            );
          },
        )}
      </div>
    </section>
  );
}
