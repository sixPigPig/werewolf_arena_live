import { useQuery } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router-dom";

import { isAdminDevLoginEnabled } from "@/features/auth/runtime-config";
import { getAdminLoginOptions } from "@/features/auth/auth-api";
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
  const oidcError = searchParams.get("oidcError");
  const loginOptions = useQuery({
    enabled: !devLoginEnabled,
    queryFn: getAdminLoginOptions,
    queryKey: ["admin", "login-options"],
    retry: false,
    staleTime: 60_000,
  });
  const oidcStartPath = loginOptions.data?.oidc_enabled
    ? loginOptions.data.oidc_start_path
    : null;

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

        {oidcStartPath ? (
          <a
            className="auth-primary-button"
            href={`${oidcStartPath}?return_to=${encodeURIComponent(returnTo)}`}
          >
            使用企业账号登录
          </a>
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
        ) : !oidcStartPath && !loginOptions.isPending ? (
          <div className="auth-notice" role="note">
            当前环境未提供登录入口。请通过已配置的企业身份入口访问，或联系系统管理员。
          </div>
        ) : null}

        {oidcError ? (
          <div aria-live="assertive" className="auth-error" role="alert">
            <strong>企业账号登录失败</strong>
            <span>{oidcErrorMessage(oidcError)}</span>
          </div>
        ) : null}

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

function oidcErrorMessage(code: string) {
  if (code === "admin_oidc_account_not_provisioned") {
    return "该企业账号尚未获得后台权限，请联系系统管理员。";
  }
  if (code === "admin_oidc_account_disabled") {
    return "该后台账号已停用，请联系系统管理员。";
  }
  if (code === "admin_oidc_provider_denied") {
    return "企业身份提供商未完成授权，请重新尝试。";
  }
  return "登录事务无效或身份验证失败，请重新尝试。";
}
