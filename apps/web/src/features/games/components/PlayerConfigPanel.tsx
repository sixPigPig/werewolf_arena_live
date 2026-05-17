import { useState } from "react";

import { Text } from "../../../components/ui";

import {
  applyProfileToSeat,
  clearAllSeats,
  clearSeat,
  hasPlayerConfig,
  randomFillEmptySeats,
} from "../lineupUtils";
import type { PlayerConfig, VirtualPlayerProfile } from "../types";
import { LineupSummary } from "./LineupSummary";
import { ProfilePicker } from "./ProfilePicker";
import { SeatDetailPanel } from "./SeatDetailPanel";
import { SeatGrid } from "./SeatGrid";

type PlayerConfigPanelProps = {
  playerCount: number;
  profiles: VirtualPlayerProfile[];
  isProfileListLoaded?: boolean;
  configs: PlayerConfig[];
  onChange: (configs: PlayerConfig[]) => void;
};

export function PlayerConfigPanel({
  playerCount,
  profiles,
  isProfileListLoaded = true,
  configs,
  onChange,
}: PlayerConfigPanelProps) {
  const [selectedSeat, setSelectedSeat] = useState(1);
  const activeSeat = Math.min(selectedSeat, playerCount);
  const selectedConfig = configs.find((item) => item.seat === activeSeat);
  const selectedProfile = profiles.find(
    (profile) => profile.id === selectedConfig?.profile_id,
  );

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

        return hasSeatConfig(nextConfig) ? nextConfig : null;
      }

      return {
        ...(existing ?? { seat: activeSeat }),
        seat: activeSeat,
        model,
      };
    });
  };

  return (
    <section
      aria-labelledby="player-seat-module-title"
      className="player-config-panel"
    >
      <div className="player-config-panel-header">
        <h3 className="player-config-panel-title" id="player-seat-module-title">
          席位模块
        </h3>
        <Text as="span" className="player-config-panel-count" size="2">
          {playerCount} 个座位
        </Text>
      </div>
      <LineupSummary
        configs={configs}
        playerCount={playerCount}
        profiles={profiles}
      />
      <div className="player-config-panel-grid">
        <SeatGrid
          configs={configs}
          onSelectSeat={setSelectedSeat}
          playerCount={playerCount}
          profiles={profiles}
          selectedSeat={activeSeat}
        />
        <div className="player-config-role-module">
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
            onClearAllSeats={() => onChange(clearAllSeats())}
            onClearSeat={() => onChange(clearSeat(configs, activeSeat))}
            onFillFavorites={() =>
              onChange(
                randomFillEmptySeats(configs, profiles, playerCount, {
                  favoritesOnly: true,
                }),
              )
            }
            onModelChange={updateSeatModel}
            onRandomFill={() =>
              onChange(randomFillEmptySeats(configs, profiles, playerCount))
            }
            selectedConfig={selectedConfig}
            selectedProfile={selectedProfile}
            selectedSeat={activeSeat}
          />
        </div>
      </div>
    </section>
  );
}

function hasSeatConfig(config: PlayerConfig) {
  return hasPlayerConfig(config);
}
