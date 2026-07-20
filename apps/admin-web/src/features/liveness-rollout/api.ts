import { adminApiFetch } from "@/api/client";
import { parseLivenessRolloutConfig } from "@/features/liveness-rollout/parsers";
import type {
  LivenessRolloutConfig,
  LivenessRolloutUpdate,
} from "@/features/liveness-rollout/types";

const PATH = "/api/v1/admin/liveness-rollout";

export async function getLivenessRollout(signal?: AbortSignal): Promise<LivenessRolloutConfig> {
  return parseLivenessRolloutConfig(
    await adminApiFetch<unknown>(PATH, { signal }),
  );
}

export async function updateLivenessRollout(
  input: LivenessRolloutUpdate,
  csrfToken: string,
): Promise<LivenessRolloutConfig> {
  return parseLivenessRolloutConfig(
    await adminApiFetch<unknown>(PATH, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken,
      },
      body: JSON.stringify(input),
    }),
  );
}
