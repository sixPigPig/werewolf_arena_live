import { adminApiFetch } from "@/api/client";
import {
  parseGameEventPage,
  parseGameRecordEvent,
  parseGameRecordSummary,
  parseModelRequest,
  parseModelRequestPage,
  parseModelActionRetryResult,
  parseGameRecordList,
  parseGameControlResult,
} from "@/match/game-records/parsers";
import type {
  GameEventPage,
  GameControlResult,
  GameRecordEvent,
  GameRecordList,
  GameRecordSummary,
  ModelRequest,
  ModelActionRetryResult,
  ModelRequestPage,
} from "@/match/game-records/types";

export async function listGameRecords(
  page: number,
  signal?: AbortSignal,
): Promise<GameRecordList> {
  const value = await adminApiFetch<unknown>(
    `/api/v1/admin/v2/games?page=${page}&page_size=20`,
    { signal },
  );
  return parseGameRecordList(value);
}

export async function readGameRecordSummary(
  gameId: string,
  signal?: AbortSignal,
): Promise<GameRecordSummary> {
  const value = await adminApiFetch<unknown>(
    `/api/v1/admin/v2/games/${encodeURIComponent(gameId)}`,
    { signal },
  );
  return parseGameRecordSummary(value);
}

export async function listGameEvents(
  gameId: string,
  afterRecordSeq: number,
  signal?: AbortSignal,
): Promise<GameEventPage> {
  const value = await adminApiFetch<unknown>(
    `/api/v1/admin/v2/games/${encodeURIComponent(gameId)}/events?after_record_seq=${afterRecordSeq}&page_size=500`,
    { signal },
  );
  return parseGameEventPage(value);
}

export async function readGameEvent(
  gameId: string,
  eventId: number,
  signal?: AbortSignal,
): Promise<GameRecordEvent> {
  const value = await adminApiFetch<unknown>(
    `/api/v1/admin/v2/games/${encodeURIComponent(gameId)}/events/${eventId}`,
    { signal },
  );
  return parseGameRecordEvent(value);
}

export async function listModelRequests(
  gameId: string,
  afterRecordSeq: number,
  signal?: AbortSignal,
): Promise<ModelRequestPage> {
  const value = await adminApiFetch<unknown>(
    `/api/v1/admin/v2/games/${encodeURIComponent(gameId)}/model-requests?after_record_seq=${afterRecordSeq}&page_size=500`,
    { signal },
  );
  return parseModelRequestPage(value);
}

export async function readModelRequest(
  gameId: string,
  attemptId: string,
  signal?: AbortSignal,
): Promise<ModelRequest> {
  const value = await adminApiFetch<unknown>(
    `/api/v1/admin/v2/games/${encodeURIComponent(gameId)}/model-requests/${encodeURIComponent(attemptId)}`,
    { signal },
  );
  return parseModelRequest(value);
}

export async function stopGame(
  gameId: string,
  reason: string,
  csrfToken: string,
): Promise<GameControlResult> {
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
  return parseGameControlResult(value);
}

export async function retryModelAction(
  gameId: string,
  reason: string,
  csrfToken: string,
): Promise<ModelActionRetryResult> {
  const value = await adminApiFetch<unknown>(
    `/api/v1/admin/v2/games/${encodeURIComponent(gameId)}/retry-model-action`,
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
  return parseModelActionRetryResult(value);
}
