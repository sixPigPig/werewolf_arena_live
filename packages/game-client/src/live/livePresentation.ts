import type { LiveGameEvent } from "../types";

/**
 * Returns the semantic event stream used to derive spectator-facing state.
 *
 * A recovery run may re-emit a durable result with the same presentation ID
 * after the parent occurrence has already reached clients. Transport callers
 * still retain every event for cursors, terminal windows and diagnostics; the
 * display projection keeps only the latest occurrence of that semantic result.
 * Legacy events without an explicit ID are never content-deduplicated.
 */
export function projectLivePresentationEvents(
  events: LiveGameEvent[],
): LiveGameEvent[] {
  const latestIndexByPresentationId = new Map<string, number>();
  let hasDuplicatePresentation = false;

  events.forEach((event, index) => {
    const presentationId = presentationIdForEvent(event);
    if (!presentationId) {
      return;
    }
    if (latestIndexByPresentationId.has(presentationId)) {
      hasDuplicatePresentation = true;
    }
    latestIndexByPresentationId.set(presentationId, index);
  });

  if (!hasDuplicatePresentation) {
    return events;
  }

  return events.filter((event, index) => {
    const presentationId = presentationIdForEvent(event);
    return (
      !presentationId || latestIndexByPresentationId.get(presentationId) === index
    );
  });
}

function presentationIdForEvent(event: LiveGameEvent): string {
  const payload = event.payload;
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return "";
  }
  const presentationId = payload.presentation_id;
  return typeof presentationId === "string" && presentationId.trim()
    ? presentationId
    : "";
}
