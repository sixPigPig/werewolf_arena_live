import { useState } from "react";
import { Link } from "react-router-dom";

import { Button, Text, TextField } from "../../../components/ui";

import { appearanceLabel, personalityLabel } from "../playerProfileOptions";
import type { PlayerConfig, VirtualPlayerProfile } from "../types";

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
  const seats = Array.from({ length: playerCount }, (_, index) => index + 1);
  const [selectedSeat, setSelectedSeat] = useState(1);
  const selectedConfig = configs.find((item) => item.seat === selectedSeat);
  const selectedProfile = profiles.find(
    (profile) => profile.id === selectedConfig?.profile_id,
  );
  const [pendingSelection, setPendingSelection] = useState<{
    seat: number;
    profileId: string;
  } | null>(null);
  const pendingProfileId =
    pendingSelection?.seat === selectedSeat
      ? pendingSelection.profileId
      : (selectedConfig?.profile_id ?? "");

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

  const confirmProfileSelection = () => {
    updateSeatConfig(selectedSeat, (existing) => {
      if (!pendingProfileId) {
        const nextConfig = { ...(existing ?? { seat: selectedSeat }) };
        delete nextConfig.profile_id;

        return hasSeatConfig(nextConfig) ? nextConfig : null;
      }

      return {
        ...(existing ?? { seat: selectedSeat }),
        seat: selectedSeat,
        profile_id: pendingProfileId,
      };
    });
    setPendingSelection(null);
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
      <div className="player-config-panel-grid">
        <div className="player-config-seat-module">
          {seats.map((seat) => {
            const config = configs.find((item) => item.seat === seat);
            const profile = profiles.find(
              (item) => item.id === config?.profile_id,
            );
            const isSelected = selectedSeat === seat;

            return (
              <button
                aria-label={`${seat}号${profile ? profile.display_name : "空席"}`}
                className={[
                  "player-config-seat-card",
                  isSelected ? "player-config-seat-card-selected" : "",
                  profile ? "player-config-seat-card-filled" : "",
                ].join(" ")}
                key={seat}
                onClick={() => setSelectedSeat(seat)}
                type="button"
              >
                <span className="player-config-seat-frame">
                  {profile?.avatar_image_url ? (
                    <img
                      alt=""
                      aria-hidden="true"
                      src={profile.avatar_image_url}
                    />
                  ) : null}
                </span>
                <span className="player-config-seat-name">
                  {seat}号{profile ? profile.display_name : "空席"}
                </span>
              </button>
            );
          })}
        </div>
        <div className="player-config-role-module">
          <div className="player-config-role-header">
            <h3 className="player-config-role-title">选择席位角色</h3>
            <span className="player-config-role-seat">{selectedSeat} 号座位</span>
          </div>
          <div className="player-config-role-cards">
            {profiles.map((profile) => {
              const isPending = pendingProfileId === profile.id;

              return (
                <button
                  aria-label={`为 ${selectedSeat} 号座位选择 ${profile.display_name}`}
                  className={[
                    "player-config-role-card",
                    isPending ? "player-config-role-card-selected" : "",
                  ].join(" ")}
                  key={profile.id}
                  onClick={() =>
                    setPendingSelection({ seat: selectedSeat, profileId: profile.id })
                  }
                  type="button"
                >
                  <span className="player-config-role-portrait">
                    {profile.avatar_image_url ? (
                      <img
                        alt={`${profile.display_name} 人物形象`}
                        src={profile.avatar_image_url}
                      />
                    ) : (
                      <span aria-hidden="true">
                        {profile.display_name.trim().charAt(0) || "?"}
                      </span>
                    )}
                  </span>
                  <span className="player-config-role-name">
                    {profile.display_name}
                  </span>
                  <span className="player-config-role-meta">
                    {personalityLabel(profile.personality_id)} ·{" "}
                    {appearanceLabel(profile.appearance_id)}
                  </span>
                </button>
              );
            })}
            {isProfileListLoaded && profiles.length === 0 ? (
              <div className="player-config-role-empty">
                <p className="player-config-role-empty-copy">暂无虚拟玩家</p>
                <Button asChild intent="primary" size="1" skin="gothic">
                  <Link to="/players">去玩家库创建</Link>
                </Button>
              </div>
            ) : null}
          </div>
          <div className="player-config-role-controls">
            <label className="player-config-seat-model-field">
              <span>{selectedSeat} 号座位模型覆盖</span>
              <TextField.Root
                aria-label={`${selectedSeat} 号座位模型覆盖`}
                className="player-config-model"
                placeholder={selectedProfile?.model || "按身份默认"}
                value={selectedConfig?.model ?? ""}
                onChange={(event) => {
                  const model = event.target.value;
                  updateSeatConfig(selectedSeat, (existing) => {
                    if (!model) {
                      const nextConfig = { ...(existing ?? { seat: selectedSeat }) };
                      delete nextConfig.model;

                      return hasSeatConfig(nextConfig) ? nextConfig : null;
                    }

                    return {
                      ...(existing ?? { seat: selectedSeat }),
                      seat: selectedSeat,
                      model,
                    };
                  });
                }}
              />
            </label>
            <div className="player-config-role-actions">
              <Button
                onClick={() =>
                  setPendingSelection({ seat: selectedSeat, profileId: "" })
                }
                size="1"
                skin="gothic"
                type="button"
              >
                随机角色
              </Button>
              <Button
                intent="warning"
                onClick={confirmProfileSelection}
                size="1"
                skin="gothic"
                type="button"
              >
                确认选择
              </Button>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function hasSeatConfig(config: PlayerConfig) {
  return Boolean(
    config.profile_id ||
      config.model ||
      config.personality_id ||
      config.appearance_id,
  );
}
