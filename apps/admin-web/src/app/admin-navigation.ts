export type AdminPermission =
  | "overview.read"
  | "games.read"
  | "games.delete"
  | "runs.read"
  | "voice.read"
  | "voice.generate_missing"
  | "voice.regenerate_all"
  | "players.read"
  | "players.write"
  | "players.publish"
  | "players.archive"
  | "players.ai_generate"
  | "rules.read"
  | "rules.write"
  | "rules.publish"
  | "rules.archive"
  | "rules.set_default"
  | "users.manage"
  | "roles.manage"
  | "audit.read"
  | "settings.read";

export type AdminNavItem = {
  description: string;
  href: string;
  id: string;
  label: string;
  marker: string;
  permission: AdminPermission;
};

export type AdminNavSection = {
  id: string;
  items: AdminNavItem[];
  label: string;
};

export const adminNavigation: AdminNavSection[] = [
  {
    id: "overview",
    label: "工作台",
    items: [
      {
        id: "overview",
        label: "运营总览",
        description: "指标、告警与恢复健康",
        href: "/overview",
        marker: "总",
        permission: "overview.read",
      },
    ],
  },
  {
    id: "operations",
    label: "运营诊断",
    items: [
      {
        id: "runs",
        label: "运行监控",
        description: "实时状态与安全诊断",
        href: "/operations/runs",
        marker: "运",
        permission: "runs.read",
      },
      {
        id: "games",
        label: "对局记录",
        description: "结果、运行与错误诊断",
        href: "/operations/games",
        marker: "局",
        permission: "games.read",
      },
    ],
  },
  {
    id: "content",
    label: "内容资产",
    items: [
      {
        id: "players",
        label: "虚拟玩家",
        description: "草稿、发布与归档",
        href: "/content/players",
        marker: "人",
        permission: "players.read",
      },
      {
        id: "voice-assets",
        label: "法官语音",
        description: "覆盖率、缺失项与试听",
        href: "/content/voice-assets",
        marker: "声",
        permission: "voice.read",
      },
      {
        id: "rules",
        label: "游戏规则",
        description: "规则版本、发布与默认配置",
        href: "/content/rules",
        marker: "规",
        permission: "rules.read",
      },
    ],
  },
  {
    id: "system",
    label: "系统安全",
    items: [
      {
        id: "jobs",
        label: "任务中心",
        description: "持久任务状态与失败诊断",
        href: "/system/jobs",
        marker: "任",
        permission: "voice.read",
      },
      {
        id: "admin-users",
        label: "后台账号",
        description: "OIDC 预授权、角色与会话",
        href: "/system/users",
        marker: "账",
        permission: "users.manage",
      },
      {
        id: "audit-events",
        label: "审计日志",
        description: "操作、资源与结果追踪",
        href: "/system/audit",
        marker: "审",
        permission: "audit.read",
      },
      {
        id: "settings",
        label: "系统设置",
        description: "安全配置与运行参数",
        href: "/system/settings",
        marker: "设",
        permission: "settings.read",
      },
    ],
  },
];

export function findAdminNavItem(pathname: string) {
  const items = adminNavigation.flatMap((section) => section.items);
  return (
    items
      .filter(
        (item) => pathname === item.href || pathname.startsWith(`${item.href}/`),
      )
      .toSorted((left, right) => right.href.length - left.href.length)[0] ?? null
  );
}
