import { apiFetch } from "./client";
import type {
  LineupPreviewRequest,
  LineupPreviewResponse,
} from "../types";

export function previewGameLineup(
  request: LineupPreviewRequest,
): Promise<LineupPreviewResponse> {
  return apiFetch<LineupPreviewResponse>("/api/v1/games/lineup-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}
