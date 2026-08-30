import { adminApiFetch } from "@/api/client";
import { isAdminApiError } from "@/api/problem-details";
import {
  parseAdminModelCatalog,
  parseVolcLoginChallenge,
} from "@/features/models/parsers";
import type {
  AdminModelCatalog,
  ModelConfigurationInput,
  ModelProvider,
  VolcLoginChallenge,
} from "@/features/models/types";

const ADMIN_MODELS_PATH = "/api/v1/admin/models";

export async function listAdminModels(signal?: AbortSignal): Promise<AdminModelCatalog> {
  return parseAdminModelCatalog(
    await adminApiFetch<unknown>(ADMIN_MODELS_PATH, { signal }),
  );
}

export async function syncAgentPlanModels(
  csrfToken: string,
): Promise<AdminModelCatalog> {
  return parseAdminModelCatalog(
    await adminApiFetch<unknown>(`${ADMIN_MODELS_PATH}/agent-plan/sync`, {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    }),
  );
}

export function isAgentPlanSyncAuthRequired(error: unknown): boolean {
  if (!isAdminApiError(error)) {
    return false;
  }
  if (error.code === "admin_model_catalog_sync_auth_required") {
    return true;
  }
  return /volc sso|auth login volc-sso|火山引擎登录/i.test(error.problem.detail);
}

export async function startAgentPlanVolcLogin(
  csrfToken: string,
): Promise<VolcLoginChallenge> {
  return parseVolcLoginChallenge(
    await adminApiFetch<unknown>(`${ADMIN_MODELS_PATH}/agent-plan/login`, {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    }),
  );
}

export async function completeAgentPlanVolcLogin(
  authorizationCode: string,
  csrfToken: string,
): Promise<void> {
  await adminApiFetch<unknown>(`${ADMIN_MODELS_PATH}/agent-plan/login/complete`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken,
    },
    body: JSON.stringify({ authorization_code: authorizationCode }),
  });
}

export async function updateAdminModel(
  provider: ModelProvider,
  modelId: string,
  input: ModelConfigurationInput,
  csrfToken: string,
): Promise<void> {
  await adminApiFetch<void>(
    `${ADMIN_MODELS_PATH}/${provider}/${encodeURIComponent(modelId)}`,
    {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify(input),
    },
  );
}
