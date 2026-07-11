import { adminApiFetch } from "@/api/client";
import { parseAdminUser, parseAdminUserList } from "@/features/admin-users/parsers";
import type {
  AdminUserCreateInput,
  AdminUserList,
  AdminUserListParams,
  AdminUserItem,
  AdminUserUpdateInput,
} from "@/features/admin-users/types";

const PATH = "/api/v1/admin/users";

export async function listAdminUsers(params: AdminUserListParams, signal?: AbortSignal): Promise<AdminUserList> {
  const search = new URLSearchParams({
    page: String(params.page),
    page_size: String(params.page_size),
    sort: `${params.direction === "desc" ? "-" : ""}${params.sort}`,
  });
  if (params.q) search.set("q", params.q);
  if (params.role) search.set("role", params.role);
  if (params.is_active) search.set("is_active", params.is_active);
  if (params.identity_status) search.set("identity_status", params.identity_status);
  return parseAdminUserList(await adminApiFetch<unknown>(`${PATH}?${search}`, { signal }));
}

export async function createAdminUser(
  input: AdminUserCreateInput,
  csrfToken: string,
): Promise<AdminUserItem> {
  return parseAdminUser(await adminApiFetch<unknown>(PATH, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": crypto.randomUUID(),
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify(input),
  }));
}

export async function updateAdminUser(
  userId: string,
  input: AdminUserUpdateInput,
  csrfToken: string,
): Promise<AdminUserItem> {
  return parseAdminUser(await adminApiFetch<unknown>(`${PATH}/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify(input),
  }));
}

export async function revokeAdminUserSessions(
  userId: string,
  reason: string,
  csrfToken: string,
): Promise<{ user_id: string; revoked_count: number }> {
  return adminApiFetch(`${PATH}/${encodeURIComponent(userId)}/revoke-sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
    body: JSON.stringify({ reason }),
  });
}
