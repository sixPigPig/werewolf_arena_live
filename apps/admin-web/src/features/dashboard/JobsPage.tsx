import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";

import { listAdminJobs } from "@/features/dashboard/api";
import type { AdminJobStatus } from "@/features/dashboard/types";
import { useAdminSession } from "@/features/auth/session-context";

const STATUSES: AdminJobStatus[] = ["queued", "running", "completed", "failed"];
const STATUS_LABELS: Record<AdminJobStatus, string> = { queued: "排队中", running: "执行中", completed: "已完成", failed: "失败" };

export default function JobsPage() {
  const { runtimeMode } = useAdminSession();
  const [search, setSearch] = useSearchParams();
  const page = Math.max(1, Number(search.get("page")) || 1);
  const rawStatus = search.get("status");
  const status = STATUSES.includes(rawStatus as AdminJobStatus) ? rawStatus as AdminJobStatus : undefined;
  const highlightedJob = search.get("job");
  const jobs = useQuery({
    queryKey: ["admin", "dashboard", "jobs", { page, status }],
    queryFn: ({ signal }) => runtimeMode === "preview" ? { items: [], pagination: { page: 1, page_size: 20, total: 0, pages: 0 } } : listAdminJobs({ page, page_size: 20, status }, signal),
    refetchInterval: runtimeMode === "authenticated" ? 10_000 : false,
  });

  function updateStatus(next: string) {
    const params = new URLSearchParams(search);
    if (next) params.set("status", next); else params.delete("status");
    params.delete("page");
    setSearch(params);
  }

  return (
    <div className="admin-page dashboard-page">
      <header className="page-heading"><div><span className="page-kicker">SYSTEM / JOBS</span><h1>后台任务</h1><p>查看持久语音任务的领取、进度和稳定错误分类。</p></div></header>
      <div className="dashboard-toolbar">
        <label>任务状态<select aria-label="任务状态" onChange={(event) => updateStatus(event.target.value)} value={status ?? ""}><option value="">全部</option>{STATUSES.map((item) => <option key={item} value={item}>{STATUS_LABELS[item]}</option>)}</select></label>
        <button onClick={() => void jobs.refetch()} type="button">刷新</button>
      </div>
      {jobs.isPending ? <div className="dashboard-page-state">正在读取任务...</div> : jobs.isError ? <div className="dashboard-page-state" role="alert">任务列表暂时不可用。</div> : jobs.data?.items.length === 0 ? <div className="dashboard-page-state">当前没有符合条件的持久任务。</div> : (
        <div className="dashboard-table-wrap"><table className="dashboard-table"><thead><tr><th>任务</th><th>状态</th><th>进度</th><th>结果</th><th>创建时间</th></tr></thead><tbody>{jobs.data?.items.map((job) => <tr className={highlightedJob === job.id ? "is-highlighted" : ""} key={job.id}><td><strong>{job.mode === "missing" ? "生成缺失语音" : "重新生成全部"}</strong><small>{job.id}</small></td><td><span className={`dashboard-status is-${job.status}`}>{STATUS_LABELS[job.status]}</span></td><td>{job.processed_count} / {job.total_count}</td><td>{job.error_code ?? `生成 ${job.generated_count} · 失败 ${job.failed_count}`}</td><td>{new Date(job.created_at).toLocaleString("zh-CN")}</td></tr>)}</tbody></table></div>
      )}
      {jobs.data && jobs.data.pagination.pages > 1 ? <div className="dashboard-pagination"><button disabled={page <= 1} onClick={() => setSearch((current) => { const next = new URLSearchParams(current); next.set("page", String(page - 1)); return next; })} type="button">上一页</button><span>第 {page} / {jobs.data.pagination.pages} 页</span><button disabled={page >= jobs.data.pagination.pages} onClick={() => setSearch((current) => { const next = new URLSearchParams(current); next.set("page", String(page + 1)); return next; })} type="button">下一页</button></div> : null}
    </div>
  );
}
