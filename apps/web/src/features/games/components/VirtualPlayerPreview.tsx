import {
  STRATEGY_OPTIONS,
  TENDENCY_LABELS,
  type TendencyField,
} from "../playerStrategyOptions";
import {
  composeProfilePromptPreview,
  normalizeTendency,
} from "../profilePromptPreview";
import { resolveAvatarImageUrl, type PlayerProfileRequest } from "../types";

type VirtualPlayerPreviewProps = {
  draft: PlayerProfileRequest;
  modelLabel?: string;
};

export function VirtualPlayerPreview({
  draft,
  modelLabel,
}: VirtualPlayerPreviewProps) {
  const displayName = draft.display_name.trim() || "未命名玩家";
  const strategy =
    STRATEGY_OPTIONS.find((option) => option.id === draft.strategy_profile) ??
    STRATEGY_OPTIONS[0];
  const promptPreview = composeProfilePromptPreview(draft);
  const avatarImageUrl = resolveAvatarImageUrl(draft);

  return (
    <aside aria-label="虚拟玩家预览" className="virtual-player-preview">
      <div className="virtual-player-preview-topline">
        <div className="virtual-player-preview-portrait">
          {avatarImageUrl ? (
            <img
              alt=""
              aria-hidden="true"
              src={avatarImageUrl}
            />
          ) : (
            <span aria-hidden="true">{displayName.charAt(0) || "?"}</span>
          )}
        </div>
        <div className="virtual-player-preview-meta">
          <span className="virtual-player-preview-name">{displayName}</span>
          <span className="virtual-player-preview-model">
            {modelLabel || draft.model || "未选择模型"}
          </span>
          <span className="virtual-player-preview-strategy">
            {strategy.label}
          </span>
        </div>
        {draft.favorite ? (
          <span className="virtual-player-preview-favorite">收藏</span>
        ) : null}
      </div>
      <p className="virtual-player-preview-description">
        {draft.short_description?.trim() || strategy.description}
      </p>
      <div className="virtual-player-preview-stats">
        {(Object.entries(TENDENCY_LABELS) as Array<[TendencyField, string]>).map(
          ([fieldName, label]) => {
            const value = normalizeTendency(draft[fieldName]);

            return (
              <div className="virtual-player-preview-stat" key={fieldName}>
                <span>{label}</span>
                <div
                  aria-label={`${label} ${value}/5`}
                  className="virtual-player-preview-stat-track"
                  role="meter"
                  aria-valuemax={5}
                  aria-valuemin={1}
                  aria-valuenow={value}
                >
                  <span style={{ width: `${value * 20}%` }} />
                </div>
              </div>
            );
          },
        )}
      </div>
      <div className="virtual-player-prompt-panel">
        <span className="virtual-player-preview-subtitle">提示词预览</span>
        <pre className="virtual-player-prompt-preview">
          {promptPreview || "暂无可预览提示词"}
        </pre>
      </div>
    </aside>
  );
}
