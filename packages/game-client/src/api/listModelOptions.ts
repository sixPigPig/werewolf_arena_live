import { apiFetch } from "./client";
import type { ModelOptionsResponse } from "../types";

export function listModelOptions(): Promise<ModelOptionsResponse> {
  return apiFetch<ModelOptionsResponse>("/api/v1/games/model-options");
}
