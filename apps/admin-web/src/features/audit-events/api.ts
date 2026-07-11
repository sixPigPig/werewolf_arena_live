import { adminApiFetch } from "@/api/client";
import { AdminApiError } from "@/api/problem-details";
import type { AdminAuditEvent, AdminAuditList, AdminAuditParams } from "@/features/audit-events/types";

export async function listAdminAuditEvents(params: AdminAuditParams, signal?: AbortSignal): Promise<AdminAuditList> {
  const search = new URLSearchParams({
    page: String(params.page),
    page_size: String(params.page_size),
    sort: params.direction === "desc" ? "-created_at" : "created_at",
  });
  for (const key of ["q", "action", "result", "resource_type", "created_from", "created_to"] as const) {
    const value = params[key];
    if (value) search.set(key, auditQueryValue(key, value));
  }
  return parseAuditList(await adminApiFetch<unknown>(`/api/v1/admin/audit-events?${search}`, { signal }));
}

function auditQueryValue(key: keyof AdminAuditParams, value: string) {
  if (key === "created_from" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return new Date(`${value}T00:00:00`).toISOString();
  }
  if (key === "created_to" && /^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return new Date(`${value}T23:59:59.999`).toISOString();
  }
  return value;
}

function parseAuditList(value: unknown): AdminAuditList {
  rejectForbidden(value);
  const record = asRecord(value);
  const pagination = asRecord(record.pagination);
  if (!Array.isArray(record.items)) throw invalid();
  return {
    items: record.items.map(parseEvent),
    pagination: {
      page: integer(pagination.page, 1),
      page_size: integer(pagination.page_size, 1),
      total: integer(pagination.total, 0),
      pages: integer(pagination.pages, 0),
    },
  };
}

function parseEvent(value: unknown): AdminAuditEvent {
  const record = asRecord(value);
  const actor = record.actor === null ? null : asRecord(record.actor);
  return {
    id: text(record.id),
    actor: actor ? { id: text(actor.id), email: text(actor.email), display_name: text(actor.display_name) } : null,
    action: text(record.action),
    resource_type: text(record.resource_type),
    resource_id: nullableText(record.resource_id),
    result: text(record.result),
    reason: nullableText(record.reason),
    request_id: nullableText(record.request_id),
    created_at: date(record.created_at),
  };
}

function rejectForbidden(value: unknown): void {
  if (Array.isArray(value)) return value.forEach(rejectForbidden);
  if (!value || typeof value !== "object") return;
  for (const [key, child] of Object.entries(value)) {
    const normalized = key.toLowerCase();
    if (["before", "after", "ip_address", "auth_subject", "auth_provider"].includes(normalized) || normalized.includes("token") || normalized.includes("secret")) throw invalid();
    rejectForbidden(child);
  }
}
function asRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw invalid();
  return value as Record<string, unknown>;
}
function text(value: unknown): string { if (typeof value !== "string" || !value) throw invalid(); return value; }
function nullableText(value: unknown): string | null { return value === null ? null : text(value); }
function integer(value: unknown, minimum: number): number { if (!Number.isInteger(value) || Number(value) < minimum) throw invalid(); return Number(value); }
function date(value: unknown): string { const result = text(value); if (!Number.isFinite(Date.parse(result))) throw invalid(); return result; }
function invalid() { return new AdminApiError({ problem: { type: "about:blank", title: "审计响应无效", status: 502, detail: "审计数据不完整或包含受限字段。", code: "admin_invalid_audit_response", request_id: null } }); }
