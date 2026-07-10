import { type FormEvent, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { isAdminDevLoginEnabled } from "@/features/auth/runtime-config";
import { useAdminSession } from "@/features/auth/session-context";

export default function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [submitted, setSubmitted] = useState(false);
  const {
    clearError,
    error,
    loginWithDevSession,
    pendingAction,
    status,
    unauthenticatedReason,
  } = useAdminSession();
  const devLoginEnabled = isAdminDevLoginEnabled();
  const returnTo = safeReturnTo(searchParams.get("returnTo"));

  if (status === "loading") {
    return (
      <main className="auth-page">
        <div aria-live="polite" className="auth-loading" role="status">
          <span aria-hidden="true" />
          正在检查现有后台会话...
        </div>
      </main>
    );
  }

  if (status === "authenticated") {
    return <Navigate replace to={returnTo} />;
  }

  async function handleDevLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    clearError();
    setSubmitted(true);
    try {
      await loginWithDevSession();
      navigate(returnTo, { replace: true });
    } catch {
      // The provider exposes a structured, user-safe error below.
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="admin-login-title">
        <div className="auth-brand" aria-hidden="true">
          WA
        </div>
        <span className="auth-kicker">WEREWOLF ARENA ADMIN</span>
        <h1 id="admin-login-title">登录管理后台</h1>
        <p>后台仅面向获得授权的运营与技术人员，不支持公开注册。</p>

        {unauthenticatedReason === "expired" ? (
          <div aria-live="polite" className="auth-notice is-warning" role="status">
            会话已过期。请重新登录后继续。
          </div>
        ) : null}
        {unauthenticatedReason === "signed-out" ? (
          <div aria-live="polite" className="auth-notice is-success" role="status">
            已安全退出后台。
          </div>
        ) : null}

        {devLoginEnabled ? (
          <form className="auth-form" onSubmit={handleDevLogin}>
            <div className="dev-login-description">
              <strong>本地开发身份</strong>
              <span>账号与角色由 API 服务端环境变量决定。</span>
            </div>
            <button
              className="auth-primary-button"
              disabled={pendingAction === "login"}
              type="submit"
            >
              {pendingAction === "login" ? "正在建立会话..." : "使用开发身份登录"}
            </button>
          </form>
        ) : (
          <div className="auth-notice" role="note">
            当前环境未提供登录入口。请通过已配置的企业身份入口访问，或联系系统管理员。
          </div>
        )}

        {submitted && error ? (
          <div aria-live="assertive" className="auth-error" role="alert">
            <strong>{error.problem.title}</strong>
            <span>{error.message}</span>
            {error.requestId ? <small>请求编号：{error.requestId}</small> : null}
          </div>
        ) : null}

        <footer>
          会话凭据仅保存在安全的 HttpOnly Cookie 中，不会写入浏览器本地存储。
        </footer>
      </section>
    </main>
  );
}

function safeReturnTo(value: string | null) {
  if (!value || !value.startsWith("/") || value.startsWith("//")) {
    return "/content/players";
  }
  if (value.startsWith("/login") || value.startsWith("/403")) {
    return "/content/players";
  }
  return value;
}
