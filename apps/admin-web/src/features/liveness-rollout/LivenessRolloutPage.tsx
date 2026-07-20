import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useMemo, useState } from "react";

import { isAdminApiError } from "@/api/problem-details";
import { hasAdminPermission } from "@/features/auth/permissions";
import { useAdminSession } from "@/features/auth/session-context";
import {
  getLivenessRollout,
  updateLivenessRollout,
} from "@/features/liveness-rollout/api";
import { previewLivenessRollout } from "@/features/liveness-rollout/preview";
import type {
  LivenessRolloutConfig,
  LivenessRolloutUpdate,
} from "@/features/liveness-rollout/types";

const QUERY_KEY = ["admin", "liveness-rollout"] as const;
const EXPERIMENT_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/;

export default function LivenessRolloutPage() {
  const { runtimeMode, session } = useAdminSession();
  const canManage =
    runtimeMode === "authenticated" &&
    hasAdminPermission(session?.permissions ?? [], "settings.manage");
  const rollout = useQuery({
    queryKey: QUERY_KEY,
    queryFn: ({ signal }) =>
      runtimeMode === "preview"
        ? Promise.resolve(previewLivenessRollout)
        : getLivenessRollout(signal),
    staleTime: 15_000,
  });
  if (rollout.isPending) {
    return <div className="dashboard-page-state">正在读取灰度配置...</div>;
  }
  if (rollout.isError || !rollout.data) {
    return <div className="dashboard-page-state" role="alert">灰度配置暂时不可用。</div>;
  }
  return (
    <LivenessRolloutEditor
      canManage={canManage}
      csrfToken={session?.csrf_token ?? ""}
      data={rollout.data}
    />
  );
}

