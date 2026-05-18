import {
  type ChangeEvent,
  type DragEvent,
  forwardRef,
  type FormEvent,
} from "react";

import {
  Button,
  Option,
  SelectField,
  TextField,
} from "../../../components/ui";
import type {
  PlayerCreationPreset,
  PlayerCreationPresetId,
  PlayerProfileCreationReadiness,
} from "../playerProfileCreation";
import { PERSONALITY_OPTIONS } from "../playerProfileOptions";
import {
  STRATEGY_OPTIONS,
  TENDENCY_LABELS,
  type TendencyField,
} from "../playerStrategyOptions";
import {
  SYSTEM_PLAYER_AVATARS,
  type SystemPlayerAvatar,
} from "../systemPlayerAvatars";
import type { ModelOption, PlayerProfileRequest } from "../types";
import { VirtualPlayerPreview } from "./VirtualPlayerPreview";

type VirtualPlayerEditorProps = {
  draft: PlayerProfileRequest;
  modelOptions: ModelOption[];
  creationPresets: PlayerCreationPreset[];
  selectedCreationPresetId: PlayerCreationPresetId;
  creationReadiness: PlayerProfileCreationReadiness;
  tagInput: string;
  catchphraseInput: string;
  exampleMessageInput: string;
  isSaving: boolean;
  isGeneratingAiDraft: boolean;
  isGeneratingAiName: boolean;
  isUploadingAvatar: boolean;
  isAvatarDragging: boolean;
  isEditing: boolean;
  isTemplateDialogOpen: boolean;
  canSave: boolean;
  templateNameInput: string;
  templateSaveError: string | null;
  onDraftChange: <Key extends keyof PlayerProfileRequest>(
    key: Key,
    value: PlayerProfileRequest[Key],
  ) => void;
  onCreationPresetChange: (presetId: PlayerCreationPresetId) => void;
  onTagInputChange: (value: string) => void;
  onCatchphraseInputChange: (value: string) => void;
  onExampleMessageInputChange: (value: string) => void;
  onGenerateAiName: () => void;
  onApplySystemAvatar: (avatar: SystemPlayerAvatar) => void;
  onAvatarFileChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onAvatarDragLeave: () => void;
  onAvatarDragOver: (event: DragEvent<HTMLLabelElement>) => void;
  onAvatarDrop: (event: DragEvent<HTMLLabelElement>) => void;
  onCancel: () => void;
  onOpenSaveTemplate: () => void;
  onCancelSaveTemplate: () => void;
  onConfirmSaveTemplate: () => void;
  onSave: () => void;
  onSaveAndContinue: () => void;
  onTemplateNameInputChange: (value: string) => void;
};

export const VirtualPlayerEditor = forwardRef<
  HTMLFormElement,
  VirtualPlayerEditorProps
