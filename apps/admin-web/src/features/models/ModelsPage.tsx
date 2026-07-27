import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Checkbox from "antd/es/checkbox";
import InputNumber from "antd/es/input-number";
import Select from "antd/es/select";
import {
  cloneElement,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactElement,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";

import { isAdminApiError } from "@/api/problem-details";
import { hasAdminPermission } from "@/features/auth/permissions";
import { useAdminSession } from "@/features/auth/session-context";
import {
  listAdminModels,
  syncAgentPlanModels,
  updateAdminModel,
} from "@/features/models/api";
import { previewModelCatalog } from "@/features/models/preview";
import { adminModelKeys } from "@/features/models/query-keys";
import type {
  AdminModel,
  AdminModelSource,
  ModelConfigurationInput,
  ThinkingMode,
} from "@/features/models/types";

type ConfigurationMutation = {
  model: AdminModel;
  input: ModelConfigurationInput;
};

export default function ModelsPage() {
  const queryClient = useQueryClient();
  const { runtimeMode, session } = useAdminSession();
  const canManage = hasAdminPermission(session?.permissions ?? [], "settings.manage");
  const catalogQuery = useQuery({
    queryKey: adminModelKeys.catalog,
    queryFn: ({ signal }) =>
      runtimeMode === "preview"
        ? Promise.resolve(previewModelCatalog)
        : listAdminModels(signal),
    staleTime: 15_000,
  });
  const syncMutation = useMutation({
    mutationFn: () => syncAgentPlanModels(session?.csrf_token ?? ""),
    onSuccess: (catalog) => queryClient.setQueryData(adminModelKeys.catalog, catalog),
  });
  const configurationMutation = useMutation({
    mutationFn: ({ model, input }: ConfigurationMutation) =>
      updateAdminModel(
        model.provider,
        model.model_id,
        input,
        session?.csrf_token ?? "",
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: adminModelKeys.all }),
  });
  const catalog = catalogQuery.data;
  const agentModels = catalog?.models.filter((model) => model.provider === "agent_plan") ?? [];
  const deepseekModels = catalog?.models.filter((model) => model.provider === "deepseek") ?? [];

  return (
    <div className="admin-page models-page">
      <header className="page-heading models-heading">
        <div>
          <span className="page-kicker">MODEL CATALOG</span>
          <h1>模型管理</h1>
          <p>同步可用模型，控制虚拟玩家可选范围，并按模型配置推理与采样参数。</p>
        </div>
        <div className="models-heading-actions">
          <button
            className="admin-secondary-button"
            disabled={catalogQuery.isFetching}
            onClick={() => void catalogQuery.refetch()}
            type="button"
          >
            {catalogQuery.isFetching ? "刷新中" : "刷新页面"}
          </button>
          {canManage && runtimeMode !== "preview" ? (
            <button
              className="admin-primary-button"
              disabled={syncMutation.isPending}
              onClick={() => syncMutation.mutate()}
              type="button"
            >
              {syncMutation.isPending ? "同步中" : "更新 Agent Plan 模型"}
            </button>
          ) : null}
        </div>
      </header>

      <div className="models-safety-note">
        <strong>生效规则</strong>
        <span>新发现模型默认关闭；被虚拟玩家使用的模型不能直接停用；运行时输出上限始终取游戏预算与模型配置中的较小值。</span>
      </div>

      {catalog ? <ModelSources sources={catalog.sources} /> : null}
      {catalogQuery.isPending ? (
        <div className="dashboard-page-state">正在读取模型目录...</div>
      ) : null}
      {catalogQuery.isError ? (
        <ModelError error={catalogQuery.error} fallback="模型目录暂时不可用。" />
      ) : null}
      {syncMutation.isError ? (
        <ModelError error={syncMutation.error} fallback="Agent Plan 模型同步失败。" />
      ) : null}
      {configurationMutation.isError ? (
        <ModelError error={configurationMutation.error} fallback="模型配置保存失败。" />
      ) : null}

      {catalog ? (
        <div className="model-provider-sections">
          <ModelProviderSection
            canManage={canManage && runtimeMode !== "preview"}
            models={agentModels}
            onSave={(model, input) => configurationMutation.mutate({ model, input })}
            pendingKey={configurationMutation.isPending ? mutationKey(configurationMutation.variables?.model) : null}
            subtitle="模型清单由 Agent Plan 控制面手动同步；套餐新增项不会自动进入玩家可选列表。"
            title="火山方舟 Agent Plan"
          />
          <ModelProviderSection
            canManage={canManage && runtimeMode !== "preview"}
            models={deepseekModels}
            onSave={(model, input) => configurationMutation.mutate({ model, input })}
            pendingKey={configurationMutation.isPending ? mutationKey(configurationMutation.variables?.model) : null}
            subtitle="每次打开本页都会通过 DeepSeek 官方 /models 接口刷新，无需单独更新。"
            title="DeepSeek 官方 API"
          />
        </div>
      ) : null}
    </div>
  );
}

