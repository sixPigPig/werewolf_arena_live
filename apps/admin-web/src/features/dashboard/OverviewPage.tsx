import { Link } from "react-router-dom";

import { useAdminSession } from "@/features/auth/session-context";
import { useOverviewQuery } from "@/features/dashboard/queries";

export default function OverviewPage() {
  const { runtimeMode } = useAdminSession();
  const overview = useOverviewQuery(runtimeMode);

  if (overview.isPending) return <PageState message="正在汇总运营状态..." />;
  if (overview.isError || !overview.data) {
    return <PageState message="运营总览暂时不可用。" retry={() => overview.refetch()} />;
  }

  const data = overview.data;
  return (
    <div className="admin-page dashboard-page">
      <header className="page-heading">
        <div>
          <span className="page-kicker">OPERATIONS / OVERVIEW</span>
          <h1>运营总览</h1>
          <p>聚合内容、对局、运行、任务与自动恢复健康状态。</p>
        </div>
        <span className={`dashboard-environment is-${data.environment}`}>
          {data.environment.toUpperCase()}
        </span>
      </header>

      <section aria-label="关键运营指标" className="dashboard-metrics-grid">
        <MetricCard href="/content/players" label="玩家内容" value={data.profiles.total} detail={`${data.profiles.draft} 草稿 · ${data.profiles.published} 已发布`} />
        <MetricCard href="/operations/games" label="对局记录" value={data.games.total} detail={`${data.games.incomplete} 未完整 · ${data.games.resumable} 可恢复`} />
        <MetricCard href="/operations/runs" label="活动运行" value={data.runs.queued + data.runs.running} detail={`${data.runs.stale} 失联 · ${data.runs.failed} 失败`} />
        <MetricCard href="/system/jobs" label="后台任务" value={data.jobs.queued + data.jobs.running} detail={`${data.jobs.failed} 失败 · ${data.jobs.completed} 完成`} />
      </section>

      <div className="dashboard-detail-grid">
        <section className="dashboard-panel" aria-labelledby="dashboard-alerts-title">
          <div className="dashboard-panel-heading">
            <div>
              <span className="page-kicker">ACTIVE SIGNALS</span>
              <h2 id="dashboard-alerts-title">需要关注</h2>
            </div>
            <span className={`dashboard-health ${data.reaper_up ? "is-healthy" : "is-critical"}`}>
              Reaper {data.reaper_up ? "正常" : "异常"}
            </span>
          </div>
          {data.alerts.length === 0 ? (
            <div className="dashboard-empty-signal"><strong>没有活动告警</strong><span>运行恢复和持久任务当前没有异常信号。</span></div>
          ) : (
            <ul className="dashboard-alert-list">
              {data.alerts.map((alert) => (
                <li className={`is-${alert.severity}`} key={alert.code}>
                  <div><strong>{alert.title}</strong><p>{alert.detail}</p></div>
                  <Link to={alert.href}>{alert.count} 项 →</Link>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="dashboard-panel" aria-labelledby="dashboard-breakdown-title">
          <div className="dashboard-panel-heading">
            <div><span className="page-kicker">SYSTEM BREAKDOWN</span><h2 id="dashboard-breakdown-title">状态分布</h2></div>
          </div>
          <dl className="dashboard-breakdown">
            <div><dt>运行完成 / 取消</dt><dd>{data.runs.completed} / {data.runs.canceled}</dd></div>
            <div><dt>恢复已耗尽</dt><dd>{data.runs.recovery_exhausted}</dd></div>
            <div><dt>推荐玩家</dt><dd>{data.profiles.featured}</dd></div>
            <div><dt>语音任务失败</dt><dd>{data.jobs.failed}</dd></div>
          </dl>
          <small>更新时间：{new Date(data.generated_at).toLocaleString("zh-CN")}</small>
        </section>
      </div>
    </div>
  );
}
function MetricCard({ href, label, value, detail }: { href: string; label: string; value: number; detail: string }) {
  return <Link className="dashboard-metric-card" to={href}><span>{label}</span><strong>{value}</strong><small>{detail}</small></Link>;
}

function PageState({ message, retry }: { message: string; retry?: () => void }) {
  return <div className="dashboard-page-state" role="status"><span>{message}</span>{retry ? <button onClick={retry} type="button">重试</button> : null}</div>;
}
