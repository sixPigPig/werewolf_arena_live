import type { V2ModelRequest } from "@/v2/game-records/types";

export type V2ModelContextPresentationKind =
  | "v11_canonical"
  | "v12_compact"
  | "unsupported";

export type V2ModelContextContractEnvelope = Pick<
  V2ModelRequest,
  | "expanded_known_events"
  | "known_events_expansion_status"
  | "model_context_schema_version"
  | "model_view_selector_version"
  | "prompt_projection"
  | "prompt_template_version"
  | "request_payload"
>;

export function classifyV2ModelContextContract(
  request: V2ModelContextContractEnvelope,
  promptContext = structuredModelContextFromRequestPayload(
    request.request_payload,
  ),
): V2ModelContextPresentationKind {
  const projection = request.prompt_projection;
  const knownEvents = isRecord(promptContext?.known_events)
    ? promptContext.known_events
    : null;
  const commonTupleMatches =
    projection !== null &&
    numericField(projection, "ledger_schema_version") === 5 &&
    numericField(projection, "model_view_schema_version") === 5 &&
    numericField(projection, "model_view_selector_version") === 2 &&
    request.model_view_selector_version === 2;
  if (
    commonTupleMatches &&
    request.model_context_schema_version === 11 &&
    (request.prompt_template_version === 3 ||
      request.prompt_template_version === 4) &&
    numericField(projection, "model_context_schema_version") === 11 &&
    numericField(projection, "prompt_template_version") ===
      request.prompt_template_version &&
    numericField(projection, "known_events_schema_version") === 5 &&
    promptContext?.model_context_schema_version === 11 &&
    promptContext.prompt_template_version === request.prompt_template_version &&
    isCanonicalKnownEventsV5(knownEvents)
  ) {
    return "v11_canonical";
  }
  if (
    commonTupleMatches &&
    request.model_context_schema_version === 12 &&
    request.prompt_template_version === 5 &&
    request.known_events_expansion_status === "verified" &&
    isCanonicalKnownEventsV5(request.expanded_known_events) &&
    numericField(projection, "model_context_schema_version") === 12 &&
    numericField(projection, "prompt_template_version") === 5 &&
    numericField(projection, "known_events_schema_version") === 6 &&
    promptContext?.model_context_schema_version === 12 &&
    promptContext.prompt_template_version === 5 &&
    knownEvents?.schema_version === 6 &&
    knownEvents.encoding === "lossless_refs_v1"
  ) {
    return "v12_compact";
  }
  return "unsupported";
}

export function structuredModelContextFromRequestPayload(
  requestPayload: Record<string, unknown> | null,
): Record<string, unknown> | null {
  if (requestPayload === null) return null;
  const candidateTexts: string[] = [];
  for (const containerKey of ["input", "messages"] as const) {
    const items = requestPayload[containerKey];
    if (!Array.isArray(items)) continue;
    for (const item of items) {
      if (!isRecord(item) || item.role !== "user") continue;
      const content = item.content;
      if (typeof content === "string") {
        candidateTexts.push(content);
      } else if (Array.isArray(content)) {
        for (const part of content) {
          if (typeof part === "string") {
            candidateTexts.push(part);
          } else if (isRecord(part) && typeof part.text === "string") {
            candidateTexts.push(part.text);
          }
        }
      }
    }
  }
  for (let index = candidateTexts.length - 1; index >= 0; index -= 1) {
    const parsed = parseStructuredModelContext(candidateTexts[index]);
    if (parsed !== null) return parsed;
  }
  return null;
}

function parseStructuredModelContext(
  text: string,
): Record<string, unknown> | null {
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start < 0 || end <= start) return null;
  try {
    const value: unknown = JSON.parse(text.slice(start, end + 1));
    return isRecord(value) ? value : null;
  } catch {
    return null;
  }
}

function numericField(
  value: Record<string, unknown> | null,
  key: string,
): number | null {
  const candidate = value?.[key];
  return typeof candidate === "number" && Number.isFinite(candidate)
    ? candidate
    : null;
}

function isCanonicalKnownEventsV5(value: unknown): boolean {
  return (
    isRecord(value) &&
    value.schema_version === 5 &&
    Array.isArray(value.events) &&
    Array.isArray(value.questions) &&
    Array.isArray(value.relations)
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
