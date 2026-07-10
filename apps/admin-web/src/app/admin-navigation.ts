export type AdminPermission =
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
    id: "content",
    label: "已接入功能",
    items: [
      {
        id: "players",
        label: "虚拟玩家",
        description: "草稿、发布与归档",
        href: "/content/players",
        marker: "人",
        permission: "players.read",
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
