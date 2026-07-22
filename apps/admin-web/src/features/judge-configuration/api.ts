import { adminApiFetch } from "@/api/client";
import { parseAdminJudgeConfiguration } from "@/features/judge-configuration/parsers";
import type { UpdateJudgeConfigurationRequest } from "@/features/judge-configuration/types";

const ADMIN_JUDGE_CONFIGURATION_PATH = "/api/v1/admin/judge-configuration";

export async function getAdminJudgeConfiguration(signal?: AbortSignal) {
  return parseAdminJudgeConfiguration(
    await adminApiFetch<unknown>(ADMIN_JUDGE_CONFIGURATION_PATH, { signal }),
  );
}

export async function updateAdminJudgeConfiguration(
  request: UpdateJudgeConfigurationRequest,
  csrfToken: string,
) {
  return parseAdminJudgeConfiguration(
    await adminApiFetch<unknown>(ADMIN_JUDGE_CONFIGURATION_PATH, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify(request),
    }),
  );
}
