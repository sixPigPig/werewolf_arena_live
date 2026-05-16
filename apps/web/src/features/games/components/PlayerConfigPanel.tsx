import { SelectField, Text, TextField } from "../../../components/ui";

import { appearanceLabel, personalityLabel } from "../playerProfileOptions";
import type { PlayerConfig, VirtualPlayerProfile } from "../types";

type PlayerConfigPanelProps = {
  playerCount: number;
  profiles: VirtualPlayerProfile[];
  configs: PlayerConfig[];
  onChange: (configs: PlayerConfig[]) => void;
};

export function PlayerConfigPanel({
  playerCount,
  profiles,
  configs,
  onChange,
}: PlayerConfigPanelProps) {
  const seats = Array.from({ length: playerCount }, (_, index) => index + 1);

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

  return (
    <section
      aria-labelledby="player-config-panel-title"
      className="player-config-panel"
    >
      <div className="player-config-panel-header">
        <h3 className="player-config-panel-title" id="player-config-panel-title">
          虚拟玩家
        </h3>
        <Text as="span" className="player-config-panel-count" size="2">
          {playerCount} 个座位
        </Text>
      </div>
      <div className="player-config-panel-grid">
        {seats.map((seat) => {
          const config = configs.find((item) => item.seat === seat);
          const selectedProfile = profiles.find(
            (profile) => profile.id === config?.profile_id,
          );

          return (
            <div className="player-config-seat" key={seat}>
              <label className="player-config-seat-label">
                <span>{seat} 号座位</span>
                <SelectField
                  aria-label={`${seat} 号座位虚拟玩家`}
                  className="player-config-select"
                  value={config?.profile_id ?? ""}
                  onChange={(event) => {
                    const profileId = event.target.value;
                    updateSeatConfig(seat, (existing) => {
                      if (!profileId) {
                        const nextConfig = { ...(existing ?? { seat }) };
                        delete nextConfig.profile_id;

                        return hasSeatConfig(nextConfig) ? nextConfig : null;
                      }

                      return {
                        ...(existing ?? { seat }),
                        seat,
                        profile_id: profileId,
                      };
                    });
                  }}
                >
                  <option value="">随机玩家</option>
                  {profiles.map((profile) => (
                    <option key={profile.id} value={profile.id}>
                      {profile.display_name}
                    </option>
                  ))}
                </SelectField>
              </label>
              <TextField.Root
                aria-label={`${seat} 号座位模型覆盖`}
                className="player-config-model"
                placeholder={selectedProfile?.model || "按身份默认"}
                value={config?.model ?? ""}
                onChange={(event) => {
                  const model = event.target.value;
                  updateSeatConfig(seat, (existing) => {
                    if (!model) {
                      const nextConfig = { ...(existing ?? { seat }) };
                      delete nextConfig.model;

                      return hasSeatConfig(nextConfig) ? nextConfig : null;
                    }

                    return { ...(existing ?? { seat }), seat, model };
                  });
                }}
              />
              {selectedProfile ? (
                <p className="player-config-summary">
                  {personalityLabel(selectedProfile.personality_id)} ·{" "}
                  {appearanceLabel(selectedProfile.appearance_id)}
                </p>
              ) : null}
            </div>
          );
        })}
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
