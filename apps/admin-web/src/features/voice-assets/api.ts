import { adminApiFetch } from "@/api/client";
import { parseAdminJudgeVoiceJob, parseAdminJudgeVoiceList } from "@/features/voice-assets/parsers";
import type {
  AdminJudgeVoiceList,
  AdminJudgeVoiceListParams,
  AdminJudgeVoiceJob,
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

export async function createAdminJudgeVoiceJob(
  mode: "missing" | "all",
  csrfToken: string,
): Promise<AdminJudgeVoiceJob> {
  const value = await adminApiFetch<unknown>(
    "/api/v1/admin/judge-voice-generation-jobs",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
        "Idempotency-Key": crypto.randomUUID(),
      },
      body: JSON.stringify({ mode }),
    },
  );
  return parseAdminJudgeVoiceJob(value);
}

export async function getAdminJudgeVoiceJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<AdminJudgeVoiceJob> {
  const value = await adminApiFetch<unknown>(
    `/api/v1/admin/jobs/${encodeURIComponent(jobId)}`,
    { signal },
  );
  return parseAdminJudgeVoiceJob(value);
}

function appendOptional(
  search: URLSearchParams,
  key: string,
  value: string | undefined,
) {
  const normalized = value?.trim();
  if (normalized) search.set(key, normalized);
}
