const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export function createRunEventSource(runId: string, afterId?: number) {
  const params = afterId === undefined ? "" : `?after_id=${afterId}`;
  return new EventSource(`${API_BASE_URL}/api/v1/games/runs/${runId}/events${params}`);
}
