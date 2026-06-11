import {
  useEffect,
  useRef,
  useState,
  type RefObject,
} from "react";

import {
  applyProfileToSeat,
  clearSeat,
  hasPlayerConfig,
} from "../lineupUtils";
import { formatRoleSummary } from "../rulePresentation";
import type {
  PlayerConfig,
  RuleSetSummary,
  VirtualPlayerProfile,
} from "../types";
import { LineupSummary } from "./LineupSummary";
import { ProfilePicker } from "./ProfilePicker";
import { SeatDetailPanel } from "./SeatDetailPanel";
import { SeatGrid } from "./SeatGrid";

type LobbyLineupWorkbenchProps = {
  configs: PlayerConfig[];
  isProfileListLoaded: boolean;
  isRuleDetailsOpen: boolean;
  onChange: (configs: PlayerConfig[]) => void;
  onOpenRuleDetails: () => void;
  playerCount: number;
  profiles: VirtualPlayerProfile[];
  rule: RuleSetSummary;
  ruleDetailsTriggerRef: RefObject<HTMLButtonElement | null>;
};

export function LobbyLineupWorkbench({
  configs,
  isProfileListLoaded,
  isRuleDetailsOpen,
  onChange,
  onOpenRuleDetails,
  playerCount,
  profiles,
  rule,
  ruleDetailsTriggerRef,
}: LobbyLineupWorkbenchProps) {
  const [selectedSeat, setSelectedSeat] = useState(1);
  const playerColumnRef = useRef<HTMLDivElement | null>(null);
  const activeSeat = Math.min(selectedSeat, playerCount);
  const selectedConfig = configs.find((item) => item.seat === activeSeat);
  const selectedProfile = profiles.find(
    (profile) => profile.id === selectedConfig?.profile_id,
  );

  useEffect(() => {
    if (selectedSeat > playerCount) {
      const clampTimer = window.setTimeout(() => {
        setSelectedSeat(playerCount);
      }, 0);

      return () => window.clearTimeout(clampTimer);
    }
  }, [playerCount, selectedSeat]);

  const updateSeatConfig = (
    seat: number,
    updater: (config: PlayerConfig | undefined) => PlayerConfig | null,
  ) => {
    const existing = configs.find((config) => config.seat === seat);
    const nextConfig = updater(existing);
    const nextConfigs = configs
      .filter((config) => config.seat !== seat)
      .concat(nextConfig ? [nextConfig] : [])
      .sort((left, right) => left.seat - right.seat);

    onChange(nextConfigs);
  };

  const updateSeatModel = (model: string) => {
    updateSeatConfig(activeSeat, (existing) => {
      if (!model) {
        const nextConfig = { ...(existing ?? { seat: activeSeat }) };
        delete nextConfig.model;

        return hasPlayerConfig(nextConfig) ? nextConfig : null;
      }

      return {
        ...(existing ?? { seat: activeSeat }),
        seat: activeSeat,
        model,
      };
    });
  };

  const selectSeat = (seat: number) => {
    setSelectedSeat(seat);
    if (typeof window !== "undefined" && window.innerWidth <= 720) {
      playerColumnRef.current?.scrollIntoView?.({
        behavior: "smooth",
        block: "start",
      });
    }
  };

  return (
    <section
      aria-labelledby="lobby-lineup-title"
      className="lobby-lineup-workbench"
      data-testid="lobby-lineup-workbench"
    >
      <div
        className="lobby-workbench-column lobby-lineup-column"
        data-testid="lobby-lineup-column"
      >
        <header className="lobby-column-header">
          <div>
            <h2 id="lobby-lineup-title">组建阵容</h2>
            <span>
              {rule.name} · {playerCount} 个座位
            </span>
          </div>
          <button
            aria-expanded={isRuleDetailsOpen}
            aria-haspopup="dialog"
            className="gothic-button gothic-button-sm"
            data-intent="default"
            onClick={onOpenRuleDetails}
            ref={ruleDetailsTriggerRef}
            type="button"
          >
            <span className="gothic-button-content">
              <span className="gothic-button-label">规则详情</span>
            </span>
          </button>
        </header>
        <p className="lobby-rule-summary">{formatRoleSummary(rule)}</p>
        <LineupSummary
          configs={configs}
          playerCount={playerCount}
          profiles={profiles}
        />
        <SeatGrid
          configs={configs}
          onSelectSeat={selectSeat}
          playerCount={playerCount}
          profiles={profiles}
          selectedSeat={activeSeat}
        />
      </div>
      <div
        className="lobby-workbench-column lobby-player-column"
        data-testid="lobby-player-column"
        ref={playerColumnRef}
      >
        <div className="lobby-column-header">
          <div>
            <h2>玩家卡牌库</h2>
            <span>当前席位 · {activeSeat} 号</span>
          </div>
        </div>
        <ProfilePicker
          configs={configs}
          isProfileListLoaded={isProfileListLoaded}
          onSelectProfile={(profileId) =>
            onChange(applyProfileToSeat(configs, activeSeat, profileId))
          }
          profiles={profiles}
          selectedSeat={activeSeat}
        />
        <SeatDetailPanel
          onClearSeat={() => onChange(clearSeat(configs, activeSeat))}
          onModelChange={updateSeatModel}
          selectedConfig={selectedConfig}
          selectedProfile={selectedProfile}
          selectedSeat={activeSeat}
        />
      </div>
    </section>
  );
}
