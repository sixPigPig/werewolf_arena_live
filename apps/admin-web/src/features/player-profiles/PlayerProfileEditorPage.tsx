import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cloneElement,
  type FormEvent,
  isValidElement,
  type KeyboardEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import {
  Link,
  useBlocker,
  useBeforeUnload,
  useNavigate,
  useParams,
} from "react-router-dom";

import { AdminApiError, isAdminApiError } from "@/api/problem-details";
import { hasAdminPermission } from "@/features/auth/permissions";
import { useAdminSession } from "@/features/auth/session-context";
import {
  cleanPlayerProfileInput,
  formErrorsFromApi,
  formatCommaList,
  formatMultilineList,
  inputFromProfile,
  parseCommaList,
  parseMultilineList,
  type PlayerProfileFormErrors,
  validatePlayerProfileInput,
} from "@/features/player-profiles/form";
import { PlayerTransitionDialog } from "@/features/player-profiles/PlayerTransitionDialog";
import { playerProfileKeys } from "@/features/player-profiles/query-keys";
import { usePlayerProfileRepository } from "@/features/player-profiles/repository";
import type {
  AdminPlayerProfile,
  AdminPlayerVoicePreview,
  PlayerProfileEditableFields,
  PlayerProfileOptions,
  PlayerProfileStatus,
  PlayerTtsSpeakerOption,
} from "@/features/player-profiles/types";

const STATUS_LABELS: Record<PlayerProfileStatus, string> = {
  draft: "草稿",
  published: "已发布",
  archived: "已归档",
};

type TransitionAction = "archive" | "publish" | "restore";

const TRANSITION_COPY: Record<
  TransitionAction,
  { title: string; description: string; actionLabel: string }
> = {
  publish: {
    title: "发布虚拟玩家",
    description: "发布后该玩家可进入 C 端与新对局，请确认内容已经审核。",
    actionLabel: "确认发布",
  },
  archive: {
    title: "归档虚拟玩家",
    description: "归档会立即从 C 端和新对局候选中移除，但不会影响历史对局。",
    actionLabel: "确认归档",
  },
  restore: {
    title: "恢复并重新发布",
    description: "恢复会将该玩家重新发布到 C 端，请确认内容仍然有效。",
    actionLabel: "确认恢复",
  },
};

export default function PlayerProfileEditorPage() {
  const { profileId } = useParams<{ profileId: string }>();
  const isNew = !profileId;
  const repository = usePlayerProfileRepository();
  const [reloadRevision, setReloadRevision] = useState(0);
  const optionsQuery = useQuery({
    queryKey: playerProfileKeys.options(),
    queryFn: ({ signal }) => repository.getOptions(signal),
    staleTime: 5 * 60_000,
  });
  const profileQuery = useQuery({
    enabled: !isNew,
    queryKey: playerProfileKeys.detail(profileId ?? "new"),
    queryFn: ({ signal }) => repository.get(profileId!, signal),
  });
  const ttsSpeakersQuery = useQuery({
    enabled: isNew || profileQuery.data?.tts_speaker !== undefined,
    queryKey: playerProfileKeys.ttsSpeakers(),
    queryFn: ({ signal }) => repository.getTtsSpeakers(signal),
    staleTime: 60 * 60_000,
  });

  async function reloadProfile() {
    const result = await profileQuery.refetch();
    if (result.data) {
      setReloadRevision((current) => current + 1);
    }
  }

  if (optionsQuery.isPending || (!isNew && profileQuery.isPending)) {
    return <EditorLoading />;
  }
  if (optionsQuery.isError) {
    return (
      <EditorLoadError
        description="无法读取模型、人设与形象选项。"
        error={optionsQuery.error}
        onRetry={optionsQuery.refetch}
      />
    );
  }
  if (!isNew && profileQuery.isError) {
    return (
      <EditorLoadError
        description={
          isAdminApiError(profileQuery.error, 404)
            ? "该玩家不存在或已被移除。"
            : "无法读取玩家详情。"
        }
        error={profileQuery.error}
        onRetry={profileQuery.refetch}
      />
    );
  }

  return (
    <PlayerProfileEditor
      initialProfile={profileQuery.data ?? null}
      isNew={isNew}
      key={`${profileId ?? "new"}:${reloadRevision}`}
      onReload={() => void reloadProfile()}
      options={optionsQuery.data}
      repository={repository}
      ttsSpeakerOptions={ttsSpeakersQuery.data?.items ?? []}
      ttsSpeakersError={ttsSpeakersQuery.isError}
      ttsSpeakersPending={ttsSpeakersQuery.isPending}
      onRetryTtsSpeakers={() => void ttsSpeakersQuery.refetch()}
    />
  );
}

