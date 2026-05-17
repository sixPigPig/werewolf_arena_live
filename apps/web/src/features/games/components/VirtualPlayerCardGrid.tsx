import { Button } from "../../../components/ui";
import {
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
        <ul aria-label="虚拟玩家列表" className="virtual-player-library-grid">
          {profiles.map((profile) => {
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
