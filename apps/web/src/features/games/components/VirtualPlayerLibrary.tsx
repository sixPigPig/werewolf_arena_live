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
import type { PlayerProfileRequest, VirtualPlayerProfile } from "../types";

type VirtualPlayerLibraryProps = {
  profiles: VirtualPlayerProfile[];
  isLoading: boolean;
  isError: boolean;
  isSaving: boolean;
  onCreateProfile: (request: PlayerProfileRequest) => Promise<unknown>;
  onUpdateProfile: (
    profileId: string,
    request: PlayerProfileRequest,
  ) => Promise<unknown>;
  onDeleteProfile: (profileId: string) => Promise<unknown>;
};

const defaultDraft = (): PlayerProfileRequest => ({
  display_name: "",
  model: "",
  personality_id: "balanced",
  personality_text: "",
  appearance_id: "default",
  avatar_prompt: "",
  tags: [],
});

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

export function VirtualPlayerLibrary({
  profiles,
  isLoading,
  isError,
  isSaving,
  onCreateProfile,
  onUpdateProfile,
  onDeleteProfile,
}: VirtualPlayerLibraryProps) {
  const [draft, setDraft] = useState<PlayerProfileRequest>(defaultDraft);
  const [editingProfileId, setEditingProfileId] = useState<string | null>(null);
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [deleteCandidateId, setDeleteCandidateId] = useState<string | null>(
    null,
  );
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
    setDraft(defaultDraft());
    setEditingProfileId(null);
    setIsEditorOpen(true);
  };

  const startEdit = (profile: VirtualPlayerProfile) => {
    setActionError(null);
    setDeleteCandidateId(null);
    setDraft(profileToDraft(profile));
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
            <TextField.Root
              disabled={isSaving}
              onChange={(event) => updateDraft("model", event.target.value)}
              value={draft.model}
            />
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
