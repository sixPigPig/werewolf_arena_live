import { adminApiFetch } from "@/api/client";
import {
  parseV2GameRecordDetail,
  parseV2GameRecordList,
} from "@/v2/game-records/parsers";
import type {
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
