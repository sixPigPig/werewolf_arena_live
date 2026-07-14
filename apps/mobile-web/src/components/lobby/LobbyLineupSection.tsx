import { useEffect, useState } from "react";
import {
  resolveAvatarImageUrl,
  type LineupQualityReport,
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
  qualityError: string | null;
  qualityOverrideConfirmed: boolean;
  qualityReport: LineupQualityReport | null;
  onClear: () => void;
  onConfirmQualityOverride: () => void;
  onFill: (options?: FillOptions) => void;
  onReshuffle: () => void;
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
  qualityError,
  qualityOverrideConfirmed,
  qualityReport,
  onClear,
  onConfirmQualityOverride,
  onFill,
  onReshuffle,
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
            onClick={() => {
              onReshuffle();
              setOpenMenu(null);
            }}
            type="button"
          >
            一键打散
          </button>
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

      {qualityReport || qualityError ? (
        <div
          aria-label="阵容质量"
          className={[
            "mobile-lobby-lineup-quality",
            qualityReport?.is_blocked
              ? "mobile-lobby-lineup-quality-blocked"
              : "",
          ]
            .filter(Boolean)
            .join(" ")}
          role="region"
        >
          {qualityError ? (
            <p>{qualityError}</p>
          ) : qualityReport ? (
            <>
              <div>
                <strong>
                  {qualityReport.is_blocked ? "阵容需要调整" : "阵容质量通过"}
                </strong>
                <span>
                  风格 {qualityReport.style_bucket_count}/
                  {qualityReport.required_style_bucket_count}
                  {qualityReport.was_repaired ? " · 已智能调整" : ""}
                </span>
              </div>
              {qualityReport.violations.length > 0 ? (
                <ul>
                  {qualityReport.violations.map((violation) => (
                    <li key={`${violation.code}:${violation.key}`}>
                      {lineupViolationLabel(violation.code)}：{violation.count}/
                      {violation.limit}
                      {violation.seat_numbers.length > 0
                        ? `（${violation.seat_numbers.join("、")}号）`
                        : ""}
                    </li>
                  ))}
                </ul>
              ) : null}
              {qualityReport.is_blocked &&
              qualityReport.policy_mode === "repair" &&
              !qualityOverrideConfirmed ? (
                <button
                  className="mobile-lobby-lineup-quality-override"
                  disabled={isBusy}
                  onClick={onConfirmQualityOverride}
                  type="button"
                >
                  仍使用当前阵容
                </button>
              ) : null}
              {qualityOverrideConfirmed ? <small>已确认承担阵容同质化风险</small> : null}
            </>
          ) : null}
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

function lineupViolationLabel(code: string) {
  const labels: Record<string, string> = {
    lineup_incomplete: "阵容未完整",
    personality_overrepresented: "同人格过多",
    strategy_profile_overrepresented: "同策略过多",
    catchphrase_overrepresented: "同口头禅过多",
    avatar_overrepresented: "同头像过多",
    tag_overrepresented: "同标签较多",
    insufficient_style_buckets: "风格覆盖不足",
  };
  return labels[code] ?? code;
}
