import type { AdminPermission } from "@/app/admin-navigation";

export function hasAdminPermission(
  permissions: readonly string[],
  permission: AdminPermission,
) {
  return permissions.includes("*") || permissions.includes(permission);
}
