import AntApp from "antd/es/app";
import ConfigProvider from "antd/es/config-provider";
import zhCN from "antd/locale/zh_CN";
import { Outlet } from "react-router-dom";

import { adminTheme } from "@/app/antd-theme";
import { AdminSessionProvider } from "@/features/auth/AdminSessionProvider";
import { getAdminRuntimeMode } from "@/features/auth/runtime-config";

export function AdminPreviewBoundary() {
  const runtimeMode = getAdminRuntimeMode();

  return (
    <ConfigProvider
      button={{ autoInsertSpace: false }}
      locale={zhCN}
      theme={adminTheme}
      wave={{ disabled: true }}
    >
      <AntApp component={false}>
        <AdminRuntimeBoundary runtimeMode={runtimeMode} />
      </AntApp>
    </ConfigProvider>
  );
}

function AdminRuntimeBoundary({
  runtimeMode,
}: {
  runtimeMode: ReturnType<typeof getAdminRuntimeMode>;
}) {
  if (runtimeMode !== "closed") {
    return (
      <AdminSessionProvider runtimeMode={runtimeMode}>
        <Outlet />
      </AdminSessionProvider>
    );
  }

  return (
    <main className="security-gate">
      <section className="security-gate-card" aria-labelledby="security-gate-title">
        <span className="security-gate-kicker">ADMIN SECURITY GATE</span>
        <h1 id="security-gate-title">管理后台未开放</h1>
        <p>
          生产构建保持安全关闭。完成身份源、部署配置与安全验收后，才能开放管理后台。
        </p>
        <dl>
          <div>
            <dt>当前状态</dt>
            <dd>Fail closed</dd>
          </div>
          <div>
            <dt>开放条件</dt>
            <dd>身份源 · 权限 · 审计</dd>
          </div>
        </dl>
      </section>
    </main>
  );
}
