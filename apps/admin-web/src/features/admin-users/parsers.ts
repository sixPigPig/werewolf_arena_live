import { AdminApiError } from "@/api/problem-details";
import type { AdminRole } from "@/features/auth/types";
import type { AdminUserItem, AdminUserList } from "@/features/admin-users/types";

const ROLES = new Set<AdminRole>(["viewer", "content_editor", "operator", "super_admin"]);
const FORBIDDEN_KEYS = new Set([
  "auth_provider",
  "auth_subject",
  "token",
  "token_hash",
  "csrf_token",
  "ip_address",
  "user_agent",
]);

export function parseAdminUserList(value: unknown): AdminUserList {
  rejectForbidden(value);
  const record = recordValue(value);
  const pagination = recordValue(record.pagination);
  return {
    items: arrayValue(record.items).map(parseAdminUser),
    pagination: {
      page: positiveInteger(pagination.page),
      page_size: positiveInteger(pagination.page_size),
      total: nonNegativeInteger(pagination.total),
      pages: nonNegativeInteger(pagination.pages),
    },
  };
}

export function parseAdminUser(value: unknown): AdminUserItem {
  rejectForbidden(value);
  const record = recordValue(value);
  const role = stringValue(record.role) as AdminRole;
  const identityStatus = stringValue(record.identity_status);
  if (!ROLES.has(role) || !["unbound", "bound"].includes(identityStatus)) throw invalid();
  return {
    id: stringValue(record.id),
    email: stringValue(record.email),
    display_name: stringValue(record.display_name),
    role,
    is_active: booleanValue(record.is_active),
    identity_status: identityStatus as AdminUserItem["identity_status"],
    active_session_count: nonNegativeInteger(record.active_session_count),
    last_session_at: nullableDate(record.last_session_at),
    created_at: dateValue(record.created_at),
    updated_at: dateValue(record.updated_at),
    version: positiveInteger(record.version),
  };
}

function rejectForbidden(value: unknown): void {
  if (Array.isArray(value)) return value.forEach(rejectForbidden);
  if (!value || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value)) {
    const normalized = key.toLowerCase();
    if (
      FORBIDDEN_KEYS.has(normalized) ||
      normalized.includes("token") ||
      normalized.includes("secret") ||
      normalized.startsWith("auth_")
    ) throw invalid();
    rejectForbidden(child);
  }
}

function recordValue(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw invalid();
  return value as Record<string, unknown>;
}
function arrayValue(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw invalid();
  return value;
}
function stringValue(value: unknown): string {
  if (typeof value !== "string" || !value) throw invalid();
  return value;
}
function booleanValue(value: unknown): boolean {
  if (typeof value !== "boolean") throw invalid();
  return value;
}
function positiveInteger(value: unknown): number {
  if (!Number.isInteger(value) || Number(value) < 1) throw invalid();
  return Number(value);
}
function nonNegativeInteger(value: unknown): number {
  if (!Number.isInteger(value) || Number(value) < 0) throw invalid();
  return Number(value);
}
function dateValue(value: unknown): string {
  const text = stringValue(value);
  if (!Number.isFinite(Date.parse(text))) throw invalid();
  return text;
}
function nullableDate(value: unknown): string | null {
  return value === null ? null : dateValue(value);
}
function invalid() {
  return new AdminApiError({
    problem: {
      type: "about:blank",
      title: "账号响应无效",
      status: 502,
      detail: "后台账号数据不完整或包含受限字段。",
      code: "admin_invalid_user_response",
      request_id: null,
    },
  });
}
