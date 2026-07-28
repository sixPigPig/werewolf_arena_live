import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import AntApp from "antd/es/app";
import Button from "antd/es/button";
import Input from "antd/es/input";
import Select from "antd/es/select";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import { createAdminJudgeVoiceJob, getAdminJudgeVoiceJob, listAdminJudgeVoiceLines } from "@/features/voice-assets/api";
import { hasAdminPermission } from "@/features/auth/permissions";
import { useAdminSession } from "@/features/auth/session-context";
import {
  judgeVoiceListParamsFromSearch,
  setJudgeVoiceSearchValues,
} from "@/features/voice-assets/list-state";
import { adminJudgeVoiceKeys } from "@/features/voice-assets/query-keys";
import type {
  AdminJudgeVoiceLine,
  AdminJudgeVoiceList,
} from "@/features/voice-assets/types";
import { adminOperationErrorDescription } from "@/lib/admin-notification";

export default function JudgeVoiceAssetsPage() {
  const { notification } = AntApp.useApp();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const { session } = useAdminSession();
  const [jobId, setJobId] = useState<string | null>(null);
  const notifiedJobResult = useRef<string | null>(null);
  const params = judgeVoiceListParamsFromSearch(searchParams);
  const voiceQuery = useQuery({
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => listAdminJudgeVoiceLines(params, signal),
    queryKey: adminJudgeVoiceKeys.list(params),
    staleTime: 30_000,
  });
  const data = voiceQuery.data;
  const permissions = session?.permissions ?? [];
  const canGenerateMissing = hasAdminPermission(permissions, "voice.generate_missing");
  const canRegenerateAll = hasAdminPermission(permissions, "voice.regenerate_all");
  const jobQuery = useQuery({
    enabled: jobId !== null,
    queryKey: ["admin", "judge-voice-job", jobId],
    queryFn: ({ signal }) => getAdminJudgeVoiceJob(jobId!, signal),
    refetchInterval: (query) =>
      query.state.data?.status === "queued" || query.state.data?.status === "running"
        ? 1500
        : false,
  });
  const createJob = useMutation({
    mutationFn: (mode: "missing" | "all") =>
      createAdminJudgeVoiceJob(mode, session?.csrf_token ?? ""),
    onError: (error) => {
      notification.error({
        description: adminOperationErrorDescription(
          error,
          "无法创建语音生成任务，请稍后重试。",
        ),
        title: "语音生成任务创建失败",
      });
    },
    onSuccess: (job) => {
      notifiedJobResult.current = null;
      setJobId(job.id);
      notification.success({ title: "语音生成任务已创建" });
    },
  });
  useEffect(() => {
    if (jobQuery.data?.status === "completed") {
      void queryClient.invalidateQueries({ queryKey: adminJudgeVoiceKeys.all });
    }
    if (
      !jobQuery.data ||
      (jobQuery.data.status !== "completed" &&
        jobQuery.data.status !== "failed")
    ) {
      return;
    }
    const resultKey = `${jobQuery.data.id}:${jobQuery.data.status}`;
    if (notifiedJobResult.current === resultKey) {
      return;
    }
    notifiedJobResult.current = resultKey;
    if (jobQuery.data.status === "failed") {
      notification.error({
        description: jobQuery.data.error_code
          ? `错误分类：${jobQuery.data.error_code}`
          : "请稍后重新创建生成任务。",
        title: "语音生成任务失败",
      });
      return;
    }
    const description = `已生成 ${jobQuery.data.generated_count} 条，失败 ${jobQuery.data.failed_count} 条。`;
    if (jobQuery.data.failed_count > 0) {
      notification.warning({
        description,
        title: "语音生成任务已完成，但存在失败项",
      });
    } else {
      notification.success({
        description,
        title: "语音生成任务已完成",
      });
    }
  }, [jobQuery.data, notification, queryClient]);

  function updateSearch(values: Record<string, string | undefined>) {
    setSearchParams(
      setJudgeVoiceSearchValues(searchParams, { page: "1", ...values }),
    );
  }

  function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    updateSearch({ q: formValue(values, "q") });
  }

  function clearFilters() {
    setSearchParams(
      setJudgeVoiceSearchValues(searchParams, {
        page: undefined,
        q: undefined,
        category: undefined,
        availability: undefined,
      }),
    );
  }

  const hasFilters = Boolean(params.q || params.category || params.availability);

  return (
    <div className="admin-page voice-assets-page">
      <header className="page-heading voice-assets-heading">
        <div>
          <span className="page-kicker">VOICE LIBRARY</span>
          <h1>法官语音资产</h1>
          <p>核对固定法官台词的使用状态、生成覆盖率与受认证试听。</p>
        </div>
        <div className="voice-assets-heading-actions">
          <span className="page-readiness-badge">只读资产</span>
          <button
            className="admin-secondary-button"
            disabled={voiceQuery.isFetching}
            onClick={() => void voiceQuery.refetch()}
            type="button"
          >
            {voiceQuery.isFetching ? "刷新中" : "手动刷新"}
          </button>
          {canGenerateMissing ? (
            <button
              className="admin-primary-button"
              disabled={createJob.isPending}
              onClick={() => createJob.mutate("missing")}
              type="button"
            >
              生成缺失语音
            </button>
          ) : null}
          {canRegenerateAll ? (
            <button
              className="admin-secondary-button"
              disabled={createJob.isPending}
              onClick={() => createJob.mutate("all")}
              type="button"
            >
              重新生成全部
            </button>
          ) : null}
        </div>
      </header>

      <p className="voice-assets-storage-note">
        {data?.storage_mode === "database"
          ? "当前读取 PostgreSQL 独立语音资产存储；旧静态文件仅作为回滚输入保留。本页不会自动生成、覆盖或删除语音。"
          : "当前仍从旧静态目录双读；完成幂等导入后会自动切换 PostgreSQL。本页不会自动生成、覆盖或删除语音。"}
      </p>
      <p className="voice-assets-storage-note">
        本页只管理法官固定台词资产。玩家音色与基础演绎在玩家档案中配置，两者不会自动联动；修改任一配置都不会改写运行中对局或历史 Replay。
      </p>

      {jobQuery.data ? (
        <section
          aria-label="语音生成任务"
          aria-live="polite"
          className="voice-assets-storage-note"
          role="status"
        >
          <strong>生成任务：{jobStatusLabel(jobQuery.data.status)}</strong>
          <span>
            {jobQuery.data.processed_count} / {jobQuery.data.total_count} · 已生成 {jobQuery.data.generated_count} · 失败 {jobQuery.data.failed_count}
          </span>
          {jobQuery.data.error_code ? <small>错误分类：{jobQuery.data.error_code}</small> : null}
        </section>
      ) : null}

      {data ? <VoiceCoverage data={data} /> : <VoiceCoverageLoading />}

      <section aria-label="语音资产筛选" className="game-filter-panel voice-filter-panel">
        <form onSubmit={handleSearch} role="search">
          <label className="game-filter-wide">
            <span>搜索台词</span>
            <Input
              aria-label="搜索台词"
              defaultValue={params.q ?? ""}
              key={`q-${params.q ?? ""}`}
              name="q"
              placeholder="台词 ID 或内容"
              type="search"
            />
          </label>
          <label>
            <span>文件状态</span>
            <Select
              aria-label="文件状态"
              onChange={(value) => updateSearch({ availability: value })}
              options={[
                { label: "全部状态", value: "" },
                { label: "已生成", value: "available" },
                { label: "缺失", value: "missing" },
              ]}
              value={params.availability ?? ""}
            />
          </label>
          <label>
            <span>台词分类</span>
            <Select
              aria-label="台词分类"
              onChange={(value) => updateSearch({ category: value })}
              options={[
                { label: "全部分类", value: "" },
                ...(data?.categories ?? []).map((category) => ({
                  label: `${category.name}（${category.available}/${category.total}）`,
                  value: category.name,
                })),
              ]}
              value={params.category ?? ""}
            />
          </label>
          <label>
            <span>排序</span>
            <Select
              aria-label="排序"
              onChange={(value) => {
                const [sort, direction] = value.split(":");
                updateSearch({ sort, direction });
              }}
              options={[
                { label: "分类与席位", value: "category:asc" },
                { label: "台词 ID", value: "id:asc" },
                { label: "台词 ID 倒序", value: "id:desc" },
                { label: "文件由大到小", value: "byte_size:desc" },
                { label: "文件由小到大", value: "byte_size:asc" },
              ]}
              value={`${params.sort}:${params.direction}`}
            />
          </label>
          <label>
            <span>每页</span>
            <Select
              aria-label="每页"
              onChange={(value) => updateSearch({ page_size: value })}
              options={[
                { label: "20 条", value: "20" },
                { label: "50 条", value: "50" },
                { label: "100 条", value: "100" },
              ]}
              value={String(params.page_size)}
            />
          </label>
          <div className="game-filter-actions">
            {hasFilters ? (
              <Button htmlType="button" onClick={clearFilters} type="text">
                清除筛选
              </Button>
            ) : null}
            <Button htmlType="submit">
              应用筛选
            </Button>
          </div>
        </form>
      </section>

      <section aria-labelledby="voice-asset-list-title" className="game-list-panel voice-list-panel">
        <div className="game-list-heading">
          <div>
            <span>JUDGE LINES</span>
            <h2 id="voice-asset-list-title">台词资产</h2>
          </div>
          <p aria-live="polite">
            {data ? `筛选结果 ${data.pagination.total} 条` : "正在统计..."}
          </p>
        </div>

        {voiceQuery.isPending ? <VoiceListLoading /> : null}
        {voiceQuery.isError ? (
          <VoiceListError error={voiceQuery.error} onRetry={voiceQuery.refetch} />
        ) : null}
        {data && data.items.length === 0 ? (
          <div className="game-empty-state">
            <span aria-hidden="true">声</span>
            <h3>{hasFilters ? "没有符合条件的台词" : "没有语音资产定义"}</h3>
            <p>{hasFilters ? "调整或清除筛选条件后重试。" : "请检查法官台词定义。"}</p>
          </div>
        ) : null}
        {data && data.items.length > 0 ? (
          <ul aria-label="法官语音资产列表" className="voice-asset-list">
            {data.items.map((line) => (
              <VoiceLineCard key={line.id} line={line} />
            ))}
          </ul>
        ) : null}
        {data ? (
          <VoicePagination
            page={data.pagination.page}
            pages={data.pagination.pages}
            onPage={(page) =>
              setSearchParams(
                setJudgeVoiceSearchValues(searchParams, { page: String(page) }),
              )
            }
          />
        ) : null}
      </section>
    </div>
  );
}