function ModelSources({ sources }: { sources: AdminModelSource[] }) {
  return (
    <section aria-label="模型来源状态" className="model-source-grid">
      {sources.map((source) => (
        <article className="model-source-card" data-status={source.status} key={source.provider}>
          <div>
            <span>{source.refresh_mode === "automatic" ? "官方实时" : "手动同步"}</span>
            <strong>{source.label}</strong>
          </div>
          <b>{source.model_count} 个当前模型</b>
          <small>
            {source.error
              ? source.error
              : source.last_synced_at
                ? `最近同步 ${formatDateTime(source.last_synced_at)}`
                : "尚未完成远端同步，当前展示环境配置。"}
          </small>
          <a href={source.docs_url} rel="noreferrer" target="_blank">查看官方文档</a>
        </article>
      ))}
    </section>
  );
}

function ModelProviderSection({
  canManage,
  models,
  onSave,
  pendingKey,
  subtitle,
  title,
}: {
  canManage: boolean;
  models: AdminModel[];
  onSave: (model: AdminModel, input: ModelConfigurationInput) => void;
  pendingKey: string | null;
  subtitle: string;
  title: string;
}) {
  return (
    <section className="model-provider-panel">
      <div className="model-provider-heading">
        <div><h2>{title}</h2><p>{subtitle}</p></div>
        <span>{models.filter((model) => model.available && model.enabled).length} / {models.filter((model) => model.available).length} 已启用</span>
      </div>
      {models.length === 0 ? (
        <div className="game-empty-state"><span aria-hidden="true">模</span><h3>没有模型记录</h3><p>检查凭证或执行一次模型同步。</p></div>
      ) : (
        <div className="model-card-list">
          {models.map((model) => (
            <ModelCard
              canManage={canManage}
              key={`${model.provider}:${model.model_id}:${model.updated_at}`}
              model={model}
              onSave={onSave}
              pending={pendingKey === mutationKey(model)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function ModelCard({
  canManage,
  model,
  onSave,
  pending,
}: {
  canManage: boolean;
  model: AdminModel;
  onSave: (model: AdminModel, input: ModelConfigurationInput) => void;
  pending: boolean;
}) {
  const [expanded, setExpanded] = useState(model.is_default);
  return (
    <details
      className="model-card"
      onToggle={(event) => setExpanded(event.currentTarget.open)}
      open={expanded}
    >
      <summary>
        <span className="model-card-identity">
          <strong>{model.display_name}</strong>
          <code>{model.model_id}</code>
        </span>
        <span className="model-card-badges">
          {model.is_default ? <b data-tone="accent">默认</b> : null}
          {model.selected_by_source ? <b data-tone="info">套餐选中</b> : null}
          {!model.available ? <b data-tone="muted">已下线</b> : null}
          <b data-tone={model.enabled ? "success" : "muted"}>{model.enabled ? "已启用" : "未启用"}</b>
          <small>{model.assigned_profile_count} 位玩家</small>
        </span>
      </summary>
      <div className="model-card-body">
        <p>{model.description ?? "该来源未提供模型描述。"}</p>
        {model.source_model_id && model.source_model_id !== model.model_id ? (
          <small>来源 ID：<code>{model.source_model_id}</code></small>
        ) : null}
        <ModelConfigurationForm
          canManage={canManage}
          model={model}
          onSubmit={(input) => onSave(model, input)}
          pending={pending}
        />
      </div>
    </details>
  );
}

function ModelConfigurationForm({
  canManage,
  model,
  onSubmit,
  pending,
}: {
  canManage: boolean;
  model: AdminModel;
  onSubmit: (input: ModelConfigurationInput) => void;
  pending: boolean;
}) {
  const [thinking, setThinking] = useState<ThinkingMode>(model.parameters.thinking);
  const [reasoningEffort, setReasoningEffort] = useState(
    model.parameters.thinking === "disabled"
      ? ""
      : model.parameters.reasoning_effort ?? "",
  );
  const [validationError, setValidationError] = useState<string | null>(null);
  const samplingDisabled = model.provider === "deepseek" && thinking !== "disabled";
  const reasoningEffortDisabled =
    thinking === "disabled" || model.reasoning_effort_options.length === 0;
  const storedReasoningConflict =
    model.parameters.thinking === "disabled" &&
    Boolean(model.parameters.reasoning_effort);

  function handleThinkingChange(nextThinking: ThinkingMode) {
    setThinking(nextThinking);
    setValidationError(null);
    if (nextThinking === "disabled") setReasoningEffort("");
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (thinking === "disabled" && reasoningEffort) {
      setValidationError("关闭 Thinking 时不能同时设置 Reasoning effort。");
      return;
    }
    setValidationError(null);
    const form = new FormData(event.currentTarget);
    onSubmit({
      enabled: model.is_default || form.get("enabled") === "on",
      is_default: model.is_default || form.get("is_default") === "on",
      parameters: {
        thinking,
        reasoning_effort: reasoningEffort || null,
        temperature: samplingDisabled ? null : optionalNumber(form, "temperature"),
        top_p: samplingDisabled ? null : optionalNumber(form, "top_p"),
        max_tokens: optionalNumber(form, "max_tokens"),
        frequency_penalty: samplingDisabled ? null : optionalNumber(form, "frequency_penalty"),
        presence_penalty: samplingDisabled ? null : optionalNumber(form, "presence_penalty"),
      },
    });
  }

  return (
    <form className="model-configuration-form" onSubmit={handleSubmit}>
      <fieldset disabled={!canManage || !model.available || pending}>
        <legend>运行配置</legend>
        <div className="model-toggle-row">
          <Checkbox defaultChecked={model.enabled} disabled={model.is_default} name="enabled">
            允许虚拟玩家使用
          </Checkbox>
          <Checkbox defaultChecked={model.is_default} disabled={model.is_default} name="is_default">
            {model.is_default ? "当前默认模型" : "设为默认模型"}
          </Checkbox>
        </div>
        <div className="model-parameter-grid">
          <ModelParameterField
            description="控制模型是否启用深度思考或推理模式。开启后通常能提升复杂问题的推理质量，但响应会更慢，并可能消耗更多 token。"
            label="Thinking"
          >
            <Select
              aria-label="Thinking"
              disabled={!model.supports_thinking}
              onChange={(value) => handleThinkingChange(value as ThinkingMode)}
              options={[
                { label: "跟随提供方默认", value: "default" },
                { label: "开启", value: "enabled" },
                { label: "关闭", value: "disabled" },
              ]}
              value={thinking}
            />
          </ModelParameterField>
          <ModelParameterField
            description="控制模型投入的推理强度。级别越高，通常会进行更深入的分析，但响应时间和 token 消耗也可能增加。可选级别由模型提供方决定。"
            label="Reasoning effort"
          >
            <Select
              aria-label="Reasoning effort"
              disabled={reasoningEffortDisabled}
              onChange={(value) => {
                setReasoningEffort(value);
                setValidationError(null);
              }}
              options={[
                { label: "跟随提供方默认", value: "" },
                ...model.reasoning_effort_options.map((option) => ({
                  label: option,
                  value: option,
                })),
              ]}
              value={reasoningEffort}
            />
          </ModelParameterField>
          <NumberField
            defaultValue={model.parameters.max_tokens}
            description={`限制模型单次响应最多生成的 token 数。当前模型上限为 ${model.max_output_tokens_limit.toLocaleString()}；实际值还会受游戏运行预算限制。`}
            label="最大输出 tokens"
            max={model.max_output_tokens_limit}
            min={1}
            name="max_tokens"
            step={1}
          />
          <NumberField
            defaultValue={model.parameters.temperature}
            description="控制输出的随机性。值越高，回答越多样但越不可预测；值越低，回答越稳定。通常建议与 Top P 只配置一个。"
            disabled={samplingDisabled}
            label="Temperature"
            max={2}
            min={0}
            name="temperature"
            step={0.05}
          />
          <NumberField
            defaultValue={model.parameters.top_p}
            description="通过核采样限制候选词范围。值越低，模型越集中于高概率词；值越高，输出越丰富。通常建议与 Temperature 只配置一个。"
            disabled={samplingDisabled}
            label="Top P"
            max={1}
            min={0}
            name="top_p"
            step={0.05}
          />
          <NumberField
            defaultValue={model.parameters.frequency_penalty}
            description="根据词语已经出现的频率施加惩罚。正值可减少重复用词和句式，负值会增加重复倾向。"
            disabled={samplingDisabled}
            label="Frequency penalty"
            max={2}
            min={-2}
            name="frequency_penalty"
            step={0.1}
          />
          <NumberField
            defaultValue={model.parameters.presence_penalty}
            description="只要词语已经出现过就施加惩罚，而不考虑出现次数。正值会鼓励模型引入新内容，负值会鼓励延续已有内容。"
            disabled={samplingDisabled}
            label="Presence penalty"
            max={2}
            min={-2}
            name="presence_penalty"
            step={0.1}
          />
        </div>
        {thinking === "disabled" ? (
          <p className="model-parameter-note">
            {storedReasoningConflict
              ? "检测到历史冲突配置：关闭 Thinking 时 Reasoning effort 不可用，本次保存会自动清空。"
              : "关闭 Thinking 时 Reasoning effort 不可用，保存时会保持为空。"}
          </p>
        ) : model.provider === "deepseek" && samplingDisabled ? (
          <p className="model-parameter-note">DeepSeek 官方说明：思考开启（含默认值）时，Temperature、Top P 与两类 penalty 不生效，保存时会自动清空。</p>
        ) : model.provider === "agent_plan" ? (
          <p className="model-parameter-note">Temperature 与 Top P 建议只配置一个；两类 penalty 仅用于 Chat 调用，V2 Responses 请求不会发送。</p>
        ) : (
          <p className="model-parameter-note">Temperature 与 Top P 建议只配置一个；留空表示继续使用游戏动作自己的动态值。</p>
        )}
        {validationError ? <p className="game-inline-warning" role="alert">{validationError}</p> : null}
        <div className="model-form-actions">
          <a href={model.docs_url} rel="noreferrer" target="_blank">参数官方文档</a>
          {canManage ? <button className="admin-primary-button" type="submit">{pending ? "保存中" : "保存配置"}</button> : <span>只读权限</span>}
        </div>
      </fieldset>
    </form>
  );
}

function NumberField({ defaultValue, description, disabled, label, max, min, name, step }: {
  defaultValue: number | null;
  description: string;
  disabled?: boolean;
  label: string;
  max: number;
  min: number;
  name: string;
  step: number;
}) {
  return (
    <ModelParameterField description={description} label={label}>
      <InputNumber
        aria-label={label}
        defaultValue={defaultValue ?? undefined}
        disabled={disabled}
        max={max}
        min={min}
        name={name}
        placeholder="默认"
        step={step}
      />
    </ModelParameterField>
  );
}

function ModelParameterField({
  children,
  description,
  label,
}: {
  children: ReactElement<{ "aria-describedby"?: string; id?: string }>;
  description: string;
  label: string;
}) {
  const [open, setOpen] = useState(false);
  const generatedId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const controlId = `${generatedId}-control`;
  const descriptionId = `${generatedId}-description`;

  useEffect(() => {
    if (!open) return;

    function closeOnOutsideClick(event: PointerEvent) {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    }

    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }

    document.addEventListener("pointerdown", closeOnOutsideClick);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutsideClick);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  function toggleOnKeyboard(event: ReactKeyboardEvent<HTMLSpanElement>) {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setOpen((current) => !current);
    }
  }

  const describedBy = [children.props["aria-describedby"], open ? descriptionId : null]
    .filter(Boolean)
    .join(" ");
  const control = cloneElement(children, {
    "aria-describedby": describedBy || undefined,
    id: controlId,
  });

  return (
    <div className="model-parameter-field" ref={rootRef}>
      <div className="model-parameter-label">
        <label htmlFor={controlId}>{label}</label>
        <span
          aria-controls={descriptionId}
          aria-expanded={open}
          aria-label={`查看 ${label} 参数说明`}
          className="model-parameter-help"
          onClick={() => setOpen((current) => !current)}
          onKeyDown={toggleOnKeyboard}
          role="button"
          tabIndex={0}
        >
          ?
        </span>
      </div>
      {control}
      {open ? (
        <span className="model-parameter-popover" id={descriptionId} role="tooltip">
          {description}
        </span>
      ) : null}
    </div>
  );
}

function ModelError({ error, fallback }: { error: unknown; fallback: string }) {
  return <p className="game-inline-warning" role="alert">{isAdminApiError(error) ? error.problem.detail : fallback}</p>;
}

function optionalString(form: FormData, key: string) {
  const value = form.get(key);
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

function optionalNumber(form: FormData, key: string) {
  const value = optionalString(form, key);
  if (value === null) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function mutationKey(model: AdminModel | undefined) {
  return model ? `${model.provider}:${model.model_id}` : null;
}

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(new Date(value));
}
