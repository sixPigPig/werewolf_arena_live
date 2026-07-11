import type { AdminRole } from "@/features/auth/types";

export type AdminIdentityStatus = "unbound" | "bound";

export type AdminUserItem = {
  id: string;
  email: string;
  display_name: string;
  role: AdminRole;
  is_active: boolean;
  identity_status: AdminIdentityStatus;
  active_session_count: number;
  last_session_at: string | null;
  created_at: string;
  updated_at: string;
  version: number;
};

export type AdminUserList = {
  items: AdminUserItem[];
  pagination: { page: number; page_size: number; total: number; pages: number };
};

export type AdminUserListParams = {
  page: number;
  page_size: number;
  q?: string;
  role?: AdminRole;
  is_active?: "true" | "false";
  identity_status?: AdminIdentityStatus;
  sort: "display_name" | "email" | "updated_at" | "created_at";
  direction: "asc" | "desc";
};

export type AdminUserCreateInput = {
  email: string;
  display_name: string;
  role: AdminRole;
  reason: string;
};

export type AdminUserUpdateInput = {
  expected_version: number;
  display_name: string;
  role: AdminRole;
  is_active: boolean;
  reason: string;
};
