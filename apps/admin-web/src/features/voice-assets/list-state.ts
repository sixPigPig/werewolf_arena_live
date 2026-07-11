import type {
  AdminJudgeVoiceAvailability,
  AdminJudgeVoiceListParams,
  AdminJudgeVoiceSortField,
} from "@/features/voice-assets/types";

const AVAILABILITY: AdminJudgeVoiceAvailability[] = ["available", "missing"];
const SORT_FIELDS: AdminJudgeVoiceSortField[] = ["category", "id", "byte_size"];

export function judgeVoiceListParamsFromSearch(
  search: URLSearchParams,
): AdminJudgeVoiceListParams {
  return {
    page: positiveInteger(search.get("page"), 1),
    page_size: pageSize(search.get("page_size")),
    q: optionalValue(search.get("q")),
    category: optionalValue(search.get("category")),
    availability: enumValue(search.get("availability"), AVAILABILITY),
    sort: enumValue(search.get("sort"), SORT_FIELDS) ?? "category",
    direction: search.get("direction") === "desc" ? "desc" : "asc",
  };
}

export function setJudgeVoiceSearchValues(
  current: URLSearchParams,
  values: Record<string, string | undefined>,
) {
  const next = new URLSearchParams(current);
  Object.entries(values).forEach(([key, value]) => {
    const normalized = value?.trim();
    if (normalized) next.set(key, normalized);
    else next.delete(key);
  });
  return next;
}

function optionalValue(value: string | null) {
  const normalized = value?.trim();
  return normalized || undefined;
}

function enumValue<Value extends string>(value: string | null, allowed: readonly Value[]) {
  return allowed.includes(value as Value) ? (value as Value) : undefined;
}

function positiveInteger(value: string | null, fallback: number) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function pageSize(value: string | null) {
  const parsed = positiveInteger(value, 20);
  return [20, 50, 100].includes(parsed) ? parsed : 20;
}
