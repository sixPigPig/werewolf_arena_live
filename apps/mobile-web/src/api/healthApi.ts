import { apiFetch } from "./client";
import type { HealthResponse } from "./types";

export function getHealth() {
  return apiFetch<HealthResponse>("/api/v1/health");
}
