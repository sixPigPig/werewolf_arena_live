import { adminApiFetch } from "@/api/client";
import {
  parseAdminGameDebug,
  parseAdminGameDetail,
  parseAdminGameList,
  parseAdminGameQualityIssues,
  parseAdminGameQualityRetry,
} from "@/features/game-records/parsers";
import type {
  AdminGameDebug,
  AdminGameDetail,
  AdminGameList,
  AdminGameListParams,
  AdminGameQualityIssues,
  AdminGameQualityRetry,
} from "@/features/game-records/types";

const ADMIN_GAMES_PATH = "/api/v1/admin/games";

export async function listAdminGames(
  params: AdminGameListParams,
  signal?: AbortSignal,
): Promise<AdminGameList> {
  const searchParams = new URLSearchParams({
    page: String(params.page),
    page_size: String(params.page_size),
    sort: `${params.direction === "desc" ? "-" : ""}${params.sort}`,
  });
  appendOptional(searchParams, "q", params.q);
  appendOptional(searchParams, "status", params.status);
  appendOptional(searchParams, "winner", params.winner);
  appendOptional(searchParams, "rule_set_id", params.rule_set_id);
  appendOptional(searchParams, "run_status", params.run_status);
  appendOptional(
    searchParams,
    "created_from",
    params.created_from ? startOfUtcDay(params.created_from) : undefined,
  );
  appendOptional(
    searchParams,
    "created_to",
    params.created_to ? endOfUtcDay(params.created_to) : undefined,
  );
  const value = await adminApiFetch<unknown>(
    `${ADMIN_GAMES_PATH}?${searchParams.toString()}`,
    { signal },
  );
  return parseAdminGameList(value);
}

export async function getAdminGame(
  sessionId: string,
  signal?: AbortSignal,
): Promise<AdminGameDetail> {
  const value = await adminApiFetch<unknown>(
    `${ADMIN_GAMES_PATH}/${encodeURIComponent(sessionId)}`,
    { signal },
  );
  return parseAdminGameDetail(value);
}

export async function deleteAdminGame(
  sessionId: string,
  csrfToken: string,
): Promise<void> {
  await adminApiFetch<void>(
    `${ADMIN_GAMES_PATH}/${encodeURIComponent(sessionId)}`,
    {
      method: "DELETE",
      headers: { "X-CSRF-Token": csrfToken },
    },
  );
}

export async function getAdminGameDebug(
  sessionId: string,
  signal?: AbortSignal,
): Promise<AdminGameDebug> {
  const value = await adminApiFetch<unknown>(
    `${ADMIN_GAMES_PATH}/${encodeURIComponent(sessionId)}/debug`,
    { signal },
  );
  return parseAdminGameDebug(value);
}

export async function getAdminGameQualityIssues(
  sessionId: string,
  signal?: AbortSignal,
): Promise<AdminGameQualityIssues> {
  const value = await adminApiFetch<unknown>(
    `${ADMIN_GAMES_PATH}/${encodeURIComponent(sessionId)}/quality-evaluation/issues`,
    { signal },
  );
  return parseAdminGameQualityIssues(value);
}

export async function retryAdminGameQualityEvaluation(
  sessionId: string,
  csrfToken: string,
): Promise<AdminGameQualityRetry> {
  const value = await adminApiFetch<unknown>(
    `${ADMIN_GAMES_PATH}/${encodeURIComponent(sessionId)}/quality-evaluation/retry`,
    {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    },
  );
  return parseAdminGameQualityRetry(value);
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

function startOfUtcDay(value: string) {
  const [year, month, day] = dateParts(value);
  return new Date(year, month - 1, day, 0, 0, 0, 0).toISOString();
}

function endOfUtcDay(value: string) {
  const [year, month, day] = dateParts(value);
  return new Date(year, month - 1, day, 23, 59, 59, 999).toISOString();
}

function dateParts(value: string): [number, number, number] {
  const [year, month, day] = value.split("-").map(Number);
  return [year ?? 0, month ?? 0, day ?? 0];
}
