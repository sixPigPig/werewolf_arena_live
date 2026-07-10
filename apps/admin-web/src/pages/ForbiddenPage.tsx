import { useState } from "react";
import { Link } from "react-router-dom";

import { useAdminSession } from "@/features/auth/session-context";

export default function ForbiddenPage() {
  const { error, logout, pendingAction, session } = useAdminSession();
  const [logoutFailed, setLogoutFailed] = useState(false);

  async function handleLogout() {
    setLogoutFailed(false);
    try {
      await logout();
    } catch {
      setLogoutFailed(true);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card forbidden-card" aria-labelledby="forbidden-title">
        <span className="forbidden-code" aria-hidden="true">
          403
        </span>
        <span className="auth-kicker">ACCESS DENIED</span>
        <h1 id="forbidden-title">没有访问权限</h1>
        <p>
          当前后台身份无权访问这个页面。如果工作职责已变更，请联系超级管理员调整权限。
        </p>
        {error?.requestId ? <small>请求编号：{error.requestId}</small> : null}
        {logoutFailed ? (
          <div aria-live="assertive" className="auth-error" role="alert">
            <span>{error?.message ?? "退出失败，请稍后重试。"}</span>
          </div>
        ) : null}
        <div className="auth-actions">
          <Link className="auth-primary-button" to="/content/players">
            返回玩家管理
          </Link>
          {session ? (
            <button
              className="auth-secondary-button"
              disabled={pendingAction === "logout"}
              onClick={() => void handleLogout()}
              type="button"
            >
              {pendingAction === "logout" ? "正在退出..." : "退出当前账号"}
            </button>
          ) : (
            <Link className="auth-secondary-button" to="/login">
              返回登录
            </Link>
          )}
        </div>
      </section>
    </main>
  );
}
