import {
  type ChangeEvent,
  type DragEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { Container } from "../../../components/ui";
import {
  AI_PLAYER_CREATION_PRESET,
  AI_PLAYER_CREATION_PRESET_ID,
  applyPlayerCreationPreset,
  createPlayerCreationPresetFromDraft,
  DEFAULT_PLAYER_CREATION_PRESET_ID,
  getPlayerProfileCreationReadiness,
  nextAvailableProfileName,
  PLAYER_CREATION_PRESETS,
  type PlayerCreationPreset,
  type PlayerCreationPresetId,
} from "../playerProfileCreation";
import {
  randomSystemPlayerAvatar,
  systemPlayerAvatarImageUrl,
  type SystemPlayerAvatar,
} from "../systemPlayerAvatars";
import type {
  ModelOption,
  PlayerProfileAiDraftRequest,
  PlayerProfileAiDraftResponse,
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
  onGenerateAiDraft?: (
    request: PlayerProfileAiDraftRequest,
  ) => Promise<PlayerProfileAiDraftResponse>;
  onCreateActionReady?: (openCreate: () => void) => void;
  onUpdateProfile: (
    profileId: string,
    request: PlayerProfileRequest,
  ) => Promise<unknown>;
  onDeleteProfile: (profileId: string) => Promise<unknown>;
};

const NAME_PREFIXES = [
  "夜幕",
  "银月",
  "暗巷",
  "狼影",
  "雾灯",
  "猎火",
  "守夜",
  "预言",
  "票台",
  "警徽",
  "月蚀",
  "暮鸦",
  "孤影",
  "暗牌",
  "冷锋",
  "霜眼",
  "烛火",
  "迷雾",
  "狼啸",
  "星痕",
];
const NAME_SUFFIXES = [
  "听风",
  "藏刀",
  "验心",
  "守灯",
  "追票",
  "破局",
  "观星",
  "潜行",
  "归零",
  "拆阵",
  "低语",
  "定狼",
  "抿牌",
  "盘线",
  "孤证",
  "压场",
  "换票",
  "归票",
  "夜判",
  "明牌",
];
const CUSTOM_CREATION_PRESETS_STORAGE_KEY =
  "werewolf-arena.custom-player-creation-presets.v1";

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

function loadCustomCreationPresets(): PlayerCreationPreset[] {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const rawValue = window.localStorage.getItem(
      CUSTOM_CREATION_PRESETS_STORAGE_KEY,
    );
    if (!rawValue) {
      return [];
    }
    const parsed = JSON.parse(rawValue) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed
      .map((item, index) => restoreCustomCreationPreset(item, index))
      .filter((preset): preset is PlayerCreationPreset => preset !== null);
  } catch {
    return [];
  }
}

function persistCustomCreationPresets(presets: PlayerCreationPreset[]) {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(
    CUSTOM_CREATION_PRESETS_STORAGE_KEY,
    JSON.stringify(presets),
  );
}

function restoreCustomCreationPreset(
  value: unknown,
  index: number,
): PlayerCreationPreset | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const item = value as Partial<PlayerCreationPreset>;
  if (!item.label || typeof item.label !== "string" || !item.draft) {
    return null;
  }

  return createPlayerCreationPresetFromDraft(
    typeof item.id === "string" ? item.id : `custom-restored-${index}`,
    item.label,
    item.draft as PlayerProfileRequest,
  );
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
    avatar_asset_id: profile.avatar_asset_id ?? null,
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

