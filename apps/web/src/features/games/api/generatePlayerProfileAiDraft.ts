import { apiFetch } from "../../../api/client";
import type {
  PlayerProfileAiDraftRequest,
  PlayerProfileAiDraftResponse,
} from "../types";

export function generatePlayerProfileAiDraft(
  request: PlayerProfileAiDraftRequest,
): Promise<PlayerProfileAiDraftResponse> {
  return apiFetch<PlayerProfileAiDraftResponse>("/api/v1/player-profiles/ai-draft", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}
