import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import {
  adminNavigation,
  findAdminNavItem,
} from "@/app/admin-navigation";

export function AdminShell() {
  const location = useLocation();
  const [navigationOpen, setNavigationOpen] = useState(false);
  const activeItem = findAdminNavItem(location.pathname);

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
          {adminNavigation.map((section) => (
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
            <strong>规划预览模式</strong>
            <small>未连接 Admin API</small>
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
            <span className="environment-badge">LOCAL PREVIEW</span>
            <span className="preview-principal" aria-label="当前预览角色">
              <span aria-hidden="true">超</span>
              <span>
                <strong>超级管理员</strong>
                <small>mock principal</small>
              </span>
            </span>
          </div>
        </header>

        <main className="admin-main" id="admin-main-content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
