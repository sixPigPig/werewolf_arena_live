export type AdminPermission =
  | "overview.read"
  | "runs.read"
  | "games.read"
  | "players.read"
  | "voice.read"
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
    label: "总览",
    items: [
      {
        id: "overview",
        label: "运营总览",
        description: "运行、内容与异常概况",
        href: "/overview",
        marker: "概",
        permission: "overview.read",
      },
    ],
  },
  {
    id: "operations",
    label: "对局运营",
    items: [
      {
        id: "runs",
        label: "实时运行",
        description: "运行状态、事件与恢复",
        href: "/operations/runs",
        marker: "运",
        permission: "runs.read",
      },
      {
        id: "games",
        label: "对局记录",
        description: "复盘、模型诊断与筛选",
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
        id: "voice",
        label: "法官语音",
        description: "资产状态、试听与生成",
        href: "/content/voice-assets",
        marker: "声",
        permission: "voice.read",
      },
    ],
  },
  {
    id: "access",
    label: "权限治理",
    items: [
      {
        id: "users",
        label: "后台用户",
        description: "账号状态与角色分配",
        href: "/access/users",
        marker: "权",
        permission: "users.manage",
      },
      {
        id: "roles",
        label: "角色权限",
        description: "固定角色与能力矩阵",
        href: "/access/roles",
        marker: "角",
        permission: "roles.manage",
      },
    ],
  },
  {
    id: "system",
    label: "系统",
    items: [
      {
        id: "audit",
        label: "审计日志",
        description: "高风险操作追踪",
        href: "/system/audit-logs",
        marker: "审",
        permission: "audit.read",
      },
      {
        id: "settings",
        label: "系统配置",
        description: "只读配置与健康信息",
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