function VoiceCoverage({ data }: { data: AdminJudgeVoiceList }) {
  const cards = [
    ["资产定义", String(data.coverage.total), `${data.categories.length} 个分类`],
    ["已生成", String(data.coverage.available), coveragePercent(data)],
    ["缺失", String(data.coverage.missing), data.coverage.missing ? "等待生成任务" : "覆盖完整"],
    ["文件体积", formatBytes(data.coverage.byte_total), `${data.audio_format.toUpperCase()} · ${data.sample_rate} Hz`],
  ];
  return (
    <section aria-label="语音资产概览" className="voice-coverage-grid">
      {cards.map(([label, value, detail]) => (
        <article key={label}>
          <span>{label}</span>
          <strong>{value}</strong>
          <small>{detail}</small>
        </article>
      ))}
    </section>
  );
}

function VoiceCoverageLoading() {
  return <div aria-label="正在读取语音资产概览" className="voice-coverage-grid is-loading" />;
}

function VoiceLineCard({ line }: { line: AdminJudgeVoiceLine }) {
  return (
    <li className={line.available ? "is-available" : "is-missing"}>
      <div className="voice-line-identity">
        <div>
          <code>{line.id}</code>
          <span className="voice-category-badge">{line.category}</span>
          {line.seat_number ? <span>{line.seat_number} 号位</span> : null}
        </div>
        <p>{line.text}</p>
        {line.template_id ? <small>模板：{line.template_id}</small> : null}
      </div>
      <div className="voice-line-metadata">
        <span className={`voice-usage-state ${line.used ? "is-used" : "is-unused"}`}>
          {line.used ? "已使用" : "未使用"}
        </span>
        <span className={`voice-file-state ${line.available ? "is-ready" : "is-missing"}`}>
          {line.available ? "已生成" : "缺失"}
        </span>
        <small>
          {line.available
            ? `${formatBytes(line.byte_size ?? 0)} · ${line.subtitle_cue_count} 个字幕时间点`
            : "暂无可试听文件"}
        </small>
      </div>
      <div className="voice-line-player">
        {line.audio_url ? (
          <audio
            aria-label={`试听 ${line.id}`}
            controls
            controlsList="nodownload"
            preload="none"
            src={line.audio_url}
          />
        ) : (
          <span>等待后续生成任务</span>
        )}
      </div>
    </li>
  );
}

