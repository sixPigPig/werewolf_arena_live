import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  cloneElement,
  type FormEvent,
  isValidElement,
  type ReactNode,
  useCallback,
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
  PlayerProfileEditableFields,
  PlayerProfileOptions,
  PlayerProfileStatus,
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
    />
  );
}

function PlayerProfileEditor({
  initialProfile,
  isNew,
  onReload,
  options,
  repository,
}: {
  initialProfile: AdminPlayerProfile | null;
  isNew: boolean;
  onReload: () => void;
  options: PlayerProfileOptions;
  repository: ReturnType<typeof usePlayerProfileRepository>;
}) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { session } = useAdminSession();
  const permissions = session?.permissions ?? [];
  const canWrite = hasAdminPermission(permissions, "players.write");
  const canPublish = hasAdminPermission(permissions, "players.publish");
  const canArchive = hasAdminPermission(permissions, "players.archive");
  const defaults = {
    model: options.models[0]?.id ?? "",
    personality_id: options.personalities[0]?.id ?? "balanced",
    strategy_profile: options.strategies[0]?.id ?? "balanced",
    appearance_id: options.appearances[0]?.id ?? "default",
    avatar_asset_id: options.appearances[0]?.avatar_asset_id ?? null,
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
    "save" | TransitionAction | null
  >(null);
  const [transitionAction, setTransitionAction] =
    useState<TransitionAction | null>(null);
  const [transitionError, setTransitionError] = useState<string | null>(null);
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

  function updateDraft<Key extends keyof PlayerProfileEditableFields>(
    field: Key,
    value: PlayerProfileEditableFields[Key],
  ) {
    setDraft((current) => ({ ...current, [field]: value }));
    setFormErrors((current) => ({ ...current, [field]: undefined, form: undefined }));
    setSuccessMessage(null);
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
          <fieldset disabled={!canEdit || pendingAction !== null}>
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
                disabled={pendingAction !== null}
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
