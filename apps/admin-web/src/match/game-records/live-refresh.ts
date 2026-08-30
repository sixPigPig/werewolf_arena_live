const ACTIVE_STATES = new Set([
  "waiting_to_start",
  "ready",
  "generating",
  "broadcasting",
  "finalizing",
  "paused_model_error",
  "waiting",
  "running",
]);

export function isLiveV2StatusActive(status: string | undefined): boolean {
  return Boolean(status && ACTIVE_STATES.has(status));
}

export function liveRefreshInterval(
  status: string | undefined,
  executionState?: string,
) {
  return isLiveV2StatusActive(status) ||
    executionState === "owned" ||
    executionState === "stale"
    ? 2_000
    : false;
}
