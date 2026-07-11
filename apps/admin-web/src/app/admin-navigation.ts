export type AdminPermission =
  | "games.read"
  | "runs.read"
  | "voice.read"
  | "voice.generate_missing"
  | "voice.regenerate_all"
  | "players.read"
  | "players.write"
  | "players.publish"
  | "players.archive"
  | "players.ai_generate";

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