function VoicePagination({
  page,
  pages,
  onPage,
}: {
  page: number;
  pages: number;
  onPage: (page: number) => void;
}) {
  return (
    <nav aria-label="语音资产分页" className="game-pagination">
      <button disabled={page <= 1} onClick={() => onPage(page - 1)} type="button">
        上一页
      </button>
      <span>第 {page} / {Math.max(1, pages)} 页</span>
      <button disabled={pages === 0 || page >= pages} onClick={() => onPage(page + 1)} type="button">
        下一页
      </button>
    </nav>
  );
}

function VoiceListLoading() {
  return (
    <div aria-live="polite" className="game-list-loading" role="status">
      正在读取语音资产...
    </div>
  );
}

function VoiceListError({ error, onRetry }: { error: Error; onRetry: () => unknown }) {
  const detail = isAdminApiError(error)
    ? error.problem.detail
    : "后台语音资产暂时不可用，请稍后重试。";
  const requestId = isAdminApiError(error) ? error.problem.request_id : null;
  return (
    <div className="game-list-error" role="alert">
      <h3>无法读取语音资产</h3>
      <p>{detail}</p>
      {requestId ? <small>请求编号：{requestId}</small> : null}
      <button onClick={() => void onRetry()} type="button">重新加载</button>
    </div>
  );
}

function coveragePercent(data: AdminJudgeVoiceList) {
  if (!data.coverage.total) return "0% 覆盖";
  return `${Math.round((data.coverage.available / data.coverage.total) * 100)}% 覆盖`;
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function formValue(values: FormData, key: string) {
  const value = values.get(key);
  return typeof value === "string" ? value : undefined;
}

function jobStatusLabel(status: "queued" | "running" | "completed" | "failed") {
  return { queued: "排队中", running: "执行中", completed: "已完成", failed: "失败" }[status];
}
