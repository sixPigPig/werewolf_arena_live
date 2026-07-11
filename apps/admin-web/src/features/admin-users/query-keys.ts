import type { AdminUserListParams } from "@/features/admin-users/types";

export const adminUserKeys = {
  all: ["admin", "users"] as const,
  list: (params: AdminUserListParams) => [...adminUserKeys.all, "list", params] as const,
};
