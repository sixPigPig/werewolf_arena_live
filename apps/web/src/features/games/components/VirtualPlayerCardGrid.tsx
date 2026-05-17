import { useMemo, useState } from "react";

import { Button, SelectField, TextField } from "../../../components/ui";
import {
  PERSONALITY_OPTIONS,
  appearanceClassName,
  personalityLabel,
} from "../playerProfileOptions";
import { STRATEGY_OPTIONS } from "../playerStrategyOptions";
import type { VirtualPlayerProfile } from "../types";

type VirtualPlayerCardGridProps = {
  profiles: VirtualPlayerProfile[];
  isLoading: boolean;
  isError: boolean;
  isModelOptionsError: boolean;
  isSaving: boolean;
  actionError: string | null;
  deleteCandidateId: string | null;
  onEditProfile: (profile: VirtualPlayerProfile) => void;
  onCopyProfile: (profile: VirtualPlayerProfile) => void;
  onRequestDeleteProfile: (profileId: string) => void;
  onConfirmDeleteProfile: (profileId: string) => void;
  onCancelDeleteProfile: () => void;
};

export function VirtualPlayerCardGrid({
  profiles,
  isLoading,
  isError,
  isModelOptionsError,
  isSaving,
  actionError,
  deleteCandidateId,
  onEditProfile,
  onCopyProfile,
  onRequestDeleteProfile,
  onConfirmDeleteProfile,
  onCancelDeleteProfile,
}: VirtualPlayerCardGridProps) {
  const [search, setSearch] = useState("");
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [selectedModel, setSelectedModel] = useState("");
  const [selectedPersonality, setSelectedPersonality] = useState("");
  const [sortMode, setSortMode] = useState<"recent" | "name">("recent");
  const modelOptions = useMemo(
    () =>
      Array.from(
        new Set(profiles.map((profile) => profile.model).filter(Boolean)),
      )
        .toSorted((left, right) => left.localeCompare(right, "zh-Hans-CN")),
    [profiles],
  );
  const personalityOptions = useMemo(
    () =>
      PERSONALITY_OPTIONS.filter((option) =>
        profiles.some((profile) => profile.personality_id === option.id),
      ),
    [profiles],
  );
  const filteredProfiles = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase();

    return profiles
      .filter((profile) => {
        const text = [
          profile.display_name,
          profile.short_description,
          profile.model,
          profile.personality_id,
          profile.strategy_profile,
          ...profile.tags,
        ]
          .join(" ")
          .toLowerCase();

        return (
          (!favoritesOnly || profile.favorite) &&
          (!selectedModel || profile.model === selectedModel) &&
          (!selectedPersonality ||
            profile.personality_id === selectedPersonality) &&
          (!normalizedSearch || text.includes(normalizedSearch))
        );
      })
      .toSorted((left, right) => {
        if (sortMode === "name") {
          return left.display_name.localeCompare(
            right.display_name,
            "zh-Hans-CN",
          );
        }

        return right.updated_at.localeCompare(left.updated_at);
      });
  }, [
    favoritesOnly,
    profiles,
    search,
    selectedModel,
    selectedPersonality,
    sortMode,
  ]);

  return (
    <>
      {actionError ? (
        <p className="virtual-player-library-error" role="alert">
          {actionError}
        </p>
      ) : null}
      {isLoading ? (
        <p className="virtual-player-library-status">正在读取虚拟玩家...</p>
      ) : null}
      {isError ? (
        <p className="virtual-player-library-error">无法读取虚拟玩家库</p>
      ) : null}
      {isModelOptionsError ? (
        <p className="virtual-player-library-error">无法读取模型列表</p>
      ) : null}
      {!isLoading && !isError && profiles.length === 0 ? (
        <p className="virtual-player-library-empty">还没有保存的虚拟玩家。</p>
      ) : null}
      {profiles.length > 0 ? (
        <div className="virtual-player-card-grid-toolbar">
          <label className="virtual-player-card-search">
            <span>搜索虚拟玩家</span>
            <TextField.Root
              onChange={(event) => setSearch(event.target.value)}
              value={search}
            />
          </label>
          <label className="virtual-player-card-filter">
            <span>模型筛选</span>
            <SelectField
              onChange={(event) => setSelectedModel(event.target.value)}
              value={selectedModel}
            >
              <option value="">全部模型</option>
              {modelOptions.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </SelectField>
          </label>
          <label className="virtual-player-card-filter">
            <span>性格筛选</span>
            <SelectField
              onChange={(event) => setSelectedPersonality(event.target.value)}
              value={selectedPersonality}
            >
              <option value="">全部性格</option>
              {personalityOptions.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </SelectField>
          </label>
          <label className="virtual-player-card-filter">
            <span>排序方式</span>
            <SelectField
              onChange={(event) =>
                setSortMode(event.target.value === "name" ? "name" : "recent")
              }
              value={sortMode}
            >
              <option value="recent">最近更新</option>
              <option value="name">显示名称</option>
            </SelectField>
          </label>
          <Button
            aria-pressed={favoritesOnly}
            className="virtual-player-card-favorite-filter"
            intent={favoritesOnly ? "warning" : "default"}
            onClick={() => setFavoritesOnly((current) => !current)}
            size="1"
            skin="gothic"
            type="button"
          >
            只看收藏
          </Button>
        </div>
      ) : null}
      {profiles.length > 0 && filteredProfiles.length === 0 ? (
        <p className="virtual-player-library-empty">没有符合条件的虚拟玩家。</p>
      ) : null}
      {filteredProfiles.length > 0 ? (
        <ul aria-label="虚拟玩家列表" className="virtual-player-library-grid">
          {filteredProfiles.map((profile) => {
            const isDeleteCandidate = deleteCandidateId === profile.id;
            const tags = profile.tags ?? [];
            const strategy =
              STRATEGY_OPTIONS.find(
                (option) => option.id === profile.strategy_profile,
              ) ?? STRATEGY_OPTIONS[0];

            return (
              <li className="virtual-player-card" key={profile.id}>
                <span
                  className={[
                    "virtual-player-card-avatar",
                    profile.avatar_image_url
                      ? "virtual-player-card-avatar-image"
                      : appearanceClassName(profile.appearance_id),
                  ].join(" ")}
                >
                  {profile.avatar_image_url ? (
                    <img
                      alt={`${profile.display_name} 人物形象`}
                      src={profile.avatar_image_url}
                    />
                  ) : (
                    profile.display_name.trim().charAt(0) || "?"
                  )}
                </span>
                <div className="virtual-player-card-main">
                  <div className="virtual-player-card-heading">
                    <span className="virtual-player-card-name">
                      {profile.display_name}
                    </span>
                    {profile.favorite ? (
                      <span className="virtual-player-card-favorite">收藏</span>
                    ) : null}
                    <span className="virtual-player-card-personality">
                      {personalityLabel(profile.personality_id)}
                    </span>
                  </div>
                  <span className="virtual-player-card-model">
                    {profile.model}
                  </span>
                  <span className="virtual-player-card-strategy">
                    {strategy.label}
                  </span>
                  {profile.short_description ? (
                    <span className="virtual-player-card-description">
                      {profile.short_description}
                    </span>
                  ) : null}
                  {tags.length > 0 ? (
                    <div className="virtual-player-card-tags">
                      {tags.slice(0, 2).map((tag) => (
                        <span className="virtual-player-card-tag" key={tag}>
                          {tag}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
                <div className="virtual-player-card-actions">
                  <Button
                    aria-label={`编辑 ${profile.display_name}`}
                    disabled={isSaving}
                    onClick={() => onEditProfile(profile)}
                    size="1"
                    skin="gothic"
                    type="button"
                  >
                    编辑
                  </Button>
                  <Button
                    aria-label={`复制 ${profile.display_name}`}
                    disabled={isSaving}
                    onClick={() => onCopyProfile(profile)}
                    size="1"
                    skin="gothic"
                    type="button"
                  >
                    复制
                  </Button>
                  {isDeleteCandidate ? (
                    <>
                      <Button
                        aria-label={`确认删除 ${profile.display_name}`}
                        disabled={isSaving}
                        onClick={() => onConfirmDeleteProfile(profile.id)}
                        size="1"
                        skin="gothic"
                        type="button"
                      >
                        确认删除
                      </Button>
                      <Button
                        aria-label={`取消删除 ${profile.display_name}`}
                        disabled={isSaving}
                        onClick={onCancelDeleteProfile}
                        size="1"
                        skin="gothic"
                        type="button"
                      >
                        取消
                      </Button>
                    </>
                  ) : (
                    <Button
                      aria-label={`删除 ${profile.display_name}`}
                      disabled={isSaving}
                      onClick={() => onRequestDeleteProfile(profile.id)}
                      size="1"
                      skin="gothic"
                      type="button"
                    >
                      删除
                    </Button>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      ) : null}
    </>
  );
}
