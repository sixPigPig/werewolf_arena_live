import { Outlet } from "react-router-dom";

function previewModeEnabled() {
  if (import.meta.env.MODE === "test") {
    return true;
  }

  return (
    import.meta.env.DEV && import.meta.env.VITE_ADMIN_PREVIEW_MODE !== "false"
  );
}

export function AdminPreviewBoundary() {
  if (previewModeEnabled()) {
    return <Outlet />;
  }

  return (
    <main className="security-gate">
      <section className="security-gate-card" aria-labelledby="security-gate-title">
        <span className="security-gate-kicker">ADMIN SECURITY GATE</span>
        <h1 id="security-gate-title">后台认证尚未接入</h1>
        <p>
          生产构建已默认关闭规划预览。完成 Admin API、登录会话和服务端 RBAC
          后，才能开放管理后台。
        </p>
        <dl>
          <div>
            <dt>当前状态</dt>
            <dd>Fail closed</dd>
          </div>
          <div>
            <dt>开放条件</dt>
            <dd>认证 · 权限 · 审计</dd>
          </div>
        </dl>
      </section>
    </main>
  );
}
