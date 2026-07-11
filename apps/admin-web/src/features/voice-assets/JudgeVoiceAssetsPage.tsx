import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";

import { isAdminApiError } from "@/api/problem-details";
import { listAdminJudgeVoiceLines } from "@/features/voice-assets/api";
import {
  judgeVoiceListParamsFromSearch,
  setJudgeVoiceSearchValues,
} from "@/features/voice-assets/list-state";
import { adminJudgeVoiceKeys } from "@/features/voice-assets/query-keys";
import type {
  AdminJudgeVoiceLine,
  AdminJudgeVoiceList,
} from "@/features/voice-assets/types";

export default function JudgeVoiceAssetsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const params = judgeVoiceListParamsFromSearch(searchParams);
  const voiceQuery = useQuery({
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => listAdminJudgeVoiceLines(params, signal),
    queryKey: adminJudgeVoiceKeys.list(params),
    staleTime: 30_000,
  });
  const data = voiceQuery.data;

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
          <p>核对固定法官台词的生成覆盖率、文件状态与受认证试听。</p>
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
        </div>
      </header>

      <p className="voice-assets-storage-note">
        当前读取旧静态目录中的已生成文件；本页不会自动生成、覆盖或删除语音。独立持久存储和异步生成任务将在后续写操作切片接入。
      </p>

      {data ? <VoiceCoverage data={data} /> : <VoiceCoverageLoading />}

      <section aria-label="语音资产筛选" className="game-filter-panel voice-filter-panel">
        <form onSubmit={handleSearch} role="search">
          <label className="game-filter-wide">
            <span>搜索台词</span>
            <input
              defaultValue={params.q ?? ""}
              key={`q-${params.q ?? ""}`}
              name="q"
              placeholder="台词 ID 或内容"
              type="search"
            />
          </label>
          <label>
            <span>文件状态</span>
            <select
              aria-label="文件状态"
              onChange={(event) =>
                updateSearch({ availability: event.target.value })
              }
              value={params.availability ?? ""}
            >
              <option value="">全部状态</option>
              <option value="available">已生成</option>
              <option value="missing">缺失</option>
            </select>
          </label>
          <label>
            <span>台词分类</span>
            <select
              aria-label="台词分类"
              onChange={(event) => updateSearch({ category: event.target.value })}
              value={params.category ?? ""}
            >
              <option value="">全部分类</option>
              {(data?.categories ?? []).map((category) => (
                <option key={category.name} value={category.name}>
                  {category.name}（{category.available}/{category.total}）
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>排序</span>
            <select
              aria-label="排序"
              onChange={(event) => {
                const [sort, direction] = event.target.value.split(":");
                updateSearch({ sort, direction });
              }}
              value={`${params.sort}:${params.direction}`}
            >
              <option value="category:asc">分类与席位</option>
              <option value="id:asc">台词 ID</option>
              <option value="id:desc">台词 ID 倒序</option>
              <option value="byte_size:desc">文件由大到小</option>
              <option value="byte_size:asc">文件由小到大</option>
            </select>
          </label>
          <label>
            <span>每页</span>
            <select
              aria-label="每页"
              onChange={(event) => updateSearch({ page_size: event.target.value })}
              value={String(params.page_size)}
            >
              <option value="20">20 条</option>
              <option value="50">50 条</option>
              <option value="100">100 条</option>
            </select>
          </label>
          <div className="game-filter-actions">
            {hasFilters ? (
              <button className="admin-text-button" onClick={clearFilters} type="button">
                清除筛选
              </button>
            ) : null}
            <button className="admin-secondary-button" type="submit">
              应用筛选
            </button>
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
