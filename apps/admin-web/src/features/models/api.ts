import { adminApiFetch } from "@/api/client";
import { parseAdminModelCatalog } from "@/features/models/parsers";
import type {
  AdminModelCatalog,
  ModelConfigurationInput,
  ModelProvider,
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