function PlayerProfileEditor({
  initialProfile,
  isNew,
  onReload,
  onRetryTtsSpeakers,
  options,
  repository,
  ttsSpeakerOptions,
  ttsSpeakersError,
  ttsSpeakersPending,
}: {
  initialProfile: AdminPlayerProfile | null;
  isNew: boolean;
  onReload: () => void;
  onRetryTtsSpeakers: () => void;
  options: PlayerProfileOptions;
  repository: ReturnType<typeof usePlayerProfileRepository>;
  ttsSpeakerOptions: PlayerTtsSpeakerOption[];
  ttsSpeakersError: boolean;
  ttsSpeakersPending: boolean;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { session } = useAdminSession();
  const permissions = session?.permissions ?? [];
  const canWrite = hasAdminPermission(permissions, "players.write");
  const canPublish = hasAdminPermission(permissions, "players.publish");
  const canArchive = hasAdminPermission(permissions, "players.archive");
  const canGenerateAi = hasAdminPermission(
    permissions,
    "players.ai_generate",
  );
  const defaults = {
    model: options.models[0]?.id ?? "",
    personality_id: options.personalities[0]?.id ?? "balanced",
    strategy_profile: options.strategies[0]?.id ?? "balanced",
    appearance_id: options.appearances[0]?.id ?? "default",
    avatar_asset_id: options.appearances[0]?.avatar_asset_id ?? null,
    tts_speaker: null,
    base_delivery_mood: "neutral",
    base_delivery_intensity: "medium",
    base_delivery_pace: "natural",
    base_delivery_instruction: null,
    voice_enabled: true,
  };
  const initialInput = inputFromProfile(initialProfile, defaults);
  const [profile, setProfile] = useState(initialProfile);
  const [draft, setDraft] = useState(initialInput);
  const [catchphraseInput, setCatchphraseInput] = useState(() =>
    formatCommaList(initialInput.catchphrases),
  );
  const [tagInput, setTagInput] = useState(() =>
    formatCommaList(initialInput.tags),
  );
  const [exampleInput, setExampleInput] = useState(() =>
    formatMultilineList(initialInput.example_messages),
  );
  const [formErrors, setFormErrors] = useState<PlayerProfileFormErrors>({});
  const [requestError, setRequestError] = useState<AdminApiError | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [conflict, setConflict] = useState<AdminApiError | null>(null);
  const [pendingAction, setPendingAction] = useState<
    "ai-draft" | "save" | TransitionAction | null
  >(null);
  const [transitionAction, setTransitionAction] =
    useState<TransitionAction | null>(null);
  const [transitionError, setTransitionError] = useState<string | null>(null);
  const [voicePreviewSay, setVoicePreviewSay] = useState(
    "我先听完这一轮，再给出我的判断。",
  );
  const [turnDelivery, setTurnDelivery] = useState({
    mood: "",
    intensity: "",
    pace: "",
    instruction: "",
  });
  const [voicePreview, setVoicePreview] =
    useState<AdminPlayerVoicePreview | null>(null);
  const [voicePreviewError, setVoicePreviewError] =
    useState<AdminApiError | null>(null);
  const [voicePreviewPending, setVoicePreviewPending] = useState(false);
  const allowNavigation = useRef(false);
  const baseline = useRef(JSON.stringify(initialInput));
  const status = profile?.status ?? "new";
  const isDirty = JSON.stringify(cleanPlayerProfileInput(draft)) !== baseline.current;
  const canEdit =
    isNew
      ? canWrite
      : status === "draft"
        ? canWrite
        : status === "published"
          ? canWrite && canPublish
          : false;
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) =>
      !allowNavigation.current &&
      isDirty &&
      currentLocation.pathname !== nextLocation.pathname,
  );

  useBeforeUnload(
    useCallback(
      (event) => {
        if (isDirty) {
          event.preventDefault();
        }
      },
      [isDirty],
    ),
    { capture: true },
  );

  const modelOptions = options.models.some((item) => item.id === draft.model)
    ? options.models
    : [{ id: draft.model, label: `当前模型 · ${draft.model}` }, ...options.models];
  const selectedAppearance = options.appearances.find(
    (item) => item.id === draft.appearance_id,
  );
  const avatarImageUrl =
    selectedAppearance?.avatar_asset_id === draft.avatar_asset_id
      ? selectedAppearance.avatar_image_url
      : profile?.avatar_image_url ?? selectedAppearance?.avatar_image_url ?? "";
  const hasVoiceConfig =
    draft.tts_speaker !== undefined ||
    draft.base_delivery_mood !== undefined ||
    draft.base_delivery_intensity !== undefined ||
    draft.base_delivery_pace !== undefined ||
    draft.base_delivery_instruction !== undefined ||
    draft.voice_enabled !== undefined ||
    profile?.voice_config_version !== undefined;

  function updateDraft<Key extends keyof PlayerProfileEditableFields>(
    field: Key,
    value: PlayerProfileEditableFields[Key],
  ) {
    setDraft((current) => ({ ...current, [field]: value }));
    setFormErrors((current) => ({ ...current, [field]: undefined, form: undefined }));
    setSuccessMessage(null);
    setVoicePreview(null);
    setVoicePreviewError(null);
  }

  function updateTurnDelivery(
    field: keyof typeof turnDelivery,
    value: string,
  ) {
    setTurnDelivery((current) => ({ ...current, [field]: value }));
    setVoicePreview(null);
    setVoicePreviewError(null);
  }

  async function previewDraftVoice() {
    if (!canEdit || voicePreviewPending || !voicePreviewSay.trim()) {
      return;
    }
    setVoicePreviewPending(true);
    setVoicePreview(null);
    setVoicePreviewError(null);
    try {
      const result = await repository.previewVoice({
        say: voicePreviewSay.trim(),
        speaker: draft.tts_speaker?.trim() || null,
        base_delivery: {
          mood: draft.base_delivery_mood ?? null,
          intensity: draft.base_delivery_intensity ?? null,
          pace: draft.base_delivery_pace ?? null,
          instruction: draft.base_delivery_instruction?.trim() || null,
        },
        turn_delivery: {
          mood: turnDelivery.mood || null,
          intensity: turnDelivery.intensity || null,
          pace: turnDelivery.pace || null,
          instruction: turnDelivery.instruction.trim() || null,
        },
      });
      setVoicePreview(result);
    } catch (error) {
      setVoicePreviewError(
        error instanceof AdminApiError
          ? error
          : new AdminApiError({
              cause: error,
              problem: {
                type: "about:blank",
                title: "语音试听失败",
                status: 0,
                detail: "语音试听未能完成，请稍后重试。",
                code: "admin_player_voice_preview_request_failed",
                request_id: null,
              },
            }),
      );
    } finally {
      setVoicePreviewPending(false);
    }
  }

  async function generateAiDraft() {
    if (!isNew || !canEdit || !canGenerateAi) {
      return;
    }
    setPendingAction("ai-draft");
    setRequestError(null);
    setSuccessMessage(null);
    try {
      const generated = await repository.generateAiDraft();
      setDraft((current) => ({ ...current, ...generated }));
      setCatchphraseInput(formatCommaList(generated.catchphrases));
      setTagInput(formatCommaList(generated.tags));
      setExampleInput(formatMultilineList(generated.example_messages));
      setFormErrors({});
      setSuccessMessage("AI 草稿已填入，请审核后保存");
    } catch (error) {
      handleRequestError(error);
    } finally {
      setPendingAction(null);
    }
  }

  async function saveProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleaned = cleanPlayerProfileInput(draft);
    const errors = validatePlayerProfileInput(cleaned, options.constraints, status);
    if (Object.keys(errors).length > 0) {
      setFormErrors(errors);
      focusFirstInvalidField(errors);
      return;
    }
    if (!canEdit) {
      return;
    }

    setPendingAction("save");
    setRequestError(null);
    setConflict(null);
    setSuccessMessage(null);
    try {
      const updated = isNew
        ? await repository.create({ ...cleaned, featured: false })
        : await repository.update(profile!.id, {
            ...cleaned,
            expected_version: profile!.version,
          });
      queryClient.setQueryData(playerProfileKeys.detail(updated.id), updated);
      await queryClient.invalidateQueries({ queryKey: playerProfileKeys.lists() });
      if (isNew) {
        allowNavigation.current = true;
        navigate(`/content/players/${encodeURIComponent(updated.id)}`, {
          replace: true,
          state: { notice: "草稿已创建" },
        });
        return;
      }
      const nextInput = inputFromProfile(updated);
      setProfile(updated);
      setDraft(nextInput);
      setCatchphraseInput(formatCommaList(nextInput.catchphrases));
      setTagInput(formatCommaList(nextInput.tags));
      setExampleInput(formatMultilineList(nextInput.example_messages));
      baseline.current = JSON.stringify(nextInput);
      setFormErrors({});
      setSuccessMessage("玩家资料已保存");
    } catch (error) {
      handleRequestError(error);
    } finally {
      setPendingAction(null);
    }
  }

  function handleRequestError(error: unknown) {
    const apiError =
      error instanceof AdminApiError
        ? error
        : new AdminApiError({
            cause: error,
            problem: {
              type: "about:blank",
              title: "玩家操作失败",
              status: 0,
              detail: "玩家操作未能完成，请稍后重试。",
              code: "admin_player_profile_request_failed",
              request_id: null,
            },
          });
    if (apiError.status === 409) {
      setConflict(apiError);
      setTransitionAction(null);
      return;
    }
    if (apiError.status === 422 && apiError.fieldErrors.length > 0) {
      const errors = formErrorsFromApi(apiError.fieldErrors);
      setFormErrors(errors);
      setTransitionError(apiError.message);
      focusFirstInvalidField(errors);
      return;
    }
    setRequestError(apiError);
    setTransitionError(apiError.message);
  }

  async function confirmTransition(reason: string) {
    if (!profile || !transitionAction || isDirty) {
      if (isDirty) {
        setTransitionError("请先保存当前修改，再执行生命周期操作。");
      }
      return;
    }
    setPendingAction(transitionAction);
    setTransitionError(null);
    setRequestError(null);
    setConflict(null);
    try {
      const updated = await repository.transition(
        profile.id,
        transitionAction,
        { expected_version: profile.version, reason },
      );
      queryClient.setQueryData(playerProfileKeys.detail(updated.id), updated);
      await queryClient.invalidateQueries({ queryKey: playerProfileKeys.lists() });
      const nextInput = inputFromProfile(updated);
      setProfile(updated);
      setDraft(nextInput);
      baseline.current = JSON.stringify(nextInput);
      setTransitionAction(null);
      setSuccessMessage(
        transitionAction === "archive"
          ? "玩家已归档"
          : transitionAction === "restore"
            ? "玩家已恢复发布"
            : "玩家已发布",
      );
    } catch (error) {
      handleRequestError(error);
    } finally {
      setPendingAction(null);
    }
  }

  function reloadAfterConflict() {
    setConflict(null);
    onReload();
  }

  return (
    <div className="admin-page player-editor-page">
      <header className="page-heading player-editor-heading">
        <div>
          <Link className="player-back-link" to="/content/players">
            ← 返回玩家内容库
          </Link>
          <span className="page-kicker">CONTENT / PLAYER PROFILE</span>
          <h1>{isNew ? "新建玩家草稿" : profile?.display_name}</h1>
          <p>
            {isNew
              ? "先保存为草稿，审核完整人设后再发布到 C 端。"
              : `ID ${profile?.id} · 版本 ${profile?.version}`}
          </p>
        </div>
        <div className="player-editor-status-actions">
          {isNew && canEdit && canGenerateAi ? (
            <button
              className="player-ai-draft-button"
              disabled={pendingAction !== null || voicePreviewPending}
              onClick={() => void generateAiDraft()}
              type="button"
            >
              {pendingAction === "ai-draft" ? "AI 生成中..." : "AI 生成草稿"}
            </button>
          ) : null}
          {profile ? (
            <span className={`player-status-badge is-${profile.status}`}>
              {STATUS_LABELS[profile.status]}
            </span>
          ) : (
            <span className="player-status-badge is-draft">新草稿</span>
          )}
          {!canEdit ? <span className="page-readiness-badge">只读</span> : null}
        </div>
      </header>

      {profile?.status === "published" && canEdit ? (
        <div className="player-editor-notice is-warning" role="status">
          此玩家已发布。保存修改会立即影响 C 端和后续新对局。
        </div>
      ) : null}
      {profile?.status === "archived" ? (
        <div className="player-editor-notice" role="status">
          已归档玩家不能直接编辑；恢复后会重新发布。
        </div>
      ) : null}
      {repository.isPreview ? (
        <div className="player-editor-notice" role="status">
          当前为本地预览数据，不会请求或修改真实 Admin API。
        </div>
      ) : null}
      {successMessage ? (
        <div aria-live="polite" className="player-editor-notice is-success" role="status">
          {successMessage}
        </div>
      ) : null}
      {conflict ? (
        <div aria-live="assertive" className="player-conflict-banner" role="alert">
          <div>
            <strong>其他操作者已经更新了该玩家</strong>
            <p>
              你的表单内容仍然保留。服务器当前版本为 {conflict.currentVersion ?? "未知"}，
              重新加载会用最新内容替换当前表单。
            </p>
          </div>
          <button onClick={reloadAfterConflict} type="button">
            重新加载最新版本
          </button>
        </div>
      ) : null}
      {requestError ? (
        <div aria-live="assertive" className="player-request-error" role="alert">
          <strong>{requestError.problem.title}</strong>
          <span>{requestError.message}</span>
          {requestError.requestId ? <small>请求编号：{requestError.requestId}</small> : null}
        </div>
      ) : null}

      <form className="player-editor-layout" noValidate onSubmit={saveProfile}>
        <div className="player-editor-form-column">
          <fieldset
            disabled={!canEdit || pendingAction !== null || voicePreviewPending}
          >
            <legend>玩家内容</legend>
            <section aria-labelledby="player-basic-title" className="player-form-section">
              <SectionHeading
                description="名称和模型决定玩家在内容库与对局中的基础身份。"
                id="player-basic-title"
                title="基础信息"
              />
              <div className="player-form-grid">
                <Field label="玩家名称" error={formErrors.display_name} required>
                  <input
                    aria-label="玩家名称"
                    aria-invalid={Boolean(formErrors.display_name)}
                    maxLength={80}
                    name="display_name"
                    onChange={(event) => updateDraft("display_name", event.target.value)}
                    value={draft.display_name}
                  />
                </Field>
                <Field label="默认模型" error={formErrors.model} required>
                  <select
                    aria-invalid={Boolean(formErrors.model)}
                    name="model"
                    onChange={(event) => updateDraft("model", event.target.value)}
                    value={draft.model}
                  >
                    {modelOptions.map((option) => (
                      <option key={option.id} value={option.id}>{option.label}</option>
                    ))}
                  </select>
                </Field>
                <Field
                  className="is-wide"
                  label="一句话简介"
                  error={formErrors.short_description}
                  help="最多 160 个字符"
                >
                  <input
                    aria-invalid={Boolean(formErrors.short_description)}
                    maxLength={160}
                    name="short_description"
                    onChange={(event) =>
                      updateDraft("short_description", event.target.value)
                    }
                    value={draft.short_description}
                  />
                </Field>
              </div>
            </section>

            <section aria-labelledby="player-persona-title" className="player-form-section">
              <SectionHeading
                description="人设、策略和倾向会进入模型提示词。"
                id="player-persona-title"
                title="人设与策略"
              />
              <div className="player-form-grid">
                <Field label="性格">
                  <select
                    name="personality_id"
                    onChange={(event) => updateDraft("personality_id", event.target.value)}
                    value={draft.personality_id}
                  >
                    {options.personalities.map((option) => (
                      <option key={option.id} value={option.id}>{option.label}</option>
                    ))}
                  </select>
                </Field>
                <Field label="策略模板">
                  <select
                    name="strategy_profile"
                    onChange={(event) => updateDraft("strategy_profile", event.target.value)}
                    value={draft.strategy_profile}
                  >
                    {options.strategies.map((option) => (
                      <option key={option.id} value={option.id}>{option.label}</option>
                    ))}
                  </select>
                </Field>
                <Field className="is-wide" label="性格描述">
                  <textarea
                    name="personality_text"
                    onChange={(event) => updateDraft("personality_text", event.target.value)}
                    rows={4}
                    value={draft.personality_text}
                  />
                </Field>
              </div>
              <div className="player-tendency-grid">
                <TendencyField label="冒险倾向" field="risk_tolerance" />
                <TendencyField label="伪装倾向" field="bluffing_tendency" />
                <TendencyField label="信任倾向" field="trust_tendency" />
                <TendencyField label="领导倾向" field="leadership_tendency" />
                <TendencyField label="发言活跃" field="talkativeness" />
              </div>
            </section>

            <section aria-labelledby="player-voice-title" className="player-form-section">
              <SectionHeading
                description="用于约束玩家的背景、语气和可参考表达。"
                id="player-voice-title"
                title="背景与表达"
              />
              <div className="player-form-grid">
                <Field label="背景故事" error={formErrors.background_story}>
                  <textarea
                    aria-invalid={Boolean(formErrors.background_story)}
                    maxLength={1200}
                    name="background_story"
                    onChange={(event) => updateDraft("background_story", event.target.value)}
                    rows={5}
                    value={draft.background_story}
                  />
                </Field>
                <Field label="发言风格" error={formErrors.speaking_style}>
                  <textarea
                    aria-invalid={Boolean(formErrors.speaking_style)}
                    maxLength={800}
                    name="speaking_style"
                    onChange={(event) => updateDraft("speaking_style", event.target.value)}
                    rows={5}
                    value={draft.speaking_style}
                  />
                </Field>
                <Field label="常用表达" error={formErrors.catchphrases} help="使用逗号分隔">
                  <input
                    aria-invalid={Boolean(formErrors.catchphrases)}
                    name="catchphrases"
                    onChange={(event) => {
                      setCatchphraseInput(event.target.value);
                      updateDraft("catchphrases", parseCommaList(event.target.value));
                    }}
                    value={catchphraseInput}
                  />
                </Field>
                <Field label="标签" error={formErrors.tags} help="使用逗号分隔">
                  <input
                    aria-invalid={Boolean(formErrors.tags)}
                    name="tags"
                    onChange={(event) => {
                      setTagInput(event.target.value);
                      updateDraft("tags", parseCommaList(event.target.value));
                    }}
                    value={tagInput}
                  />
                </Field>
                <Field
                  className="is-wide"
                  label="示例发言"
                  error={formErrors.example_messages}
                  help="每行一条"
                >
                  <textarea
                    aria-invalid={Boolean(formErrors.example_messages)}
                    name="example_messages"
                    onChange={(event) => {
                      setExampleInput(event.target.value);
                      updateDraft("example_messages", parseMultilineList(event.target.value));
                    }}
                    rows={5}
                    value={exampleInput}
                  />
                </Field>
              </div>
            </section>

            {hasVoiceConfig ? (
              <section aria-labelledby="player-tts-title" className="player-form-section">
                <SectionHeading
                  description="玩家音色可继承全局配置；基础演绎留空时分别重置为内置 neutral、medium 与 natural。"
                  id="player-tts-title"
                  title="玩家音色与基础演绎"
                />
                {draft.voice_enabled !== undefined ? (
                  <label className="player-featured-control">
                    <input
                      checked={draft.voice_enabled}
                      name="voice_enabled"
                      onChange={(event) =>
                        updateDraft("voice_enabled", event.target.checked)
                      }
                      type="checkbox"
                    />
                    <span>
                      <strong>为新对局启用玩家语音</strong>
                      <small>关闭只影响之后创建的新对局，不改写运行中或历史语音。</small>
                    </span>
                  </label>
                ) : null}
                <div className="player-form-grid player-voice-config-grid">
                  {draft.tts_speaker !== undefined ? (
                    <TtsSpeakerField
                      error={formErrors.tts_speaker}
                      isError={ttsSpeakersError}
                      isPending={ttsSpeakersPending}
                      onChange={(speaker) => updateDraft("tts_speaker", speaker)}
                      onRetry={onRetryTtsSpeakers}
                      options={ttsSpeakerOptions}
                      value={draft.tts_speaker ?? null}
                    />
                  ) : null}
                  {draft.base_delivery_mood !== undefined ? (
                    <Field
                      error={formErrors.base_delivery_mood}
                      label="基础情绪"
                      help="留空重置为内置中性情绪 neutral。"
                    >
                      <select
                        name="base_delivery_mood"
                        onChange={(event) =>
                          updateDraft(
                            "base_delivery_mood",
                            event.target.value || null,
                          )
                        }
                        value={draft.base_delivery_mood ?? ""}
                      >
                        {voiceDeliveryOptions(
                          PLAYER_DELIVERY_MOOD_OPTIONS,
                          draft.base_delivery_mood,
                          "内置默认 · neutral",
                        )}
                      </select>
                    </Field>
                  ) : null}
                  {draft.base_delivery_intensity !== undefined ? (
                    <Field
                      error={formErrors.base_delivery_intensity}
                      label="基础强度"
                      help="留空重置为内置中等强度 medium。"
                    >
                      <select
                        name="base_delivery_intensity"
                        onChange={(event) =>
                          updateDraft(
                            "base_delivery_intensity",
                            event.target.value || null,
                          )
                        }
                        value={draft.base_delivery_intensity ?? ""}
                      >
                        {voiceDeliveryOptions(
                          PLAYER_DELIVERY_INTENSITY_OPTIONS,
                          draft.base_delivery_intensity,
                          "内置默认 · medium",
                        )}
                      </select>
                    </Field>
                  ) : null}
                  {draft.base_delivery_pace !== undefined ? (
                    <Field
                      error={formErrors.base_delivery_pace}
                      label="基础语速"
                      help="留空重置为内置自然语速 natural。"
                    >
                      <select
                        name="base_delivery_pace"
                        onChange={(event) =>
                          updateDraft(
                            "base_delivery_pace",
                            event.target.value || null,
                          )
                        }
                        value={draft.base_delivery_pace ?? ""}
                      >
                        {voiceDeliveryOptions(
                          PLAYER_DELIVERY_PACE_OPTIONS,
                          draft.base_delivery_pace,
                          "内置默认 · natural",
                        )}
                      </select>
                    </Field>
                  ) : null}
                  {draft.base_delivery_instruction !== undefined ? (
                    <Field
                      className="is-wide"
                      error={formErrors.base_delivery_instruction}
                      label="基础演绎提示"
                      help="只描述演绎方式，不应包含身份、座位、行动结果或其他游戏事实。"
                    >
                      <textarea
                        maxLength={240}
                        name="base_delivery_instruction"
                        onChange={(event) =>
                          updateDraft(
                            "base_delivery_instruction",
                            event.target.value,
                          )
                        }
                        rows={3}
                        value={draft.base_delivery_instruction ?? ""}
                      />
                    </Field>
                  ) : null}
                </div>
                <p className="player-voice-config-boundary">
                  当前生效：
                  {draft.voice_enabled === false
                    ? "语音关闭"
                    : draft.tts_speaker || "继承全局音色"}
                  {profile?.voice_config_version !== undefined
                    ? ` · 配置版本 ${profile.voice_config_version}`
                    : ""}
                  。保存后只影响新对局；进行中、恢复、已排队语音和历史 Replay 继续使用冻结快照。
                </p>
                <div className="player-voice-preview" aria-labelledby="player-voice-preview-title">
                  <header>
                    <div>
                      <h3 id="player-voice-preview-title">草稿语音试听</h3>
                      <p>直接使用当前未保存表单；只生成一次性受限音频，不创建正式语音任务或 Replay 数据。</p>
                    </div>
                    <span>seed-tts-2.0</span>
                  </header>
                  <div className="player-form-grid player-voice-preview-grid">
                    <Field className="is-wide" label="试听文本" help="最多 240 个字符">
                      <textarea
                        maxLength={240}
                        name="voice_preview_say"
                        onChange={(event) => {
                          setVoicePreviewSay(event.target.value);
                          setVoicePreview(null);
                          setVoicePreviewError(null);
                        }}
                        rows={3}
                        value={voicePreviewSay}
                      />
                    </Field>
                    <Field label="本轮情绪">
                      <select
                        name="voice_preview_mood"
                        onChange={(event) =>
                          updateTurnDelivery("mood", event.target.value)
                        }
                        value={turnDelivery.mood}
                      >
                        {voiceDeliveryOptions(
                          PLAYER_DELIVERY_MOOD_OPTIONS,
                          turnDelivery.mood,
                          "沿用基础情绪",
                        )}
                      </select>
                    </Field>
                    <Field label="本轮强度">
                      <select
                        name="voice_preview_intensity"
                        onChange={(event) =>
                          updateTurnDelivery("intensity", event.target.value)
                        }
                        value={turnDelivery.intensity}
                      >
                        {voiceDeliveryOptions(
                          PLAYER_DELIVERY_INTENSITY_OPTIONS,
                          turnDelivery.intensity,
                          "沿用基础强度",
                        )}
                      </select>
                    </Field>
                    <Field label="本轮语速">
                      <select
                        name="voice_preview_pace"
                        onChange={(event) =>
                          updateTurnDelivery("pace", event.target.value)
                        }
                        value={turnDelivery.pace}
                      >
                        {voiceDeliveryOptions(
                          PLAYER_DELIVERY_PACE_OPTIONS,
                          turnDelivery.pace,
                          "沿用基础语速",
                        )}
                      </select>
                    </Field>
                    <Field
                      className="is-wide"
                      label="本轮演绎提示"
                      help="含座位、身份、阵营或行动事实时，后端会丢弃整段并安全回退。"
                    >
                      <textarea
                        maxLength={240}
                        name="voice_preview_instruction"
                        onChange={(event) =>
                          updateTurnDelivery("instruction", event.target.value)
                        }
                        rows={2}
                        value={turnDelivery.instruction}
                      />
                    </Field>
                  </div>
                  <button
                    className="player-voice-preview-button"
                    disabled={
                      !canEdit ||
                      voicePreviewPending ||
                      pendingAction !== null ||
                      !voicePreviewSay.trim()
                    }
                    onClick={() => void previewDraftVoice()}
                    type="button"
                  >
                    {voicePreviewPending ? "正在合成..." : "试听当前草稿"}
                  </button>
                  {voicePreviewError ? (
                    <div className="player-voice-preview-error" role="alert">
                      <strong>{voicePreviewError.problem.title}</strong>
                      <span>{voicePreviewError.message}</span>
                      <code>错误码：{voicePreviewError.problem.code}</code>
                    </div>
                  ) : null}
                  {voicePreview ? (
                    <div className="player-voice-preview-result" role="status">
                      <audio
                        aria-label="玩家语音试听"
                        controls
                        src={`data:${voicePreview.mime_type};base64,${voicePreview.audio_base64}`}
                      />
                      <dl>
                        <div><dt>音色</dt><dd>{voicePreview.speaker}</dd></div>
                        <div><dt>格式</dt><dd>{voicePreview.audio_format}</dd></div>
                        <div><dt>采样率</dt><dd>{voicePreview.sample_rate} Hz</dd></div>
                        <div><dt>耗时</dt><dd>{voicePreview.elapsed_ms} ms</dd></div>
                        <div><dt>大小</dt><dd>{voicePreview.audio_byte_length} bytes</dd></div>
                      </dl>
                      <div className="player-voice-effective-delivery">
                        <strong>最终演绎</strong>
                        <code>
                          {voicePreview.effective_delivery.mood} / {voicePreview.effective_delivery.intensity} / {voicePreview.effective_delivery.pace}
                          {voicePreview.effective_delivery.instruction
                            ? ` · ${voicePreview.effective_delivery.instruction}`
                            : ""}
                        </code>
                      </div>
                      <div className="player-voice-context-texts">
                        <strong>安全 context_texts</strong>
                        {voicePreview.context_texts.map((text, index) => (
                          <code key={`${index}:${text}`}>{text}</code>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              </section>
            ) : null}

            <section aria-labelledby="player-appearance-title" className="player-form-section">
              <SectionHeading
                description="本轮仅允许选择服务端提供的不可变形象资产。"
                id="player-appearance-title"
                title="人物形象"
              />
              <div className="player-form-grid">
                <Field label="内设形象">
                  <select
                    name="appearance_id"
                    onChange={(event) => {
                      const appearance = options.appearances.find(
                        (item) => item.id === event.target.value,
                      );
                      updateDraft("appearance_id", event.target.value);
                      updateDraft("avatar_asset_id", appearance?.avatar_asset_id ?? null);
                    }}
                    value={draft.appearance_id}
                  >
                    {options.appearances.map((option) => (
                      <option key={option.id} value={option.id}>{option.label}</option>
                    ))}
                  </select>
                </Field>
                <div className="player-avatar-readonly">
                  {avatarImageUrl ? <img alt="当前玩家形象预览" src={avatarImageUrl} /> : <span>暂无形象</span>}
                  <small>资产 ID：{draft.avatar_asset_id ?? "系统默认"}</small>
                </div>
              </div>
            </section>

            {profile?.status === "published" ? (
              <section aria-labelledby="player-presentation-title" className="player-form-section">
                <SectionHeading
                  description="推荐状态会影响 C 端内容运营展示。"
                  id="player-presentation-title"
                  title="发布展示"
                />
                <label className="player-featured-control">
                  <input
                    checked={draft.featured}
                    name="featured"
                    onChange={(event) => updateDraft("featured", event.target.checked)}
                    type="checkbox"
                  />
                  <span>
                    <strong>设为推荐玩家</strong>
                    <small>归档时推荐状态会自动清除。</small>
                  </span>
                </label>
              </section>
            ) : null}
          </fieldset>

          {formErrors.form ? <p className="player-form-summary-error" role="alert">{formErrors.form}</p> : null}
          <div className="player-editor-save-bar">
            {canEdit ? (
              <button
                className="admin-primary-button"
                disabled={pendingAction !== null || voicePreviewPending}
                type="submit"
              >
                {pendingAction === "save"
                  ? "正在保存..."
                  : isNew
                    ? "保存草稿"
                    : "保存修改"}
              </button>
            ) : (
              <span>当前权限或生命周期不允许编辑。</span>
            )}
          </div>
        </div>

        <aside aria-label="玩家内容预览" className="player-editor-preview-column">
          <div className="player-preview-card">
            <span className="player-preview-avatar">
              {avatarImageUrl ? <img alt="" src={avatarImageUrl} /> : draft.display_name.charAt(0) || "?"}
            </span>
            <span className="page-kicker">PLAYER PREVIEW</span>
            <h2>{draft.display_name.trim() || "未命名玩家"}</h2>
            <p>{draft.short_description.trim() || "尚未填写一句话简介。"}</p>
            <dl>
              <div><dt>模型</dt><dd>{draft.model || "未选择"}</dd></div>
              <div><dt>性格</dt><dd>{optionLabel(options.personalities, draft.personality_id)}</dd></div>
              <div><dt>策略</dt><dd>{optionLabel(options.strategies, draft.strategy_profile)}</dd></div>
              {hasVoiceConfig ? (
                <div>
                  <dt>语音</dt>
                  <dd>
                    {draft.voice_enabled === false
                      ? "关闭"
                      : draft.tts_speaker || "继承全局音色"}
                  </dd>
                </div>
              ) : null}
            </dl>
            <div className="player-preview-tags">
              {draft.tags.length > 0
                ? draft.tags.map((tag) => <span key={tag}>{tag}</span>)
                : <small>暂无标签</small>}
            </div>
          </div>

          {profile ? (
            <section className="player-lifecycle-panel" aria-labelledby="player-lifecycle-title">
              <h2 id="player-lifecycle-title">生命周期</h2>
              <dl>
                <div><dt>创建时间</dt><dd>{formatDateTime(profile.created_at)}</dd></div>
                <div><dt>更新时间</dt><dd>{formatDateTime(profile.updated_at)}</dd></div>
                <div><dt>发布操作人</dt><dd>{profile.published_by ?? "尚未发布"}</dd></div>
                <div><dt>更新操作人</dt><dd>{profile.updated_by ?? "系统"}</dd></div>
              </dl>
              <div className="player-lifecycle-actions">
                {profile.status === "draft" && canPublish ? (
                  <button
                    disabled={isDirty}
                    onClick={() => setTransitionAction("publish")}
                    title={isDirty ? "请先保存修改" : undefined}
                    type="button"
                  >
                    发布
                  </button>
                ) : null}
                {profile.status === "published" && canArchive ? (
                  <button
                    className="is-danger"
                    disabled={isDirty}
                    onClick={() => setTransitionAction("archive")}
                    title={isDirty ? "请先保存修改" : undefined}
                    type="button"
                  >
                    归档
                  </button>
                ) : null}
                {profile.status === "archived" && canArchive ? (
                  <button
                    disabled={isDirty}
                    onClick={() => setTransitionAction("restore")}
                    title={isDirty ? "请先保存修改" : undefined}
                    type="button"
                  >
                    恢复发布
                  </button>
                ) : null}
              </div>
              {isDirty ? (
                <p className="player-lifecycle-save-hint" role="status">
                  请先保存修改，再执行生命周期操作。
                </p>
              ) : null}
            </section>
          ) : null}
        </aside>
      </form>

      {transitionAction ? (
        <PlayerTransitionDialog
          actionLabel={TRANSITION_COPY[transitionAction].actionLabel}
          description={TRANSITION_COPY[transitionAction].description}
          error={transitionError}
          key={transitionAction}
          onClose={() => {
            setTransitionAction(null);
            setTransitionError(null);
          }}
          onConfirm={(reason) => void confirmTransition(reason)}
          pending={pendingAction === transitionAction}
          title={TRANSITION_COPY[transitionAction].title}
        />
      ) : null}

      {blocker.state === "blocked" ? (
        <div className="player-dialog-backdrop">
          <div
            aria-modal="true"
            className="player-transition-dialog"
            role="alertdialog"
            aria-labelledby="unsaved-player-title"
          >
            <h2 id="unsaved-player-title">放弃未保存的修改？</h2>
            <p>离开后，当前表单中的修改不会保留。</p>
            <div className="player-dialog-actions">
              <button autoFocus onClick={() => blocker.reset()} type="button">继续编辑</button>
              <button
                className="admin-danger-button"
                onClick={() => {
                  allowNavigation.current = true;
                  blocker.proceed();
                }}
                type="button"
              >
                放弃并离开
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );

  function TendencyField({
    field,
    label,
  }: {
    field:
      | "bluffing_tendency"
      | "leadership_tendency"
      | "risk_tolerance"
      | "talkativeness"
      | "trust_tendency";
    label: string;
  }) {
    return (
      <Field label={label} error={formErrors[field]}>
        <input
          aria-invalid={Boolean(formErrors[field])}
          inputMode="numeric"
          max={5}
          min={1}
          name={field}
          onChange={(event) =>
            updateDraft(
              field,
              event.target.value === "" ? Number.NaN : Number(event.target.value),
            )
          }
          step={1}
          type="number"
          value={Number.isFinite(draft[field]) ? draft[field] : ""}
        />
      </Field>
    );
  }
}

function TtsSpeakerField({
  error,
  isError,
  isPending,
  onChange,
  onRetry,
  options,
  value,
}: {
  error?: string;
  isError: boolean;
  isPending: boolean;
  onChange: (value: string | null) => void;
  onRetry: () => void;
  options: PlayerTtsSpeakerOption[];
  value: string | null;
}) {
  const generatedId = useId();
  const labelId = `${generatedId}-label`;
  const valueId = `${generatedId}-value`;
  const helpId = `${generatedId}-help`;
  const errorId = `${generatedId}-error`;
  const listboxId = `${generatedId}-listbox`;
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const optionRefs = useRef<Array<HTMLDivElement | null>>([]);
  const [isOpen, setIsOpen] = useState(false);
  const selected = options.find((option) => option.voice_type === value);
  const legacyOption = value && !selected
    ? { voice_type: value, name: "当前已保存（不在可用列表）" }
    : null;
  const displayedOptions = [
    { voice_type: "", name: "继承全局玩家音色" },
    ...(legacyOption ? [legacyOption] : []),
    ...options,
  ];
  const selectedIndex = Math.max(
    0,
    displayedOptions.findIndex((option) => option.voice_type === (value ?? "")),
  );
  const [activeIndex, setActiveIndex] = useState(selectedIndex);

  useEffect(() => {
    if (!isOpen) {
      return undefined;
    }
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () =>
      document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, [isOpen]);

  useEffect(() => {
    if (isOpen) {
      optionRefs.current[activeIndex]?.focus();
    }
  }, [activeIndex, isOpen]);

  function openList(direction: "first" | "last" | "selected" = "selected") {
    setActiveIndex(
      direction === "first"
        ? 0
        : direction === "last"
          ? displayedOptions.length - 1
          : selectedIndex,
    );
    setIsOpen(true);
  }

  function selectOption(option: PlayerTtsSpeakerOption) {
    onChange(option.voice_type || null);
    setIsOpen(false);
    triggerRef.current?.focus();
  }

  function handleOptionKeyDown(
    event: KeyboardEvent<HTMLDivElement>,
    index: number,
  ) {
    let nextIndex = index;
    if (event.key === "ArrowDown") {
      nextIndex = Math.min(displayedOptions.length - 1, index + 1);
    } else if (event.key === "ArrowUp") {
      nextIndex = Math.max(0, index - 1);
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = displayedOptions.length - 1;
    } else if (event.key === "Escape") {
      event.preventDefault();
      setIsOpen(false);
      triggerRef.current?.focus();
      return;
    } else {
      return;
    }
    event.preventDefault();
    setActiveIndex(nextIndex);
  }

  const selectedName = selected?.name ?? legacyOption?.name ?? "继承全局玩家音色";
  return (
    <div
      className="player-form-field player-speaker-field is-wide"
      ref={containerRef}
    >
      <span id={labelId}>玩家音色</span>
      <div className="player-speaker-select">
        <button
          aria-controls={listboxId}
          aria-describedby={[helpId, error ? errorId : null]
            .filter(Boolean)
            .join(" ")}
          aria-expanded={isOpen}
          aria-haspopup="listbox"
          aria-invalid={Boolean(error)}
          aria-labelledby={`${labelId} ${valueId}`}
          className="player-speaker-trigger"
          onClick={() => (isOpen ? setIsOpen(false) : openList())}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              openList(event.key === "ArrowDown" ? "first" : "last");
            }
          }}
          ref={triggerRef}
          role="combobox"
          type="button"
        >
          <span className="player-speaker-value" id={valueId}>
            <code>{value || "继承全局"}</code>
            <span>{selectedName}</span>
          </span>
          <span aria-hidden="true" className="player-speaker-chevron">
            ⌄
          </span>
        </button>
        {isOpen ? (
          <div className="player-speaker-menu" id={listboxId} role="listbox">
            <div aria-hidden="true" className="player-speaker-menu-header">
              <span>voice_type</span>
              <span>音色名称</span>
            </div>
            {displayedOptions.map((option, index) => (
              <div
                aria-label={`${option.voice_type || "继承全局"} ${option.name}`}
                aria-selected={option.voice_type === (value ?? "")}
                className="player-speaker-option"
                key={option.voice_type || "inherit-global"}
                onClick={() => selectOption(option)}
                onFocus={() => setActiveIndex(index)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    selectOption(option);
                    return;
                  }
                  handleOptionKeyDown(event, index);
                }}
                ref={(node) => {
                  optionRefs.current[index] = node;
                }}
                role="option"
                tabIndex={activeIndex === index ? 0 : -1}
              >
                <code>{option.voice_type || "继承全局"}</code>
                <span>{option.name}</span>
              </div>
            ))}
            {isPending ? (
              <div className="player-speaker-menu-status" role="status">
                正在读取火山引擎音色列表…
              </div>
            ) : null}
            {isError ? (
              <div className="player-speaker-menu-status is-error" role="alert">
                <span>音色列表暂时读取失败。</span>
                <button onClick={onRetry} type="button">
                  重试
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
      <small id={helpId}>
        仅列出当前 seed-tts-2.0
        双向流兼容音色；留空表示继承全局 player_speaker。
      </small>
      {error ? (
        <small className="player-field-error" id={errorId} role="alert">
          {error}
        </small>
      ) : null}
    </div>
  );
}

function Field({
  children,
  className = "",
  error,
  help,
  label,
  required = false,
}: {
  children: ReactNode;
  className?: string;
  error?: string;
  help?: string;
  label: string;
  required?: boolean;
}) {
  const generatedId = useId();
  const helpId = `${generatedId}-help`;
  const errorId = `${generatedId}-error`;
  const describedBy = [help ? helpId : null, error ? errorId : null]
    .filter(Boolean)
    .join(" ");
  const control = isValidElement<Record<string, unknown>>(children)
    ? cloneElement(children, {
        "aria-describedby": describedBy || undefined,
        "aria-errormessage": error ? errorId : undefined,
      })
    : children;
  return (
    <label className={`player-form-field ${className}`}>
      <span>{label}{required ? <strong aria-hidden="true"> *</strong> : null}</span>
      {control}
      {help ? <small id={helpId}>{help}</small> : null}
      {error ? <small className="player-field-error" id={errorId} role="alert">{error}</small> : null}
    </label>
  );
}

function SectionHeading({
  description,
  id,
  title,
}: {
  description: string;
  id: string;
  title: string;
}) {
  return (
    <header className="player-form-section-heading">
      <h2 id={id}>{title}</h2>
      <p>{description}</p>
    </header>
  );
}

function EditorLoading() {
  return (
    <div aria-live="polite" className="route-loading" role="status">
      <span />
      正在读取玩家资料...
    </div>
  );
}

function EditorLoadError({
  description,
  error,
  onRetry,
}: {
  description: string;
  error: Error;
  onRetry: () => unknown;
}) {
  return (
    <div className="admin-page player-editor-load-error" role="alert">
      <span className="page-kicker">PLAYER PROFILE</span>
      <h1>无法打开玩家资料</h1>
      <p>{description}</p>
      <small>{error.message}</small>
      <div>
        <Link to="/content/players">返回玩家内容库</Link>
        <button onClick={() => void onRetry()} type="button">重新加载</button>
      </div>
    </div>
  );
}

function optionLabel(options: Array<{ id: string; label: string }>, id: string) {
  return options.find((option) => option.id === id)?.label ?? id;
}

const PLAYER_DELIVERY_MOOD_OPTIONS = [
  { id: "neutral", label: "中性" },
  { id: "restrained", label: "克制" },
  { id: "calm", label: "平静" },
  { id: "confident", label: "笃定" },
  { id: "skeptical", label: "质疑" },
  { id: "tense", label: "紧张" },
  { id: "frustrated", label: "挫败" },
  { id: "urgent", label: "急迫" },
  { id: "sad", label: "低落" },
  { id: "excited", label: "兴奋" },
  { id: "playful", label: "轻松" },
] as const;

const PLAYER_DELIVERY_INTENSITY_OPTIONS = [
  { id: "low", label: "低" },
  { id: "medium", label: "中" },
  { id: "high", label: "高" },
] as const;

const PLAYER_DELIVERY_PACE_OPTIONS = [
  { id: "slow", label: "慢" },
  { id: "natural", label: "自然" },
  { id: "fast", label: "快" },
] as const;

function voiceDeliveryOptions(
  options: ReadonlyArray<{ id: string; label: string }>,
  current: string | null | undefined,
  emptyLabel: string,
) {
  const hasCurrent = current
    ? options.some((option) => option.id === current)
    : true;
  return (
    <>
      <option value="">{emptyLabel}</option>
      {!hasCurrent && current ? (
        <option value={current}>当前值 · {current}</option>
      ) : null}
      {options.map((option) => (
        <option key={option.id} value={option.id}>
          {option.label} · {option.id}
        </option>
      ))}
    </>
  );
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function focusFirstInvalidField(errors: PlayerProfileFormErrors) {
  const firstField = Object.keys(errors).find((field) => field !== "form");
  if (!firstField) {
    return;
  }
  requestAnimationFrame(() => {
    document.querySelector<HTMLElement>(`[name="${firstField}"]`)?.focus();
  });
}
