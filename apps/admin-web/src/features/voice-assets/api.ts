import { adminApiFetch } from "@/api/client";
import { parseAdminJudgeVoiceList } from "@/features/voice-assets/parsers";
import type {
  AdminJudgeVoiceList,
  AdminJudgeVoiceListParams,
} from "@/features/voice-assets/types";

const ADMIN_JUDGE_VOICE_PATH = "/api/v1/admin/judge-voice-lines";

export async function listAdminJudgeVoiceLines(
  params: AdminJudgeVoiceListParams,
  signal?: AbortSignal,
): Promise<AdminJudgeVoiceList> {
  const search = new URLSearchParams({
    page: String(params.page),
    page_size: String(params.page_size),
    sort: `${params.direction === "desc" ? "-" : ""}${params.sort}`,
  });
  appendOptional(search, "q", params.q);
  appendOptional(search, "category", params.category);
  appendOptional(search, "availability", params.availability);
  const value = await adminApiFetch<unknown>(
    `${ADMIN_JUDGE_VOICE_PATH}?${search.toString()}`,
    { signal },
  );
  return parseAdminJudgeVoiceList(value);
}

function appendOptional(
  search: URLSearchParams,
  key: string,
  value: string | undefined,
) {
  const normalized = value?.trim();
  if (normalized) search.set(key, normalized);
}
