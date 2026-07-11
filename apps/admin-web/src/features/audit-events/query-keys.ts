import type { AdminAuditParams } from "@/features/audit-events/types";

export const adminAuditKeys = {
  all: ["admin", "audit-events"] as const,
  list: (params: AdminAuditParams) => [...adminAuditKeys.all, "list", params] as const,
};
