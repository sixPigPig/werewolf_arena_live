import { useState } from "react";

import {
  Button,
  Container,
  Option,
  SelectField,
  TextField,
} from "../../../components/ui";
import {
  APPEARANCE_OPTIONS,
  appearanceClassName,
  PERSONALITY_OPTIONS,
  personalityLabel,
} from "../playerProfileOptions";
import type {
  ModelOption,
  PlayerProfileRequest,
  VirtualPlayerProfile,
} from "../types";

type VirtualPlayerLibraryProps = {
  profiles: VirtualPlayerProfile[];
  modelOptions: ModelOption[];
  isLoading: boolean;
  isError: boolean;
  isModelOptionsError: boolean;
  isSaving: boolean;
  onCreateProfile: (request: PlayerProfileRequest) => Promise<unknown>;
  onUpdateProfile: (
    profileId: string,
    request: PlayerProfileRequest,
  ) => Promise<unknown>;
  onDeleteProfile: (profileId: string) => Promise<unknown>;
};

const NAME_PREFIXES = ["冷月", "沉默", "银刃", "夜行", "雾隐", "烛影"];
const NAME_SUFFIXES = ["阿夜", "林川", "青棠", "北辰", "司南", "月白"];

const defaultDraft = (model = ""): PlayerProfileRequest => ({
  display_name: "",
  model,
  personality_id: "balanced",
  personality_text: "",
  appearance_id: "default",
  avatar_prompt: "",
  tags: [],
});

function generateVirtualPlayerName() {
  const prefix = NAME_PREFIXES[Math.floor(Math.random() * NAME_PREFIXES.length)];
  const suffix = NAME_SUFFIXES[Math.floor(Math.random() * NAME_SUFFIXES.length)];
  return `${prefix}${suffix}`;
}

function profileToDraft(profile: VirtualPlayerProfile): PlayerProfileRequest {
  return {
    display_name: profile.display_name,
    model: profile.model,
    personality_id: profile.personality_id || "balanced",
    personality_text: profile.personality_text || "",
    appearance_id: profile.appearance_id || "default",
    avatar_prompt: profile.avatar_prompt || "",
    tags: profile.tags,
  };
}