function mergeAiDraftIntoProfileDraft(
  draft: PlayerProfileRequest,
  aiDraft: PlayerProfileAiDraftResponse,
): PlayerProfileRequest {
  return {
    ...draft,
    display_name: aiDraft.display_name?.trim() || draft.display_name,
    personality_id: aiDraft.personality_id || draft.personality_id,
    personality_text: aiDraft.personality_text ?? draft.personality_text,
    short_description: aiDraft.short_description ?? draft.short_description,
    background_story: aiDraft.background_story ?? draft.background_story,
    speaking_style: aiDraft.speaking_style ?? draft.speaking_style,
    catchphrases: Array.isArray(aiDraft.catchphrases)
      ? [...aiDraft.catchphrases]
      : draft.catchphrases,
    strategy_profile: aiDraft.strategy_profile || draft.strategy_profile,
    risk_tolerance: cleanTendency(aiDraft.risk_tolerance ?? draft.risk_tolerance),
    bluffing_tendency: cleanTendency(
      aiDraft.bluffing_tendency ?? draft.bluffing_tendency,
    ),
    trust_tendency: cleanTendency(aiDraft.trust_tendency ?? draft.trust_tendency),
    leadership_tendency: cleanTendency(
      aiDraft.leadership_tendency ?? draft.leadership_tendency,
    ),
    talkativeness: cleanTendency(aiDraft.talkativeness ?? draft.talkativeness),
    example_messages: Array.isArray(aiDraft.example_messages)
      ? [...aiDraft.example_messages]
      : draft.example_messages,
    tags: Array.isArray(aiDraft.tags) ? [...aiDraft.tags] : draft.tags,
  };
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
  onGenerateAiDraft,
  onCreateActionReady,
  onUpdateProfile,
  onDeleteProfile,
}: VirtualPlayerLibraryProps) {
  const [draft, setDraft] = useState<PlayerProfileRequest>(() =>
    defaultDraft(),
  );
  const [selectedCreationPresetId, setSelectedCreationPresetId] =
    useState<PlayerCreationPresetId>(DEFAULT_PLAYER_CREATION_PRESET_ID);
  const [customCreationPresets, setCustomCreationPresets] = useState<
    PlayerCreationPreset[]
  >(() => loadCustomCreationPresets());
  const [tagInput, setTagInput] = useState("");
  const [catchphraseInput, setCatchphraseInput] = useState("");
  const [exampleMessageInput, setExampleMessageInput] = useState("");
  const [editingProfileId, setEditingProfileId] = useState<string | null>(null);
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [focusEditorRequest, setFocusEditorRequest] = useState(0);
  const [isUploadingAvatar, setIsUploadingAvatar] = useState(false);
  const [isAvatarDragging, setIsAvatarDragging] = useState(false);
  const [isGeneratingAiDraft, setIsGeneratingAiDraft] = useState(false);
  const [isGeneratingAiName, setIsGeneratingAiName] = useState(false);
  const [isTemplateDialogOpen, setIsTemplateDialogOpen] = useState(false);
  const [templateNameInput, setTemplateNameInput] = useState("");
  const [templateSaveError, setTemplateSaveError] = useState<string | null>(
    null,
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [deleteCandidateId, setDeleteCandidateId] = useState<string | null>(
    null,
  );
  const editorRef = useRef<HTMLFormElement>(null);
  const shouldFocusEditorRef = useRef(false);
  const aiNameRequestRef = useRef(0);
  const activeModelOptions = modelOptionsForDraft(modelOptions, draft.model);
  const creationPresets = useMemo(
    () => [
      ...PLAYER_CREATION_PRESETS,
      ...customCreationPresets,
      AI_PLAYER_CREATION_PRESET,
    ],
    [customCreationPresets],
  );
  const creationReadiness = useMemo(
    () =>
      getPlayerProfileCreationReadiness(draft, profiles, editingProfileId),
    [draft, editingProfileId, profiles],
  );
  const canSave =
    !isSaving &&
    !isUploadingAvatar &&
    !isGeneratingAiDraft &&
    !isGeneratingAiName &&
    creationReadiness.canSave;

  const updateDraft = <Key extends keyof PlayerProfileRequest>(
    key: Key,
    value: PlayerProfileRequest[Key],
  ) =>
    setDraft((current) => ({
      ...current,
      [key]: value,
      ...(key === "personality_id" && value !== current.personality_id
        ? { personality_text: "" }
        : {}),
    }));

  const setDraftAndListInputs = useCallback((nextDraft: PlayerProfileRequest) => {
    setDraft(nextDraft);
    setTagInput(formatTagInput(nextDraft.tags));
    setCatchphraseInput(formatListInput(nextDraft.catchphrases));
    setExampleMessageInput(formatMultilineInput(nextDraft.example_messages));
  }, []);

  const applySystemAvatar = (avatar: SystemPlayerAvatar) => {
    setDraft((current) => ({
      ...current,
      appearance_id: avatar.id,
      avatar_asset_id: avatar.assetId,
      avatar_image_url: systemPlayerAvatarImageUrl(avatar),
      avatar_image_mime: avatar.mime,
    }));
  };

  const buildFreshDraft = useCallback(
    (reservedNames: string[] = []) => {
      const avatar = randomSystemPlayerAvatar();
      const reservedProfiles = [
        ...profiles,
        ...reservedNames.map((name, index) => ({
          id: `reserved-profile-${index}`,
          display_name: name,
        })),
      ];

      return applyPlayerCreationPreset(
        {
          ...defaultDraft(modelOptions[0]?.id ?? ""),
          display_name: nextAvailableProfileName(
            generateVirtualPlayerName(),
            reservedProfiles,
          ),
          appearance_id: avatar.id,
          avatar_asset_id: avatar.assetId,
          avatar_image_url: systemPlayerAvatarImageUrl(avatar),
          avatar_image_mime: avatar.mime,
        },
        DEFAULT_PLAYER_CREATION_PRESET_ID,
      );
    },
    [modelOptions, profiles],
  );

  const requestAiNameForDraft = useCallback(() => {
    if (!onGenerateAiDraft) {
      setActionError("无法生成 AI 昵称");
      return;
    }

    const requestId = aiNameRequestRef.current + 1;
    aiNameRequestRef.current = requestId;
    const fallbackName = draft.display_name;

    setActionError(null);
    setIsGeneratingAiName(true);
    void onGenerateAiDraft({
      mode: "name",
      existing_names: [],
    })
      .then((aiDraft) => {
        const generatedName = aiDraft.display_name?.trim();
        if (!generatedName) {
          return;
        }

        setDraft((current) => {
          if (
            aiNameRequestRef.current !== requestId ||
            current.display_name !== fallbackName
          ) {
            return current;
          }

          return {
            ...current,
            display_name: nextAvailableProfileName(
              generatedName,
              profiles,
              editingProfileId,
            ),
          };
        });
      })
      .catch(() => setActionError("无法生成 AI 昵称"))
      .finally(() => setIsGeneratingAiName(false));
    },
    [draft.display_name, editingProfileId, onGenerateAiDraft, profiles],
  );

  const startCreate = useCallback(() => {
    const nextDraft = buildFreshDraft();

    shouldFocusEditorRef.current = true;
    setActionError(null);
    setDeleteCandidateId(null);
    setSelectedCreationPresetId(DEFAULT_PLAYER_CREATION_PRESET_ID);
    setDraftAndListInputs(nextDraft);
    setEditingProfileId(null);
    setIsEditorOpen(true);
    setFocusEditorRequest((request) => request + 1);
  }, [buildFreshDraft, setDraftAndListInputs]);

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
        "input:not([type='file']):not([disabled]), select:not([disabled]), textarea:not([disabled]), button:not(.virtual-player-preset-option):not([disabled])",
      )
      ?.focus();
  }, [focusEditorRequest, isEditorOpen]);

  const startEdit = (profile: VirtualPlayerProfile) => {
    const nextDraft = profileToDraft(profile);

    aiNameRequestRef.current += 1;
    setActionError(null);
    setDeleteCandidateId(null);
    setIsTemplateDialogOpen(false);
    setSelectedCreationPresetId(DEFAULT_PLAYER_CREATION_PRESET_ID);
    setDraftAndListInputs(nextDraft);
    setEditingProfileId(profile.id);
    setIsEditorOpen(true);
  };

  const cancelEditor = () => {
    aiNameRequestRef.current += 1;
    setActionError(null);
    setIsEditorOpen(false);
    setIsTemplateDialogOpen(false);
    setTemplateSaveError(null);
    setEditingProfileId(null);
    setSelectedCreationPresetId(DEFAULT_PLAYER_CREATION_PRESET_ID);
    setDraftAndListInputs(defaultDraft());
  };

  const applyCreationPreset = (presetId: PlayerCreationPresetId) => {
    setSelectedCreationPresetId(presetId);
    if (presetId === AI_PLAYER_CREATION_PRESET_ID) {
      if (!onGenerateAiDraft) {
        setActionError("无法生成 AI 模板");
        return;
      }

      setActionError(null);
      setIsGeneratingAiDraft(true);
      void onGenerateAiDraft({
        mode: "template",
        existing_names: profiles.map((profile) => profile.display_name),
      })
        .then((aiDraft) => {
          setDraft((current) => {
            const nextDraft = mergeAiDraftIntoProfileDraft(current, aiDraft);
            setTagInput(formatTagInput(nextDraft.tags));
            setCatchphraseInput(formatListInput(nextDraft.catchphrases));
            setExampleMessageInput(
              formatMultilineInput(nextDraft.example_messages),
            );
            return nextDraft;
          });
        })
        .catch(() => setActionError("无法生成 AI 模板"))
        .finally(() => setIsGeneratingAiDraft(false));
      return;
    }

    setDraft((current) => {
      const nextDraft = applyPlayerCreationPreset(
        current,
        presetId,
        creationPresets,
      );
      setTagInput(formatTagInput(nextDraft.tags));
      setCatchphraseInput(formatListInput(nextDraft.catchphrases));
      setExampleMessageInput(formatMultilineInput(nextDraft.example_messages));
      return nextDraft;
    });
  };

  const saveDraft = async (options: { continueCreating?: boolean } = {}) => {
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
      avatar_asset_id: draft.avatar_asset_id?.trim() ?? null,
      avatar_image_url: draft.avatar_image_url?.trim() ?? "",
      avatar_image_mime: draft.avatar_image_mime?.trim() ?? "",
      tags: cleanList(draft.tags),
    };
    const wasEditing = Boolean(editingProfileId);
    try {
      if (editingProfileId) {
        await onUpdateProfile(editingProfileId, request);
      } else {
        await onCreateProfile(request);
      }
      if (!wasEditing && options.continueCreating) {
        shouldFocusEditorRef.current = true;
        const nextDraft = buildFreshDraft([request.display_name]);
        setSelectedCreationPresetId(DEFAULT_PLAYER_CREATION_PRESET_ID);
        setDraftAndListInputs(nextDraft);
        setEditingProfileId(null);
        setIsEditorOpen(true);
        setIsTemplateDialogOpen(false);
        setFocusEditorRequest((requestCount) => requestCount + 1);
        return;
      }

      setIsEditorOpen(false);
      setEditingProfileId(null);
      setIsTemplateDialogOpen(false);
      setSelectedCreationPresetId(DEFAULT_PLAYER_CREATION_PRESET_ID);
      setDraftAndListInputs(defaultDraft());
    } catch {
      setActionError("无法保存虚拟玩家");
    }
  };

  const copyProfile = (profile: VirtualPlayerProfile) => {
    setActionError(null);
    void onCreateProfile({
      ...profileToDraft(profile),
      display_name: nextAvailableProfileName(
        `${profile.display_name} 副本`,
        profiles,
      ),
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
        avatar_asset_id: response.avatar_asset_id,
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

  const openSaveTemplateDialog = () => {
    setTemplateNameInput(
      draft.display_name.trim() ? `${draft.display_name.trim()}模板` : "",
    );
    setTemplateSaveError(null);
    setIsTemplateDialogOpen(true);
  };

  const cancelSaveTemplateDialog = () => {
    setIsTemplateDialogOpen(false);
    setTemplateSaveError(null);
  };

  const saveCurrentDraftAsTemplate = () => {
    const templateName = templateNameInput.trim();
    if (!templateName) {
      setTemplateSaveError("请输入模板名");
      return;
    }

    const nextPreset = createPlayerCreationPresetFromDraft(
      `custom-${Date.now().toString(36)}-${Math.random()
        .toString(36)
        .slice(2, 8)}`,
      templateName,
      draft,
    );
    setCustomCreationPresets((current) => {
      const nextPresets = [...current, nextPreset];
      persistCustomCreationPresets(nextPresets);
      return nextPresets;
    });
    setSelectedCreationPresetId(nextPreset.id);
    setTemplateSaveError(null);
    setIsTemplateDialogOpen(false);
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
      </div>

      {isEditorOpen ? (
        <div className="virtual-player-editor-dialog-backdrop">
          <div
            aria-labelledby="virtual-player-editor-dialog-title"
            aria-modal="true"
            className="virtual-player-editor-dialog"
            role="dialog"
          >
            <h3
              className="virtual-player-editor-dialog-title"
              id="virtual-player-editor-dialog-title"
            >
              {editingProfileId ? "编辑虚拟玩家" : "新建虚拟玩家"}
            </h3>
            <VirtualPlayerEditor
              ref={editorRef}
              canSave={canSave}
              catchphraseInput={catchphraseInput}
              creationPresets={creationPresets}
              creationReadiness={creationReadiness}
              draft={draft}
              exampleMessageInput={exampleMessageInput}
              isGeneratingAiDraft={isGeneratingAiDraft}
              isGeneratingAiName={isGeneratingAiName}
              isEditing={Boolean(editingProfileId)}
              isAvatarDragging={isAvatarDragging}
              isSaving={isSaving}
              isTemplateDialogOpen={isTemplateDialogOpen}
              isUploadingAvatar={isUploadingAvatar}
              modelOptions={activeModelOptions}
              selectedCreationPresetId={selectedCreationPresetId}
              tagInput={tagInput}
              onApplySystemAvatar={applySystemAvatar}
              onAvatarDragLeave={handleAvatarDragLeave}
              onAvatarDragOver={handleAvatarDragOver}
              onAvatarDrop={handleAvatarDrop}
              onAvatarFileChange={(event) => void uploadAvatar(event)}
              onCancel={cancelEditor}
              onCancelSaveTemplate={cancelSaveTemplateDialog}
              onCatchphraseInputChange={handleCatchphraseInputChange}
              onConfirmSaveTemplate={saveCurrentDraftAsTemplate}
              onCreationPresetChange={applyCreationPreset}
              onDraftChange={updateDraft}
              onExampleMessageInputChange={handleExampleMessageInputChange}
              onGenerateAiName={requestAiNameForDraft}
              onOpenSaveTemplate={openSaveTemplateDialog}
              onSave={() => void saveDraft()}
              onSaveAndContinue={() =>
                void saveDraft({ continueCreating: true })
              }
              onTagInputChange={handleTagInputChange}
              onTemplateNameInputChange={setTemplateNameInput}
              templateNameInput={templateNameInput}
              templateSaveError={templateSaveError}
            />
          </div>
        </div>
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
