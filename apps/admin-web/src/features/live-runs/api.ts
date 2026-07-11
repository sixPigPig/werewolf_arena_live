import { adminApiFetch } from "@/api/client";
import {
  parseAdminLiveRunDebug,
  parseAdminLiveRunControl,
  parseAdminLiveRunDetail,
  parseAdminLiveRunList,
} from "@/features/live-runs/parsers";
import type {
  AdminLiveRunDebug,
  AdminLiveRunControlAction,
  AdminLiveRunControlResult,
  AdminLiveRunDetail,
  AdminLiveRunList,
  AdminLiveRunListParams,
} from "@/features/live-runs/types";

const ADMIN_LIVE_RUNS_PATH = "/api/v1/admin/live-runs";

export async function listAdminLiveRuns(
  params: AdminLiveRunListParams,
  signal?: AbortSignal,
): Promise<AdminLiveRunList> {
  const searchParams = new URLSearchParams({
    page: String(params.page),
    page_size: String(params.page_size),
    sort: `${params.direction === "desc" ? "-" : ""}${params.sort}`,
  });
  appendOptional(searchParams, "q", params.q);
  appendOptional(searchParams, "status", params.status);
  appendOptional(searchParams, "rule_set_id", params.rule_set_id);
  appendOptional(
    searchParams,
    "created_from",
    params.created_from ? startOfLocalDay(params.created_from) : undefined,
  );
  appendOptional(
    searchParams,
    "created_to",
    params.created_to ? endOfLocalDay(params.created_to) : undefined,
  );
  const value = await adminApiFetch<unknown>(
    `${ADMIN_LIVE_RUNS_PATH}?${searchParams.toString()}`,
    { signal },
  );
  return parseAdminLiveRunList(value);
}

export async function getAdminLiveRun(
  runId: string,
  signal?: AbortSignal,
): Promise<AdminLiveRunDetail> {
  const value = await adminApiFetch<unknown>(
    `${ADMIN_LIVE_RUNS_PATH}/${encodeURIComponent(runId)}`,
    { signal },
  );
  return parseAdminLiveRunDetail(value);
}

export async function getAdminLiveRunDebug(
  runId: string,
  signal?: AbortSignal,
): Promise<AdminLiveRunDebug> {
  const value = await adminApiFetch<unknown>(
    `${ADMIN_LIVE_RUNS_PATH}/${encodeURIComponent(runId)}/debug`,
    { signal },
  );
  return parseAdminLiveRunDebug(value);
}

export async function controlAdminLiveRun(
  runId: string,
  action: AdminLiveRunControlAction,
  reason: string,
  csrfToken: string,
): Promise<AdminLiveRunControlResult> {
  const value = await adminApiFetch<unknown>(
    `${ADMIN_LIVE_RUNS_PATH}/${encodeURIComponent(runId)}/${action}`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": crypto.randomUUID(),
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify({ reason }),
    },
  );
  return parseAdminLiveRunControl(value);
}

function appendOptional(
  params: URLSearchParams,
  key: string,
  value: string | undefined,
) {
  const normalized = value?.trim();
  if (normalized) {
    params.set(key, normalized);
  }
}

function startOfLocalDay(value: string) {
  const [year, month, day] = dateParts(value);
  return new Date(year, month - 1, day, 0, 0, 0, 0).toISOString();
}

function endOfLocalDay(value: string) {
  const [year, month, day] = dateParts(value);
  return new Date(year, month - 1, day, 23, 59, 59, 999).toISOString();
}

function dateParts(value: string): [number, number, number] {
  const [year, month, day] = value.split("-").map(Number);
  return [year ?? 0, month ?? 0, day ?? 0];
}