function LivenessRolloutEditor({
  canManage,
  csrfToken,
  data,
}: {
  canManage: boolean;
  csrfToken: string;
  data: LivenessRolloutConfig;
}) {
  const queryClient = useQueryClient();
  const [experienceRevision, setExperienceRevision] = useState(data.experience_revision);
  const [experimentId, setExperimentId] = useState(data.experiment_id);
  const [treatmentPercent, setTreatmentPercent] = useState(data.treatment_percent);
  const [changeReason, setChangeReason] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const [savedMessage, setSavedMessage] = useState<string | null>(null);
  const mutation = useMutation({
    mutationFn: (input: LivenessRolloutUpdate) =>
      updateLivenessRollout(input, csrfToken),
    onSuccess: (saved) => {
      setSavedMessage(`灰度配置已保存为修订 ${saved.revision}，后续新对局开始生效。`);
      queryClient.setQueryData(QUERY_KEY, saved);
    },
  });
  const selectedExperience = useMemo(
    () =>
      data.available_experiences.find(
        (item) => item.revision === experienceRevision,
      ) ?? null,
    [data.available_experiences, experienceRevision],
  );

  function submit(event: FormEvent) {
    event.preventDefault();
    setSavedMessage(null);
    const reason = changeReason.trim();
    const id = experimentId.trim();
    if (!EXPERIMENT_ID.test(id)) {
      setValidationError("实验标识只能使用字母、数字、点、下划线、冒号或短横线，最长 64 位。");
      return;
    }
    if (reason.length < 3) {
      setValidationError("请填写至少 3 个字的变更原因，便于审计和回溯。");
      return;
    }
    setValidationError(null);
    mutation.mutate({
      expected_revision: data.revision,
      experience_revision: experienceRevision,
      experiment_id: id,
      treatment_percent: treatmentPercent,
      change_reason: reason,
    });
  }

  return (
    <div className="admin-page liveness-rollout-page">
      <header className="page-heading liveness-rollout-heading">
        <div>
          <span className="page-kicker">EXPERIENCE / ROLLOUT</span>
          <h1>灰度控制</h1>
          <p>控制活人感体验版本与新对局分流比例，并保留每次变更的修订和审计记录。</p>
        </div>
        <div className="liveness-rollout-status">
          <span>{data.source === "database" ? `配置修订 ${data.revision}` : "环境变量默认值"}</span>
          <strong>{data.treatment_percent}% 灰度中</strong>
        </div>
      </header>

      <section className="liveness-rollout-safety" aria-label="生效范围">
        <strong>只影响保存后创建的新对局</strong>
        <span>进行中对局、恢复运行和 Replay 继续使用各自开局时锁定的版本，不会被中途切换。</span>
      </section>

      <div className="liveness-rollout-layout">
        <form className="liveness-rollout-form" onSubmit={submit}>
          <div className="liveness-rollout-form-heading">
            <div><span>当前控制项</span><h2>新对局分流</h2></div>
            <small>{data.updated_at ? `最近保存 ${formatTime(data.updated_at)}` : "尚未写入后台配置"}</small>
          </div>

          <label className="liveness-rollout-field">
            <span>候选体验版本</span>
            <select
              disabled={!canManage || mutation.isPending}
              onChange={(event) => setExperienceRevision(event.target.value)}
              value={experienceRevision}
            >
              {data.available_experiences.map((option) => (
                <option key={option.revision} value={option.revision}>
                  {option.label} · {option.revision}
                </option>
              ))}
            </select>
            <small>{selectedExperience?.description}</small>
          </label>

          <label className="liveness-rollout-field">
            <span>实验标识</span>
            <input
              disabled={!canManage || mutation.isPending}
              maxLength={64}
              onChange={(event) => setExperimentId(event.target.value)}
              spellCheck={false}
              value={experimentId}
            />
            <small>更换标识会重新计算稳定分桶；同一标识下，同一对局的分组保持稳定。</small>
          </label>

          <fieldset className="liveness-rollout-percent" disabled={!canManage || mutation.isPending}>
            <legend>放量比例</legend>
            <div className="liveness-rollout-percent-value">
              <strong>{treatmentPercent}%</strong>
              <span>候选版本</span>
            </div>
            <input
              aria-label="放量比例"
              max={100}
              min={0}
              onChange={(event) => setTreatmentPercent(Number(event.target.value))}
              step={1}
              type="range"
              value={treatmentPercent}
            />
            <div className="liveness-rollout-distribution" aria-label={`对照组 ${100 - treatmentPercent}%，候选组 ${treatmentPercent}%`}>
              <span style={{ width: `${100 - treatmentPercent}%` }}>对照 {100 - treatmentPercent}%</span>
              <b style={{ width: `${treatmentPercent}%` }}>{treatmentPercent > 8 ? `候选 ${treatmentPercent}%` : ""}</b>
            </div>
            <div className="liveness-rollout-presets">
              {[0, 10, 25, 50, 100].map((value) => (
                <button
                  className={treatmentPercent === value ? "is-active" : ""}
                  key={value}
                  onClick={() => setTreatmentPercent(value)}
                  type="button"
                >
                  {value}%
                </button>
              ))}
            </div>
          </fieldset>

          <label className="liveness-rollout-field">
            <span>变更原因</span>
            <textarea
              disabled={!canManage || mutation.isPending}
              maxLength={500}
              onChange={(event) => setChangeReason(event.target.value)}
              placeholder="例如：评审达标，先扩大到 25% 观察线上重写率与首句延迟"
              rows={3}
              value={changeReason}
            />
          </label>

          {validationError ? <p className="liveness-rollout-error" role="alert">{validationError}</p> : null}
          {mutation.isError ? (
            <p className="liveness-rollout-error" role="alert">
              {isAdminApiError(mutation.error)
                ? mutation.error.problem.detail
                : "灰度配置保存失败。"}
            </p>
          ) : null}
          {savedMessage ? <p className="liveness-rollout-success" role="status">{savedMessage}</p> : null}

          <div className="liveness-rollout-actions">
            {canManage ? (
              <button className="admin-primary-button" disabled={mutation.isPending} type="submit">
                {mutation.isPending ? "保存中" : "保存灰度配置"}
              </button>
            ) : (
              <span>当前账号只有查看权限，需 settings.manage 才能修改。</span>
            )}
          </div>
        </form>

        <aside className="liveness-rollout-explainer">
          <span>版本差异</span>
          <h2>{selectedExperience?.label ?? experienceRevision}</h2>
          <article>
            <b>对照组 · {100 - treatmentPercent}%</b>
            <p>{selectedExperience?.control_summary}</p>
          </article>
          <article className="is-treatment">
            <b>候选组 · {treatmentPercent}%</b>
            <p>{selectedExperience?.treatment_summary}</p>
          </article>
          <dl>
            <div><dt>版本</dt><dd>{experienceRevision}</dd></div>
            <div><dt>实验</dt><dd>{experimentId}</dd></div>
            <div><dt>生效对象</dt><dd>新创建对局</dd></div>
          </dl>
        </aside>
      </div>
    </div>
  );
}

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
