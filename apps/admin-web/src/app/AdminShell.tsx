import AuditOutlined from "@ant-design/icons/es/icons/AuditOutlined";
import CloudServerOutlined from "@ant-design/icons/es/icons/CloudServerOutlined";
import ControlOutlined from "@ant-design/icons/es/icons/ControlOutlined";
import DashboardOutlined from "@ant-design/icons/es/icons/DashboardOutlined";
import DatabaseOutlined from "@ant-design/icons/es/icons/DatabaseOutlined";
import MenuOutlined from "@ant-design/icons/es/icons/MenuOutlined";
import ProfileOutlined from "@ant-design/icons/es/icons/ProfileOutlined";
import RobotOutlined from "@ant-design/icons/es/icons/RobotOutlined";
import SafetyCertificateOutlined from "@ant-design/icons/es/icons/SafetyCertificateOutlined";
import SettingOutlined from "@ant-design/icons/es/icons/SettingOutlined";
import SoundOutlined from "@ant-design/icons/es/icons/SoundOutlined";
import TeamOutlined from "@ant-design/icons/es/icons/TeamOutlined";
import Avatar from "antd/es/avatar";
import AntApp from "antd/es/app";
import Badge from "antd/es/badge";
import Breadcrumb from "antd/es/breadcrumb";
import Button from "antd/es/button";
import Drawer from "antd/es/drawer";
import Flex from "antd/es/flex";
import Layout from "antd/es/layout";
import Menu, { type MenuProps } from "antd/es/menu";
import Space from "antd/es/space";
import Tag from "antd/es/tag";
import Typography from "antd/es/typography";
import { useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";

import {
  adminNavigation,
  findAdminNavItem,
} from "@/app/admin-navigation";
import { hasAdminPermission } from "@/features/auth/permissions";
import { useAdminSession } from "@/features/auth/session-context";
import type { AdminRole } from "@/features/auth/types";
import { GlobalAdminSearch } from "@/features/dashboard/GlobalAdminSearch";
import {
  useOverviewQuery,
  useSettingsQuery,
} from "@/features/dashboard/queries";
import { adminOperationErrorDescription } from "@/lib/admin-notification";

const { Content, Header, Sider } = Layout;

const roleLabels: Record<AdminRole, string> = {
  viewer: "只读观察员",
  content_editor: "内容编辑",
  operator: "运行运营",
  super_admin: "超级管理员",
};

const navigationIcons = {
  "admin-users": <SafetyCertificateOutlined aria-hidden="true" />,
  "audit-events": <AuditOutlined aria-hidden="true" />,
  games: <DatabaseOutlined aria-hidden="true" />,
  jobs: <ProfileOutlined aria-hidden="true" />,
  models: <RobotOutlined aria-hidden="true" />,
  overview: <DashboardOutlined aria-hidden="true" />,
  players: <TeamOutlined aria-hidden="true" />,
  rules: <ControlOutlined aria-hidden="true" />,
  runs: <CloudServerOutlined aria-hidden="true" />,
  settings: <SettingOutlined aria-hidden="true" />,
  "v2-games": <DatabaseOutlined aria-hidden="true" />,
  "voice-assets": <SoundOutlined aria-hidden="true" />,
};

export function AdminShell() {
  const { notification } = AntApp.useApp();
  const location = useLocation();
  const [navigationOpen, setNavigationOpen] = useState(false);
  const { logout, pendingAction, runtimeMode, session } = useAdminSession();
  const activeItem = findAdminNavItem(location.pathname);
  const user = session?.user;
  const permissions = session?.permissions ?? [];
  const canReadOverview = hasAdminPermission(permissions, "overview.read");
  const canReadSettings = hasAdminPermission(permissions, "settings.read");
  const overview = useOverviewQuery(runtimeMode, canReadOverview);
  const settings = useSettingsQuery(runtimeMode, canReadSettings);
  const alertCount =
    overview.data?.alerts.reduce((total, alert) => total + alert.count, 0) ?? 0;
  const visibleNavigation = adminNavigation
    .map((section) => ({
      ...section,
      items: section.items.filter((item) =>
        hasAdminPermission(permissions, item.permission),
      ),
    }))
    .filter((section) => section.items.length > 0);
  const menuItems: MenuProps["items"] = visibleNavigation.map((section) => ({
    children: section.items.map((item) => ({
      icon: navigationIcons[item.id as keyof typeof navigationIcons],
      key: item.href,
      label: (
        <Link
          aria-label={`${item.label} ${item.description}`}
          title={item.description}
          to={item.href}
        >
          {item.label}
        </Link>
      ),
    })),
    key: section.id,
    label: section.label,
    type: "group",
  }));

  async function handleLogout() {
    try {
      await logout();
    } catch (error) {
      notification.error({
        description: adminOperationErrorDescription(
          error,
          "退出失败，请稍后重试。",
        ),
        title: "退出失败",
      });
    }
  }

  function focusMainContent() {
    window.requestAnimationFrame(() => {
      document.getElementById("admin-main-content")?.focus();
    });
  }

  const sidebar = (
    <div className="admin-ant-sider-inner">
      <div className="admin-ant-brand">
        <span className="admin-brand-mark" aria-hidden="true">
          WA
        </span>
        <span className="admin-ant-brand-copy">
          <strong>Werewolf Arena</strong>
          <small>运营与诊断后台</small>
        </span>
      </div>
      <nav aria-label="后台主导航">
        <Menu
          className="admin-ant-menu"
          items={menuItems}
          mode="inline"
          onClick={() => setNavigationOpen(false)}
          selectedKeys={activeItem ? [activeItem.href] : []}
          theme="dark"
        />
      </nav>
      <div className="admin-ant-sider-footer">
        <Flex align="center" gap={9}>
          <Badge status={runtimeMode === "preview" ? "warning" : "success"} />
          <span>
            <Typography.Text strong>
              {runtimeMode === "preview" ? "规划预览模式" : "安全会话已连接"}
            </Typography.Text>
            <Typography.Text type="secondary">
              {runtimeMode === "preview" ? "未连接 Admin API" : "Admin API"}
            </Typography.Text>
          </span>
        </Flex>
      </div>
    </div>
  );

  return (
    <Layout className="admin-ant-layout admin-app-shell">
      <a
        className="skip-link"
        href="#admin-main-content"
        onClick={focusMainContent}
      >
        跳到主要内容
      </a>
      <Sider className="admin-ant-sider" width={260}>
        {sidebar}
      </Sider>
      {navigationOpen ? (
        <Drawer
          closable={false}
          onClose={() => setNavigationOpen(false)}
          open
          placement="left"
          rootClassName="admin-ant-mobile-drawer"
          size={276}
          styles={{ body: { background: "#111827", padding: 0 } }}
        >
          {sidebar}
        </Drawer>
      ) : null}

      <Layout className="admin-ant-workspace">
        <Header className="admin-ant-header">
          <Button
            aria-expanded={navigationOpen}
            aria-label="打开导航"
            className="admin-ant-menu-trigger"
            icon={<MenuOutlined />}
            onClick={() => setNavigationOpen(true)}
            type="text"
          />
          <Breadcrumb
            aria-label="当前位置"
            items={[
              { title: "管理后台" },
              { title: activeItem?.label ?? "页面" },
            ]}
          />
          {canReadOverview ? <GlobalAdminSearch runtimeMode={runtimeMode} /> : null}
          <Space className="admin-ant-header-actions" size={10}>
            {alertCount > 0 ? (
              <Link
                aria-label={`${alertCount} 项异常`}
                title="查看活动异常"
                to="/overview"
              >
                <Badge count={alertCount} overflowCount={99}>
                  <Button type="text">
                    <span className="admin-ant-alert-label">异常</span>
                  </Button>
                </Badge>
              </Link>
            ) : null}
            <Tag className="admin-ant-environment" color="blue">
              {runtimeMode === "preview"
                ? "LOCAL PREVIEW"
                : (settings.data?.environment ?? "ADMIN").toUpperCase()}
            </Tag>
            <span
              aria-label="当前后台身份"
              className="admin-ant-principal"
              role="group"
            >
              <Avatar size={32}>{user?.display_name?.slice(0, 1) ?? "管"}</Avatar>
              <span className="admin-ant-principal-copy">
                <strong>{user ? roleLabels[user.role] : "后台用户"}</strong>
                <small>{user?.display_name ?? "unknown principal"}</small>
              </span>
            </span>
            {runtimeMode === "authenticated" ? (
              <Button
                aria-label="退出"
                loading={pendingAction === "logout"}
                onClick={() => void handleLogout()}
              >
                退出
              </Button>
            ) : null}
          </Space>
        </Header>

        <Content
          className="admin-ant-content"
          id="admin-main-content"
          tabIndex={-1}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