>(function VirtualPlayerEditor(
  {
    draft,
    modelOptions,
    creationPresets,
    selectedCreationPresetId,
    creationReadiness,
    tagInput,
    catchphraseInput,
    exampleMessageInput,
    isSaving,
    isGeneratingAiDraft,
    isGeneratingAiName,
    isUploadingAvatar,
    isAvatarDragging,
    isEditing,
    isTemplateDialogOpen,
    canSave,
    templateNameInput,
    templateSaveError,
    onDraftChange,
    onCreationPresetChange,
    onTagInputChange,
    onCatchphraseInputChange,
    onExampleMessageInputChange,
    onGenerateAiName,
    onApplySystemAvatar,
    onAvatarFileChange,
    onAvatarDragLeave,
    onAvatarDragOver,
    onAvatarDrop,
    onCancel,
    onOpenSaveTemplate,
    onCancelSaveTemplate,
    onConfirmSaveTemplate,
    onSave,
    onSaveAndContinue,
    onTemplateNameInputChange,
  },
  ref,
) {
  const modelLabel =
    modelOptions.find((option) => option.id === draft.model)?.label ??
    draft.model;

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    onSave();
  };

  return (
    <form
      className="virtual-player-editor"
      noValidate
      ref={ref}
      onSubmit={handleSubmit}
    >
      <div className="virtual-player-editor-main">
        <section
          aria-labelledby="virtual-player-creation-section"
          className="virtual-player-editor-section virtual-player-creation-section"
        >
          <h3
            className="virtual-player-editor-section-title"
            id="virtual-player-creation-section"
          >
            创作模板
          </h3>
          <div className="virtual-player-preset-grid">
            {creationPresets.map((preset) => (
              <button
                aria-pressed={selectedCreationPresetId === preset.id}
                className="virtual-player-preset-option"
                data-ai={preset.isAiGenerated ? "true" : undefined}
                data-custom={preset.isCustom ? "true" : undefined}
                disabled={isSaving || isGeneratingAiDraft}
                key={preset.id}
                onClick={() => onCreationPresetChange(preset.id)}
                type="button"
              >
                <span className="virtual-player-preset-name">
                  {preset.isAiGenerated && isGeneratingAiDraft
                    ? "AI 生成中"
                    : preset.label}
                </span>
                <span className="virtual-player-preset-description">
                  {preset.description}
                </span>
              </button>
            ))}
          </div>
          <div aria-label="创建状态" className="virtual-player-readiness">
            {creationReadiness.items.map((item) => (
              <span
                className="virtual-player-readiness-chip"
                data-complete={item.isComplete ? "true" : "false"}
                key={item.id}
              >
                {item.label}
              </span>
            ))}
          </div>
          {creationReadiness.issueText ? (
            <p className="virtual-player-readiness-alert" role="alert">
              {creationReadiness.issueText}
            </p>
          ) : null}
        </section>

        <section
          aria-labelledby="virtual-player-basic-section"
          className="virtual-player-editor-section"
        >
          <h3
            className="virtual-player-editor-section-title"
            id="virtual-player-basic-section"
          >
            基础
          </h3>
          <div className="virtual-player-name-control">
            <label>
              <span>虚拟玩家昵称</span>
              <TextField.Root
                aria-invalid={
                  creationReadiness.items.find((item) => item.id === "name")
                    ?.isComplete === false
                    ? true
                    : undefined
                }
                disabled={isSaving || isGeneratingAiName}
                onChange={(event) =>
                  onDraftChange("display_name", event.target.value)
                }
                value={draft.display_name}
              />
            </label>
            <Button
              className="virtual-player-ai-name-button"
              disabled={isSaving || isGeneratingAiName || isGeneratingAiDraft}
              intent="info"
              onClick={onGenerateAiName}
              size="1"
              skin="gothic"
              type="button"
            >
              {isGeneratingAiName ? "生成中" : "AI 生成昵称"}
            </Button>
          </div>
          <label>
            <span>一句话简介</span>
            <TextField.Root
              disabled={isSaving}
              maxLength={160}
              onChange={(event) =>
                onDraftChange("short_description", event.target.value)
              }
              value={draft.short_description ?? ""}
            />
          </label>
          <label>
            <span>默认模型</span>
            <SelectField
              aria-invalid={
                creationReadiness.items.find((item) => item.id === "model")
                  ?.isComplete === false
                  ? true
                  : undefined
              }
              disabled={isSaving}
              onChange={(event) => onDraftChange("model", event.target.value)}
              value={draft.model}
            >
              {modelOptions.length === 0 ? (
                <Option value="">暂无可用模型</Option>
              ) : null}
              {modelOptions.map((option) => (
                <Option key={option.id} value={option.id}>
                  {option.label}
                </Option>
              ))}
            </SelectField>
          </label>
          <label>
            <span>性格</span>
            <SelectField
              disabled={isSaving}
              onChange={(event) =>
                onDraftChange("personality_id", event.target.value)
              }
              value={draft.personality_id}
            >
              {PERSONALITY_OPTIONS.map((option) => (
                <Option key={option.id} value={option.id}>
                  {option.label}
                </Option>
              ))}
            </SelectField>
          </label>
          <label>
            <span>策略模板</span>
            <SelectField
              disabled={isSaving}
              onChange={(event) =>
                onDraftChange("strategy_profile", event.target.value)
              }
              value={draft.strategy_profile}
            >
              {STRATEGY_OPTIONS.map((option) => (
                <Option key={option.id} value={option.id}>
                  {option.label}
                </Option>
              ))}
            </SelectField>
          </label>
          <label className="virtual-player-toggle">
            <input
              checked={Boolean(draft.favorite)}
              disabled={isSaving}
              onChange={(event) =>
                onDraftChange("favorite", event.target.checked)
              }
              type="checkbox"
            />
            <span>收藏</span>
          </label>
        </section>

        <section
          aria-labelledby="virtual-player-avatar-section"
          className="virtual-player-editor-section virtual-player-editor-media"
        >
          <h3
            className="virtual-player-editor-section-title"
            id="virtual-player-avatar-section"
          >
            形象
          </h3>
          <label
            className={[
              "virtual-player-avatar-uploader",
              isAvatarDragging ? "virtual-player-avatar-uploader-dragging" : "",
            ].join(" ")}
            data-testid="virtual-player-avatar-dropzone"
            onDragLeave={onAvatarDragLeave}
            onDragOver={onAvatarDragOver}
            onDrop={onAvatarDrop}
          >
            <span>人物形象</span>
            <input
              accept="image/png,image/jpeg,image/webp"
              aria-label="人物形象"
              disabled={isSaving || isUploadingAvatar}
              onChange={onAvatarFileChange}
              type="file"
            />
            <div className="virtual-player-avatar-preview">
              {draft.avatar_image_url ? (
                <img
                  alt={`${draft.display_name || "虚拟玩家"} 人物形象`}
                  src={draft.avatar_image_url}
                />
              ) : (
                <span
                  aria-hidden="true"
                  className="virtual-player-avatar-placeholder"
                >
                  {draft.display_name.trim().charAt(0) || "?"}
                </span>
              )}
            </div>
          </label>
          <div className="virtual-player-system-avatars">
            {SYSTEM_PLAYER_AVATARS.map((avatar) => {
              const isSelected = draft.avatar_image_url === avatar.imageUrl;

              return (
                <button
                  aria-label={`选择内设形象 ${avatar.label}`}
                  className={[
                    "virtual-player-system-avatar",
                    isSelected ? "virtual-player-system-avatar-selected" : "",
                  ].join(" ")}
                  key={avatar.id}
                  onClick={() => onApplySystemAvatar(avatar)}
                  type="button"
                >
                  <img alt="" aria-hidden="true" src={avatar.imageUrl} />
                  <span>{avatar.label}</span>
                </button>
              );
            })}
          </div>
        </section>

        <section
          aria-labelledby="virtual-player-voice-section"
          className="virtual-player-editor-section"
        >
          <h3
            className="virtual-player-editor-section-title"
            id="virtual-player-voice-section"
          >
            设定
          </h3>
          <label className="virtual-player-field-wide">
            <span>性格描述</span>
            <textarea
              disabled={isSaving}
              onChange={(event) =>
                onDraftChange("personality_text", event.target.value)
              }
              value={draft.personality_text ?? ""}
            />
          </label>
          <label>
            <span>背景故事</span>
            <textarea
              disabled={isSaving}
              onChange={(event) =>
                onDraftChange("background_story", event.target.value)
              }
              value={draft.background_story ?? ""}
            />
          </label>
          <label>
            <span>发言风格</span>
            <textarea
              disabled={isSaving}
              onChange={(event) =>
                onDraftChange("speaking_style", event.target.value)
              }
              value={draft.speaking_style ?? ""}
            />
          </label>
          <label>
            <span>常用表达</span>
            <TextField.Root
              disabled={isSaving}
              onChange={(event) => onCatchphraseInputChange(event.target.value)}
              value={catchphraseInput}
            />
          </label>
          <label>
            <span>标签</span>
            <TextField.Root
              disabled={isSaving}
              onChange={(event) => onTagInputChange(event.target.value)}
              value={tagInput}
            />
          </label>
          <label className="virtual-player-field-wide">
            <span>示例发言</span>
            <textarea
              disabled={isSaving}
              onChange={(event) =>
                onExampleMessageInputChange(event.target.value)
              }
              value={exampleMessageInput}
            />
          </label>
        </section>

        <section
          aria-labelledby="virtual-player-tendency-section"
          className="virtual-player-editor-section virtual-player-tendency-section"
        >
          <h3
            className="virtual-player-editor-section-title"
            id="virtual-player-tendency-section"
          >
            倾向
          </h3>
          <div className="virtual-player-tendency-grid">
            {(
              Object.entries(TENDENCY_LABELS) as Array<[TendencyField, string]>
            ).map(([fieldName, label]) => (
              <label className="virtual-player-tendency-field" key={fieldName}>
                <span>{label}</span>
                <input
                  disabled={isSaving}
                  inputMode="numeric"
                  max={5}
                  min={1}
                  onChange={(event) =>
                    onDraftChange(
                      fieldName,
                      event.target.value === ""
                        ? Number.NaN
                        : Number(event.target.value),
                    )
                  }
                  step={1}
                  type="number"
                  value={
                    Number.isFinite(draft[fieldName])
                      ? String(draft[fieldName])
                      : ""
                  }
                />
              </label>
            ))}
          </div>
        </section>

        <div className="virtual-player-editor-actions">
          <Button
            className="virtual-player-editor-save"
            disabled={!canSave}
            intent="primary"
            size="1"
            skin="gothic"
            type="submit"
          >
            保存虚拟玩家
          </Button>
          <Button
            className="virtual-player-editor-save-template"
            disabled={isSaving || isGeneratingAiDraft}
            intent="info"
            onClick={onOpenSaveTemplate}
            size="1"
            skin="gothic"
            type="button"
          >
            保存为模板
          </Button>
          {!isEditing ? (
            <Button
              className="virtual-player-editor-save-more"
              disabled={!canSave}
              intent="warning"
              onClick={onSaveAndContinue}
              size="1"
              skin="gothic"
              type="button"
            >
              保存并继续新建
            </Button>
          ) : null}
          <Button
            disabled={isSaving}
            onClick={onCancel}
            size="1"
            skin="gothic"
            type="button"
          >
            取消
          </Button>
        </div>
        {isTemplateDialogOpen ? (
          <div
            aria-labelledby="virtual-player-template-dialog-title"
            aria-modal="true"
            className="virtual-player-template-dialog"
            role="dialog"
          >
            <div className="virtual-player-template-dialog-panel">
              <h3
                className="virtual-player-template-dialog-title"
                id="virtual-player-template-dialog-title"
              >
                保存为模板
              </h3>
              <label>
                <span>模板名</span>
                <TextField.Root
                  autoFocus
                  onChange={(event) =>
                    onTemplateNameInputChange(event.target.value)
                  }
                  value={templateNameInput}
                />
              </label>
              {templateSaveError ? (
                <p className="virtual-player-template-dialog-error" role="alert">
                  {templateSaveError}
                </p>
              ) : null}
              <div className="virtual-player-template-dialog-actions">
                <Button
                  intent="primary"
                  onClick={onConfirmSaveTemplate}
                  size="1"
                  skin="gothic"
                  type="button"
                >
                  保存模板
                </Button>
                <Button
                  onClick={onCancelSaveTemplate}
                  size="1"
                  skin="gothic"
                  type="button"
                >
                  取消
                </Button>
              </div>
            </div>
          </div>
        ) : null}
      </div>
      <VirtualPlayerPreview draft={draft} modelLabel={modelLabel} />
    </form>
  );
});
