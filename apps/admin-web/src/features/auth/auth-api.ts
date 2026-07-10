import { adminApiFetch } from "@/api/client";
import { AdminApiError } from "@/api/problem-details";
import type {
  AdminRole,
  AdminSession,
  AdminUser,
} from "@/features/auth/types";

const ADMIN_AUTH_BASE_PATH = "/api/v1/admin";
const ADMIN_ROLES: AdminRole[] = [
  "viewer",
  "content_editor",
  "operator",
  "super_admin",
];

export async function getAdminSession() {
  const value = await adminApiFetch<unknown>(`${ADMIN_AUTH_BASE_PATH}/me`, {
    notifyOnUnauthorized: false,
  });
  return parseAdminSession(value);
}

export async function createAdminDevSession() {
  const value = await adminApiFetch<unknown>(
    `${ADMIN_AUTH_BASE_PATH}/dev-login`,
    {
      method: "POST",
      notifyOnUnauthorized: false,
    },
  );
  return parseAdminSession(value);
}

export async function deleteAdminSession(csrfToken: string) {
  await adminApiFetch<void>(`${ADMIN_AUTH_BASE_PATH}/logout`, {
    headers: { "X-CSRF-Token": csrfToken },
    method: "POST",
  });
}

export function parseAdminSession(value: unknown): AdminSession {
  if (!isRecord(value)) {
    throw invalidSessionResponse();
  }

  const user = parseAdminUser(value.user);
  const permissions = value.permissions;
  const csrfToken = value.csrf_token;
  const sessionExpiresAt = value.session_expires_at;

  if (
    !Array.isArray(permissions) ||
    !permissions.every((permission) => typeof permission === "string") ||
    typeof csrfToken !== "string" ||
    csrfToken.length === 0 ||
    typeof sessionExpiresAt !== "string" ||
    !Number.isFinite(Date.parse(sessionExpiresAt))
  ) {
    throw invalidSessionResponse();
  }

  return {
    user,
    permissions: [...permissions],
    csrf_token: csrfToken,
    session_expires_at: sessionExpiresAt,
  };
}

function parseAdminUser(value: unknown): AdminUser {
  if (!isRecord(value)) {
    throw invalidSessionResponse();
  }

  const { display_name: displayName, email, id, role } = value;
  if (
    typeof id !== "string" ||
    id.length === 0 ||
    typeof email !== "string" ||
    email.length === 0 ||
    typeof displayName !== "string" ||
    displayName.length === 0 ||
    typeof role !== "string" ||
    !ADMIN_ROLES.includes(role as AdminRole)
  ) {
    throw invalidSessionResponse();
  }

  return {
    id,
    email,
    display_name: displayName,
    role: role as AdminRole,
  };
}

function invalidSessionResponse() {
  return new AdminApiError({
    problem: {
      type: "about:blank",
      title: "会话响应无效",
      status: 502,
      detail: "后台返回的会话信息不完整或格式错误。",
      code: "admin_invalid_session_response",
      request_id: null,
    },
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
