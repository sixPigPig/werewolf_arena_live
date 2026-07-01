import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { Button, SelectField, TextField } from "../../../components/ui";

import { personalityLabel, PERSONALITY_OPTIONS } from "../playerProfileOptions";
import { STRATEGY_OPTIONS } from "../playerStrategyOptions";
import {
  resolveAvatarImageUrl,
  type PlayerConfig,
  type VirtualPlayerProfile,
} from "../types";

type ProfilePickerProps = {
  configs: PlayerConfig[];
  isProfileListLoaded: boolean;
  profiles: VirtualPlayerProfile[];
  selectedSeat: number;
  onSelectProfile: (profileId: string) => void;
};

export function ProfilePicker({
  configs,
  isProfileListLoaded,
  profiles,
  selectedSeat,
  onSelectProfile,
}: ProfilePickerProps) {
  const [searchTerm, setSearchTerm] = useState("");
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [selectedModel, setSelectedModel] = useState("");
  const [selectedPersonality, setSelectedPersonality] = useState("");
  const [selectedStrategy, setSelectedStrategy] = useState("");

  const occupiedSeatByProfileId = useMemo(() => {
    const occupied = new Map<string, number>();
    configs.forEach((config) => {
      if (config.profile_id) {
        occupied.set(config.profile_id, config.seat);
      }
    });
    return occupied;
  }, [configs]);

  const modelOptions = useMemo(
    () => [...new Set(profiles.map((profile) => profile.model).filter(Boolean))],
    [profiles],
  );

  const strategyOptions = useMemo(
    () =>
      STRATEGY_OPTIONS.filter((option) =>
        profiles.some((profile) => profile.strategy_profile === option.id),
      ),
    [profiles],
  );

  const filteredProfiles = useMemo(() => {
    const normalizedSearch = searchTerm.trim().toLowerCase();

    return profiles
      .filter((profile) => {
        const haystack = [
          profile.display_name,
          profile.short_description,
          profile.model,
          profile.personality_id,
          profile.strategy_profile,
          ...(profile.tags ?? []),
        ]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();

        return (
          (!normalizedSearch || haystack.includes(normalizedSearch)) &&
          (!favoritesOnly || profile.favorite) &&
          (!selectedModel || profile.model === selectedModel) &&
          (!selectedPersonality || profile.personality_id === selectedPersonality) &&
          (!selectedStrategy || profile.strategy_profile === selectedStrategy)
        );
      })
      .sort((left, right) => {
        const leftOccupied = occupiedSeatByProfileId.has(left.id);
        const rightOccupied = occupiedSeatByProfileId.has(right.id);
        if (left.favorite !== right.favorite) {
          return left.favorite ? -1 : 1;
        }
        if (leftOccupied !== rightOccupied) {
          return leftOccupied ? 1 : -1;
        }
        return Date.parse(right.updated_at) - Date.parse(left.updated_at);
      });
  }, [
    favoritesOnly,
    occupiedSeatByProfileId,
    profiles,
    searchTerm,
    selectedModel,
    selectedPersonality,
    selectedStrategy,
  ]);

  return (
    <div className="profile-picker">
      <div className="profile-picker-header">
        <div>
          <h3 className="player-config-role-title">选择虚拟玩家</h3>
          <span className="player-config-role-seat">{selectedSeat} 号座位</span>
        </div>
        <Button
          aria-pressed={favoritesOnly}
          intent={favoritesOnly ? "warning" : "default"}
          onClick={() => setFavoritesOnly((value) => !value)}
          size="1"
          skin="gothic"
          type="button"
        >
          只看收藏
        </Button>
      </div>
      <div className="profile-picker-filters">
        <label className="profile-picker-search">
          <span>搜索可选虚拟玩家</span>
          <TextField.Root
            aria-label="搜索可选虚拟玩家"
            className="player-config-model"
            placeholder="搜索名称、标签、模型"
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
          />
        </label>
        <SelectField
          aria-label="筛选模型"
          className="profile-picker-select"
          value={selectedModel}
          onChange={(event) => setSelectedModel(event.target.value)}
        >
          <option value="">全部模型</option>
          {modelOptions.map((model) => (
            <option key={model} value={model}>
              {model}
            </option>
          ))}
        </SelectField>
        <SelectField
          aria-label="筛选性格"
          className="profile-picker-select"
          value={selectedPersonality}
          onChange={(event) => setSelectedPersonality(event.target.value)}
        >
          <option value="">全部性格</option>
          {PERSONALITY_OPTIONS.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </SelectField>
        <SelectField
          aria-label="筛选策略"
          className="profile-picker-select"
          value={selectedStrategy}
          onChange={(event) => setSelectedStrategy(event.target.value)}
        >
          <option value="">全部策略</option>
          {strategyOptions.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </SelectField>
      </div>
      <div
        className="player-config-role-cards"
        data-testid="lobby-player-card-grid"
      >
        {filteredProfiles.map((profile) => {
          const occupiedSeat = occupiedSeatByProfileId.get(profile.id);
          const isCurrentSeat = occupiedSeat === selectedSeat;
          const isOccupiedElsewhere = Boolean(
            occupiedSeat && occupiedSeat !== selectedSeat,
          );
          const avatarImageUrl = resolveAvatarImageUrl(profile);

          return (
            <button
              aria-label={`为 ${selectedSeat} 号座位选择 ${profile.display_name}`}
              className={[
                "player-config-role-card",
                isCurrentSeat ? "player-config-role-card-selected" : "",
                isOccupiedElsewhere ? "player-config-role-card-disabled" : "",
              ].join(" ")}
              disabled={isOccupiedElsewhere}
              key={profile.id}
              onClick={() => onSelectProfile(profile.id)}
              type="button"
            >
              <span className="player-config-role-portrait">
                {avatarImageUrl ? (
                  <img
                    alt={`${profile.display_name} 人物形象`}
                    src={avatarImageUrl}
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
                {personalityLabel(profile.personality_id)} · {profile.model}
              </span>
              {occupiedSeat ? (
                <span className="profile-picker-occupied">
                  已在 {occupiedSeat} 号位
                </span>
              ) : null}
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
        {profiles.length > 0 && filteredProfiles.length === 0 ? (
          <p className="player-config-role-empty-copy profile-picker-empty">
            没有符合条件的虚拟玩家。
          </p>
        ) : null}
      </div>
    </div>
  );
}
