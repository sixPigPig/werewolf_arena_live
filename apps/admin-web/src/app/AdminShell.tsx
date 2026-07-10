import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import {
  adminNavigation,
  findAdminNavItem,
} from "@/app/admin-navigation";
import { hasAdminPermission } from "@/features/auth/permissions";
import { useAdminSession } from "@/features/auth/session-context";
import type { AdminRole } from "@/features/auth/types";

const roleLabels: Record<AdminRole, string> = {
  viewer: "只读观察员",
  content_editor: "内容编辑",
  operator: "运行运营",
  super_admin: "超级管理员",
};

export function AdminShell() {
  const location = useLocation();
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const { logout, pendingAction, runtimeMode, session } = useAdminSession();
  const activeItem = findAdminNavItem(location.pathname);
  const user = session?.user;
  const visibleNavigation = adminNavigation
    .map((section) => ({
      ...section,
      items: section.items.filter((item) =>
        hasAdminPermission(session?.permissions ?? [], item.permission),
      ),
    }))
    .filter((section) => section.items.length > 0);

  async function handleLogout() {
    setLogoutError(null);
    try {
      await logout();
    } catch (error) {
      setLogoutError(error instanceof Error ? error.message : "退出失败，请稍后重试。");
    }
  }

  return (
    <div className="admin-app-shell">
      <a className="skip-link" href="#admin-main-content">
        跳到主要内容
      </a>
      <button
        aria-label="关闭导航"
        className="admin-sidebar-backdrop"
        data-open={navigationOpen}
        onClick={() => setNavigationOpen(false)}
        type="button"
      />
      <aside className="admin-sidebar" data-open={navigationOpen}>
        <div className="admin-brand">
          <span className="admin-brand-mark" aria-hidden="true">
            WA
          </span>
          <span>
            <strong>Werewolf Arena</strong>
            <small>运营与诊断后台</small>
          </span>
        </div>

        <nav aria-label="后台主导航" className="admin-navigation">
          {visibleNavigation.map((section) => (
            <section className="admin-navigation-section" key={section.id}>
              <h2>{section.label}</h2>
              {section.items.map((item) => (
                <NavLink
                  className={({ isActive }) =>
                    isActive ? "admin-nav-link is-active" : "admin-nav-link"
                  }
                  key={item.id}
                  onClick={() => setNavigationOpen(false)}
                  to={item.href}
                >
                  <span className="admin-nav-marker" aria-hidden="true">
                    {item.marker}
                  </span>
                  <span>
                    <strong>{item.label}</strong>
                    <small>{item.description}</small>
                  </span>
                </NavLink>
              ))}
            </section>
          ))}
        </nav>

        <footer className="admin-sidebar-footer">
          <span className="status-dot" aria-hidden="true" />
          <span>
            <strong>
              {runtimeMode === "preview" ? "规划预览模式" : "安全会话已连接"}
            </strong>
            <small>
              {runtimeMode === "preview" ? "未连接 Admin API" : "Admin API"}
            </small>
          </span>
        </footer>
      </aside>

      <div className="admin-workspace">
        <header className="admin-topbar">
          <button
            aria-expanded={navigationOpen}
            aria-label="打开导航"
            className="admin-menu-button"
            onClick={() => setNavigationOpen((current) => !current)}
            type="button"
          >
            <span />
            <span />
            <span />
          </button>
          <div className="admin-breadcrumbs" aria-label="当前位置">
            <span>管理后台</span>
            <span aria-hidden="true">/</span>
            <strong>{activeItem?.label ?? "页面"}</strong>
          </div>
          <div className="admin-topbar-actions">
            {logoutError ? (
              <span aria-live="assertive" className="topbar-error" role="alert">
                {logoutError}
              </span>
            ) : null}
            <span className="environment-badge">
              {runtimeMode === "preview" ? "LOCAL PREVIEW" : "ADMIN SESSION"}
            </span>
            <span className="preview-principal" aria-label="当前后台身份">
              <span aria-hidden="true">超</span>
              <span>
                <strong>{user ? roleLabels[user.role] : "后台用户"}</strong>
                <small>{user?.display_name ?? "unknown principal"}</small>
              </span>
            </span>
            {runtimeMode === "authenticated" ? (
              <button
                className="admin-logout-button"
                disabled={pendingAction === "logout"}
                onClick={() => void handleLogout()}
                type="button"
              >
                {pendingAction === "logout" ? "退出中" : "退出"}
              </button>
            ) : null}
          </div>
        </header>

        <main className="admin-main" id="admin-main-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
