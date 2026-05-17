import {
  type ChangeEvent,
  type DragEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { Button, Container } from "../../../components/ui";
import {
  randomSystemPlayerAvatar,
  type SystemPlayerAvatar,
} from "../systemPlayerAvatars";
import type {
  ModelOption,
  PlayerAvatarUploadResponse,
  PlayerProfileRequest,
  VirtualPlayerProfile,
} from "../types";
import { DEFAULT_PLAYER_PROFILE_DRAFT } from "../types";
import { VirtualPlayerCardGrid } from "./VirtualPlayerCardGrid";
import { VirtualPlayerEditor } from "./VirtualPlayerEditor";

type VirtualPlayerLibraryProps = {
  profiles: VirtualPlayerProfile[];
  modelOptions: ModelOption[];
  isLoading: boolean;
  isError: boolean;
  isModelOptionsError: boolean;
  isSaving: boolean;
  onUploadAvatar: (file: File) => Promise<PlayerAvatarUploadResponse>;
  onCreateProfile: (request: PlayerProfileRequest) => Promise<unknown>;
  onCreateActionReady?: (openCreate: () => void) => void;
  onUpdateProfile: (
    profileId: string,
    request: PlayerProfileRequest,
  ) => Promise<unknown>;
  onDeleteProfile: (profileId: string) => Promise<unknown>;
};

const NAME_PREFIXES = ["冷月", "沉默", "银刃", "夜行", "雾隐", "烛影"];
const NAME_SUFFIXES = ["阿夜", "林川", "青棠", "北辰", "司南", "月白"];

function defaultDraft(model = ""): PlayerProfileRequest {
  return {
    ...DEFAULT_PLAYER_PROFILE_DRAFT,
    model,
    tags: [...(DEFAULT_PLAYER_PROFILE_DRAFT.tags ?? [])],
    catchphrases: [...(DEFAULT_PLAYER_PROFILE_DRAFT.catchphrases ?? [])],
    example_messages: [
      ...(DEFAULT_PLAYER_PROFILE_DRAFT.example_messages ?? []),
    ],
  };
}

function generateVirtualPlayerName() {
  const prefix = NAME_PREFIXES[Math.floor(Math.random() * NAME_PREFIXES.length)];
  const suffix = NAME_SUFFIXES[Math.floor(Math.random() * NAME_SUFFIXES.length)];
  return `${prefix}${suffix}`;
}

function profileToDraft(profile: VirtualPlayerProfile): PlayerProfileRequest {
  return {
    ...defaultDraft(profile.model),
    display_name: profile.display_name,
    personality_id: profile.personality_id || "balanced",
    personality_text: profile.personality_text || "",
    short_description: profile.short_description || "",
    background_story: profile.background_story || "",
    speaking_style: profile.speaking_style || "",
    catchphrases: profile.catchphrases ?? [],
    strategy_profile: profile.strategy_profile || "balanced",
    risk_tolerance: profile.risk_tolerance ?? 3,
    bluffing_tendency: profile.bluffing_tendency ?? 3,
    trust_tendency: profile.trust_tendency ?? 3,
    leadership_tendency: profile.leadership_tendency ?? 3,
    talkativeness: profile.talkativeness ?? 3,
    example_messages: profile.example_messages ?? [],
    favorite: profile.favorite ?? false,
    appearance_id: profile.appearance_id || "default",
    avatar_prompt: profile.avatar_prompt || "",
    avatar_image_url: profile.avatar_image_url || "",
    avatar_image_mime: profile.avatar_image_mime || "",
    tags: profile.tags ?? [],
  };
}

function parseTagInput(value: string) {
  return value
    .split(/[,\uFF0C\s]+/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function parseListInput(value: string) {
  return value
    .split(/[,\uFF0C;\uFF1B\n]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseMultilineInput(value: string) {
  return value
    .split(/\n+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatTagInput(tags: string[] | undefined) {
  return (tags ?? []).join("，");
}

function formatListInput(items: string[] | undefined) {
  return (items ?? []).join("，");
}

function formatMultilineInput(items: string[] | undefined) {
  return (items ?? []).join("\n");
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

function cleanList(items: string[] | undefined) {
  return (items ?? []).map((item) => item.trim()).filter(Boolean);
}

function cleanTendency(value: unknown) {
  const parsed = Number(value);

  if (!Number.isFinite(parsed)) {
    return 3;
  }

  return Math.min(5, Math.max(1, Math.round(parsed)));
}

export function VirtualPlayerLibrary({
  profiles,
  modelOptions,
  isLoading,
  isError,
  isModelOptionsError,
  isSaving,
  onUploadAvatar,
  onCreateProfile,
  onCreateActionReady,
  onUpdateProfile,
  onDeleteProfile,
}: VirtualPlayerLibraryProps) {
  const [draft, setDraft] = useState<PlayerProfileRequest>(() =>
    defaultDraft(),
  );
  const [tagInput, setTagInput] = useState("");
  const [catchphraseInput, setCatchphraseInput] = useState("");
  const [exampleMessageInput, setExampleMessageInput] = useState("");
  const [editingProfileId, setEditingProfileId] = useState<string | null>(null);
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [focusEditorRequest, setFocusEditorRequest] = useState(0);
  const [isUploadingAvatar, setIsUploadingAvatar] = useState(false);
  const [isAvatarDragging, setIsAvatarDragging] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [deleteCandidateId, setDeleteCandidateId] = useState<string | null>(
    null,
  );
  const editorRef = useRef<HTMLFormElement>(null);
  const shouldFocusEditorRef = useRef(false);
  const activeModelOptions = modelOptionsForDraft(modelOptions, draft.model);
  const canSave =
    !isSaving &&
    !isUploadingAvatar &&
    draft.display_name.trim().length > 0 &&
    draft.model.trim().length > 0;

  const updateDraft = <Key extends keyof PlayerProfileRequest>(
    key: Key,
    value: PlayerProfileRequest[Key],
  ) => setDraft((current) => ({ ...current, [key]: value }));

  const applySystemAvatar = (avatar: SystemPlayerAvatar) => {
    setDraft((current) => ({
      ...current,
      appearance_id: avatar.id,
      avatar_image_url: avatar.imageUrl,
      avatar_image_mime: avatar.mime,
    }));
  };

  const startCreate = useCallback(() => {
    const avatar = randomSystemPlayerAvatar();
    shouldFocusEditorRef.current = true;
    setActionError(null);
    setDeleteCandidateId(null);
    setDraft({
      ...defaultDraft(modelOptions[0]?.id ?? ""),
      display_name: generateVirtualPlayerName(),
      appearance_id: avatar.id,
      avatar_image_url: avatar.imageUrl,
      avatar_image_mime: avatar.mime,
    });
    setTagInput("");
    setCatchphraseInput("");
    setExampleMessageInput("");
    setEditingProfileId(null);
    setIsEditorOpen(true);
    setFocusEditorRequest((request) => request + 1);
  }, [modelOptions]);

  useEffect(() => {
    if (!onCreateActionReady) {
      return undefined;
    }

    onCreateActionReady(startCreate);
    return () => onCreateActionReady(() => undefined);
  }, [onCreateActionReady, startCreate]);

  useEffect(() => {
    if (!isEditorOpen || !shouldFocusEditorRef.current) {
      return;
    }

    shouldFocusEditorRef.current = false;
    editorRef.current?.scrollIntoView?.({
      behavior: "smooth",
      block: "start",
    });
    editorRef.current
      ?.querySelector<HTMLElement>(
        "input:not([type='file']):not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not([disabled])",
      )
      ?.focus();
  }, [focusEditorRequest, isEditorOpen]);

  const startEdit = (profile: VirtualPlayerProfile) => {
    const nextDraft = profileToDraft(profile);

    setActionError(null);
    setDeleteCandidateId(null);
    setDraft(nextDraft);
    setTagInput(formatTagInput(nextDraft.tags));
    setCatchphraseInput(formatListInput(nextDraft.catchphrases));
    setExampleMessageInput(formatMultilineInput(nextDraft.example_messages));
    setEditingProfileId(profile.id);
    setIsEditorOpen(true);
  };

  const cancelEditor = () => {
    setActionError(null);
    setIsEditorOpen(false);
    setEditingProfileId(null);
    setDraft(defaultDraft());
    setTagInput("");
    setCatchphraseInput("");
    setExampleMessageInput("");
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
      short_description: draft.short_description?.trim() ?? "",
      background_story: draft.background_story?.trim() ?? "",
      speaking_style: draft.speaking_style?.trim() ?? "",
      catchphrases: cleanList(draft.catchphrases),
      strategy_profile: draft.strategy_profile || "balanced",
      risk_tolerance: cleanTendency(draft.risk_tolerance),
      bluffing_tendency: cleanTendency(draft.bluffing_tendency),
      trust_tendency: cleanTendency(draft.trust_tendency),
      leadership_tendency: cleanTendency(draft.leadership_tendency),
      talkativeness: cleanTendency(draft.talkativeness),
      example_messages: cleanList(draft.example_messages),
      favorite: Boolean(draft.favorite),
      avatar_prompt: draft.avatar_prompt?.trim() ?? "",
      avatar_image_url: draft.avatar_image_url?.trim() ?? "",
      avatar_image_mime: draft.avatar_image_mime?.trim() ?? "",
      tags: cleanList(draft.tags),
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
      setCatchphraseInput("");
      setExampleMessageInput("");
    } catch {
      setActionError("无法保存虚拟玩家");
    }
  };

  const copyProfile = (profile: VirtualPlayerProfile) => {
    setActionError(null);
    void onCreateProfile({
      ...profileToDraft(profile),
      display_name: `${profile.display_name} 副本`,
    }).catch(() => setActionError("无法保存虚拟玩家"));
  };

  const uploadAvatarFile = async (file: File) => {
    if (!file) {
      return;
    }

    setActionError(null);
    setIsUploadingAvatar(true);
    try {
      const response = await onUploadAvatar(file);
      setDraft((current) => ({
        ...current,
        avatar_image_url: response.avatar_image_url,
        avatar_image_mime: response.avatar_image_mime,
      }));
    } catch {
      setActionError("无法上传人物形象");
    } finally {
      setIsUploadingAvatar(false);
    }
  };

  const uploadAvatar = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    try {
      if (file) {
        await uploadAvatarFile(file);
      }
    } finally {
      event.target.value = "";
    }
  };

  const handleAvatarDragOver = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
    setIsAvatarDragging(true);
  };

  const handleAvatarDragLeave = () => {
    setIsAvatarDragging(false);
  };

  const handleAvatarDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setIsAvatarDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) {
      void uploadAvatarFile(file);
    }
  };

  const handleTagInputChange = (value: string) => {
    setTagInput(value);
    updateDraft("tags", parseTagInput(value));
  };

  const handleCatchphraseInputChange = (value: string) => {
    setCatchphraseInput(value);
    updateDraft("catchphrases", parseListInput(value));
  };

  const handleExampleMessageInputChange = (value: string) => {
    setExampleMessageInput(value);
    updateDraft("example_messages", parseMultilineInput(value));
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
        <VirtualPlayerEditor
          ref={editorRef}
          canSave={canSave}
          catchphraseInput={catchphraseInput}
          draft={draft}
          exampleMessageInput={exampleMessageInput}
          isAvatarDragging={isAvatarDragging}
          isSaving={isSaving}
          isUploadingAvatar={isUploadingAvatar}
          modelOptions={activeModelOptions}
          tagInput={tagInput}
          onApplySystemAvatar={applySystemAvatar}
          onAvatarDragLeave={handleAvatarDragLeave}
          onAvatarDragOver={handleAvatarDragOver}
          onAvatarDrop={handleAvatarDrop}
          onAvatarFileChange={(event) => void uploadAvatar(event)}
          onCancel={cancelEditor}
          onCatchphraseInputChange={handleCatchphraseInputChange}
          onDraftChange={updateDraft}
          onExampleMessageInputChange={handleExampleMessageInputChange}
          onSave={() => void saveDraft()}
          onTagInputChange={handleTagInputChange}
        />
      ) : null}

      <VirtualPlayerCardGrid
        actionError={actionError}
        deleteCandidateId={deleteCandidateId}
        isError={isError}
        isLoading={isLoading}
        isModelOptionsError={isModelOptionsError}
        isSaving={isSaving}
        profiles={profiles}
        onCancelDeleteProfile={cancelDeleteProfile}
        onConfirmDeleteProfile={(profileId) => void confirmDeleteProfile(profileId)}
        onCopyProfile={copyProfile}
        onEditProfile={startEdit}
        onRequestDeleteProfile={requestDeleteProfile}
      />
    </Container>
  );
}
