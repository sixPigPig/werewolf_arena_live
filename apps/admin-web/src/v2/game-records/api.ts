import { adminApiFetch } from "@/api/client";
import {
  parseV2GameRecordDetail,
  parseV2GameRecordList,
  parseV2GameControlResult,
} from "@/v2/game-records/parsers";
import type {
  V2GameControlResult,
  V2GameRecordDetail,
  V2GameRecordList,
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

export async function readV2GameRecord(
  gameId: string,
  signal?: AbortSignal,
): Promise<V2GameRecordDetail> {
  const value = await adminApiFetch<unknown>(
    `/api/v1/admin/v2/games/${encodeURIComponent(gameId)}`,
    { signal },
  );
  return parseV2GameRecordDetail(value);
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
