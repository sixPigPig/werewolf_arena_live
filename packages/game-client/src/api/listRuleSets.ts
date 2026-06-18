import { apiFetch } from "./client";
import type { RuleSetsResponse } from "../types";

export function listRuleSets(): Promise<RuleSetsResponse> {
  return apiFetch<RuleSetsResponse>("/api/v1/games/rule-sets");
}
