import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAdminSession } from "@/features/auth/session-context";

export function AdminSessionBoundary() {
  const location = useLocation();
  const { error, refreshSession, status } = useAdminSession();

  if (status === "loading") {
    return <FullPageStatus message="正在验证后台会话..." />;
  }

  if (status === "unauthenticated") {
    const returnTo = `${location.pathname}${location.search}${location.hash}`;
    return (
      <Navigate
        replace
        to={`/login?returnTo=${encodeURIComponent(returnTo)}`}
      />
    );
  }

  if (status === "forbidden") {
    return <Navigate replace to="/403" />;
  }

  if (status === "error") {
    return (
      <main className="auth-page">
        <section
          aria-labelledby="session-error-title"
          aria-live="polite"
          className="auth-card"
        >
          <span className="auth-kicker">ADMIN SESSION</span>
          <h1 id="session-error-title">暂时无法验证后台会话</h1>
          <p>{error?.message ?? "后台认证服务暂时不可用。"}</p>
          {error?.requestId ? (
            <small>请求编号：{error.requestId}</small>
          ) : null}
          <button
            className="auth-primary-button"
            onClick={() => void refreshSession()}
            type="button"
          >
            重新验证
          </button>
        </section>
      </main>
    );
  }

  return <Outlet />;
}

function FullPageStatus({ message }: { message: string }) {
  return (
    <main className="auth-page">
      <div aria-live="polite" className="auth-loading" role="status">
        <span aria-hidden="true" />
        {message}
      </div>
    </main>
  );
}
