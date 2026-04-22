import { apiFetch } from "../../../api/client";

export type HealthResponse = {
  status: string;
};

export function getHealth() {
  return apiFetch<HealthResponse>("/api/v1/health");
}
