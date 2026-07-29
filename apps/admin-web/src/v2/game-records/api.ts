import { adminApiFetch } from "@/api/client";
import {
  parseV2GameEventPage,
  parseV2GameRecordEvent,
  parseV2GameRecordSummary,
  parseV2ModelRequest,
  parseV2ModelRequestPage,
  parseV2GameRecordList,
  parseV2GameControlResult,
} from "@/v2/game-records/parsers";
import type {
  V2GameEventPage,
  V2GameControlResult,
  V2GameRecordEvent,
  V2GameRecordList,
  V2GameRecordSummary,
  V2ModelRequest,
  V2ModelRequestPage,
} from "@/v2/game-records/types";

export async function listV2GameRecords(
  page: number,
  signal?: AbortSignal,
): Promise<V2GameRecordList> {
  const value = await adminApiFetch<unknown>(
    `/api/v1/admin/v2/games?page=${page}&page_size=20`,
    { signal },
  );
  return parseV2GameRecordList(value);
}

export async function readV2GameRecordSummary(
  gameId: string,
  signal?: AbortSignal,
): Promise<V2GameRecordSummary> {
  const value = await adminApiFetch<unknown>(
    `/api/v1/admin/v2/games/${encodeURIComponent(gameId)}`,
    { signal },
  );
  return parseV2GameRecordSummary(value);
}

export async function listV2GameEvents(
  gameId: string,
  afterRecordSeq: number,
  signal?: AbortSignal,
): Promise<V2GameEventPage> {
  const value = await adminApiFetch<unknown>(
    `/api/v1/admin/v2/games/${encodeURIComponent(gameId)}/events?after_record_seq=${afterRecordSeq}&page_size=500`,
    { signal },
  );
  return parseV2GameEventPage(value);
}

export async function readV2GameEvent(
  gameId: string,
  eventId: number,
  signal?: AbortSignal,
): Promise<V2GameRecordEvent> {
  const value = await adminApiFetch<unknown>(
    `/api/v1/admin/v2/games/${encodeURIComponent(gameId)}/events/${eventId}`,
    { signal },
  );
  return parseV2GameRecordEvent(value);
}

export async function listV2ModelRequests(
  gameId: string,
  afterRecordSeq: number,
  signal?: AbortSignal,
): Promise<V2ModelRequestPage> {
  const value = await adminApiFetch<unknown>(
    `/api/v1/admin/v2/games/${encodeURIComponent(gameId)}/model-requests?after_record_seq=${afterRecordSeq}&page_size=500`,
    { signal },
  );
  return parseV2ModelRequestPage(value);
}

export async function readV2ModelRequest(
  gameId: string,
  attemptId: string,
  signal?: AbortSignal,
): Promise<V2ModelRequest> {
  const value = await adminApiFetch<unknown>(
    `/api/v1/admin/v2/games/${encodeURIComponent(gameId)}/model-requests/${encodeURIComponent(attemptId)}`,
    { signal },
  );
  return parseV2ModelRequest(value);
}

export async function stopV2Game(
  gameId: string,
  reason: string,
  csrfToken: string,
): Promise<V2GameControlResult> {
  const value = await adminApiFetch<unknown>(
    `/api/v1/admin/v2/games/${encodeURIComponent(gameId)}/stop`,
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
  return parseV2GameControlResult(value);
}