function parseTagInput(value: string) {
  return value
    .split(/[,\uFF0C\s]+/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function formatTagInput(tags: string[] | undefined) {
  return (tags ?? []).join("，");
}

function modelOptionsForDraft(
  options: ModelOption[],
  draftModel: string | undefined,
) {
  if (!draftModel || options.some((option) => option.id === draftModel)) {
    return options;
  }

  return [{ id: draftModel, label: `当前模型 · ${draftModel}` }, ...options];
}

export function VirtualPlayerLibrary({
  profiles,
  modelOptions,
  isLoading,
  isError,
  isModelOptionsError,
  isSaving,
  onCreateProfile,
  onUpdateProfile,
  onDeleteProfile,
}: VirtualPlayerLibraryProps) {
  const [draft, setDraft] = useState<PlayerProfileRequest>(defaultDraft);
  const [tagInput, setTagInput] = useState("");
  const [editingProfileId, setEditingProfileId] = useState<string | null>(null);
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [deleteCandidateId, setDeleteCandidateId] = useState<string | null>(
    null,
  );
  const activeModelOptions = modelOptionsForDraft(modelOptions, draft.model);
  const canSave =
    !isSaving &&
    draft.display_name.trim().length > 0 &&
    draft.model.trim().length > 0;

  const updateDraft = <Key extends keyof PlayerProfileRequest>(
    key: Key,
    value: PlayerProfileRequest[Key],
  ) => setDraft((current) => ({ ...current, [key]: value }));

  const startCreate = () => {
    setActionError(null);
    setDeleteCandidateId(null);
    setDraft({
      ...defaultDraft(modelOptions[0]?.id ?? ""),
      display_name: generateVirtualPlayerName(),
    });
    setTagInput("");
    setEditingProfileId(null);
    setIsEditorOpen(true);
  };

  const startEdit = (profile: VirtualPlayerProfile) => {
    setActionError(null);
    setDeleteCandidateId(null);
    setDraft(profileToDraft(profile));
    setTagInput(formatTagInput(profile.tags));
    setEditingProfileId(profile.id);
    setIsEditorOpen(true);
  };

  const saveDraft = async () => {
    if (!canSave) {
      return;
    }
    setActionError(null);
    const request: PlayerProfileRequest = {
      ...draft,
      display_name: draft.display_name.trim(),
      model: draft.model.trim(),
      personality_text: draft.personality_text?.trim() ?? "",
      avatar_prompt: draft.avatar_prompt?.trim() ?? "",
      tags: draft.tags ?? [],
    };
    try {
      if (editingProfileId) {
        await onUpdateProfile(editingProfileId, request);
      } else {
        await onCreateProfile(request);
      }
      setIsEditorOpen(false);
      setEditingProfileId(null);
      setDraft(defaultDraft());
      setTagInput("");
    } catch {
      setActionError("无法保存虚拟玩家");
    }
  };

  const copyProfile = (profile: VirtualPlayerProfile) => {
    setActionError(null);
    void onCreateProfile({
      display_name: `${profile.display_name} 副本`,
      model: profile.model,
      personality_id: profile.personality_id,
      personality_text: profile.personality_text,
      appearance_id: profile.appearance_id,
      avatar_prompt: profile.avatar_prompt,
      tags: profile.tags,
    }).catch(() => setActionError("无法保存虚拟玩家"));
  };

  const requestDeleteProfile = (profileId: string) => {
    setActionError(null);
    setDeleteCandidateId(profileId);
  };

  const confirmDeleteProfile = async (profileId: string) => {
    setActionError(null);
    try {
      await onDeleteProfile(profileId);
      setDeleteCandidateId(null);
    } catch {
      setActionError("无法删除虚拟玩家");
    }
  };

  const cancelDeleteProfile = () => {
    setActionError(null);
    setDeleteCandidateId(null);
  };

  return (
    <Container
      aria-labelledby="virtual-player-library-title"
      as="section"
      className="virtual-player-library"
      contentClassName="virtual-player-library-content"
      data-testid="virtual-player-library"
      size="1"
    >
      <div className="virtual-player-library-header">
        <h2
          className="virtual-player-library-title"
          id="virtual-player-library-title"
        >
          虚拟玩家库
        </h2>
        <Button
          className="virtual-player-library-action"
          intent="primary"
          onClick={startCreate}
          size="1"
          skin="gothic"
          type="button"
        >
          新建虚拟玩家
        </Button>
      </div>

      {isEditorOpen ? (
        <form
          className="virtual-player-editor"
          onSubmit={(event) => {
            event.preventDefault();
            void saveDraft();
          }}
        >
          <label>
            <span>虚拟玩家昵称</span>
            <TextField.Root
              disabled={isSaving}
              onChange={(event) =>
                updateDraft("display_name", event.target.value)
              }
              value={draft.display_name}
            />
          </label>
          <label>
            <span>默认模型</span>
            <SelectField
              disabled={isSaving}
              onChange={(event) => updateDraft("model", event.target.value)}
              value={draft.model}
            >
              {activeModelOptions.length === 0 ? (
                <Option value="">暂无可用模型</Option>
              ) : null}
              {activeModelOptions.map((option) => (
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
                updateDraft("personality_id", event.target.value)
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
            <span>人物形象</span>
            <SelectField
              disabled={isSaving}
              onChange={(event) =>
                updateDraft("appearance_id", event.target.value)
              }
              value={draft.appearance_id}
            >
              {APPEARANCE_OPTIONS.map((option) => (
                <Option key={option.id} value={option.id}>
                  {option.label}
                </Option>
              ))}
            </SelectField>
          </label>
          <label>
            <span>性格描述</span>
            <textarea
              disabled={isSaving}
              onChange={(event) =>
                updateDraft("personality_text", event.target.value)
              }
              value={draft.personality_text ?? ""}
            />
          </label>
          <label>
            <span>形象提示</span>
            <textarea
              disabled={isSaving}
              onChange={(event) =>
                updateDraft("avatar_prompt", event.target.value)
              }
              value={draft.avatar_prompt ?? ""}
            />
          </label>
          <label>
            <span>标签</span>
            <TextField.Root
              disabled={isSaving}
              onChange={(event) => {
                setTagInput(event.target.value);
                updateDraft("tags", parseTagInput(event.target.value));
              }}
              value={tagInput}
            />
          </label>
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
        </form>
      ) : null}

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
        <ul
          aria-label="虚拟玩家列表"
          className="virtual-player-library-grid"
        >
          {profiles.map((profile) => {
            const isDeleteCandidate = deleteCandidateId === profile.id;
            return (
              <li className="virtual-player-card" key={profile.id}>
                <span
                  aria-hidden="true"
                  className={[
                    "virtual-player-card-avatar",
                    appearanceClassName(profile.appearance_id),
                  ].join(" ")}
                >
                  {profile.display_name.trim().charAt(0) || "?"}
                </span>
                <div className="virtual-player-card-main">
                  <div className="virtual-player-card-heading">
                    <span className="virtual-player-card-name">
                      {profile.display_name}
                    </span>
                    <span className="virtual-player-card-personality">
                      {personalityLabel(profile.personality_id)}
                    </span>
                  </div>
                  <span className="virtual-player-card-model">
                    {profile.model}
                  </span>
                  {profile.tags.length > 0 ? (
                    <div className="virtual-player-card-tags">
                      {profile.tags.slice(0, 2).map((tag) => (
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
                    onClick={() => startEdit(profile)}
                    size="1"
                    skin="gothic"
                    type="button"
                  >
                    编辑
                  </Button>
                  <Button
                    aria-label={`复制 ${profile.display_name}`}
                    disabled={isSaving}
                    onClick={() => copyProfile(profile)}
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
                        onClick={() => void confirmDeleteProfile(profile.id)}
                        size="1"
                        skin="gothic"
                        type="button"
                      >
                        确认删除
                      </Button>
                      <Button
                        aria-label={`取消删除 ${profile.display_name}`}
                        disabled={isSaving}
                        onClick={cancelDeleteProfile}
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
                      onClick={() => requestDeleteProfile(profile.id)}
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
    </Container>
  );
}
