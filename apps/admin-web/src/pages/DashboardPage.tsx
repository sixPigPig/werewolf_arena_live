const metrics = [
  { label: "运行中", value: "--", note: "等待 /admin/runs" },
  { label: "24 小时失败", value: "--", note: "等待聚合接口" },
  { label: "已发布玩家", value: "--", note: "等待内容状态" },
  { label: "缺失语音", value: "--", note: "等待资产服务" },
];

const foundations = [
  {
    title: "Public / Admin API 隔离",
    detail: "C 端 DTO 不得包含 prompt、raw response 与私有状态。",
    state: "阻断",
    tone: "critical",
  },
  {
    title: "认证、RBAC 与审计",
    detail: "所有管理写操作必须由服务端授权并记录操作者。",
    state: "阻断",
    tone: "critical",
  },
  {
    title: "服务端分页与筛选",
    detail: "玩家、对局和运行列表不再加载全量数据。",
    state: "待开发",
    tone: "planned",
  },
  {
    title: "语音资产持久化",
    detail: "运行时文件迁出旧 Web 源码目录。",
    state: "待开发",
    tone: "planned",
  },
];

export default function DashboardPage() {
  return (
    <div className="admin-page">
      <header className="page-heading">
        <div>
          <span className="page-kicker">OVERVIEW</span>
          <h1>运营总览</h1>
          <p>统一查看对局运行、内容资产和后台安全基线。</p>
        </div>
        <span className="page-readiness-badge">规划骨架</span>
      </header>

      <section className="metric-grid" aria-label="核心指标">
        {metrics.map((metric) => (
          <article className="metric-card" key={metric.label}>
            <span>{metric.label}</span>
            <strong>{metric.value}</strong>
            <small>{metric.note}</small>
          </article>
        ))}
      </section>

      <div className="dashboard-grid">
        <section className="admin-panel" aria-labelledby="foundation-title">
          <div className="panel-heading">
            <div>
              <span>上线门槛</span>
              <h2 id="foundation-title">后台基础能力</h2>
            </div>
            <strong>0 / 4 完成</strong>
          </div>
          <div className="foundation-list">
            {foundations.map((item) => (
              <article key={item.title}>
                <span className={`foundation-state is-${item.tone}`}>
                  {item.state}
                </span>
                <div>
                  <h3>{item.title}</h3>
                  <p>{item.detail}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        <aside className="admin-panel next-step-panel" aria-labelledby="next-step-title">
          <span>推荐起点</span>
          <h2 id="next-step-title">先打通安全只读链路</h2>
          <ol>
            <li>建立后台登录会话和固定角色</li>
            <li>提供只读 Admin 总览与分页列表</li>
            <li>加入敏感诊断字段的独立权限</li>
            <li>最后开放受审计保护的写操作</li>
          </ol>
          <p>当前页面不会调用现有匿名业务接口。</p>
        </aside>
      </div>
    </div>
  );
}
