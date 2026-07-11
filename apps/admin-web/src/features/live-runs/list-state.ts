import type {
  AdminLiveRunListParams,
  AdminLiveRunSortField,
  AdminLiveRunStatus,
} from "@/features/live-runs/types";

const RUN_STATUSES: AdminLiveRunStatus[] = [
  "queued",
  "running",
  "completed",
  "failed",
];
const SORT_FIELDS: AdminLiveRunSortField[] = ["created_at", "updated_at"];

export function liveRunListParamsFromSearch(
  searchParams: URLSearchParams,
): AdminLiveRunListParams {
  return {
    page: positiveInteger(searchParams.get("page"), 1),
    page_size: boundedPageSize(searchParams.get("page_size")),
    q: optionalValue(searchParams.get("q")),
    status: enumValue(searchParams.get("status"), RUN_STATUSES),
    rule_set_id: optionalValue(searchParams.get("rule_set_id")),
    created_from: validDate(searchParams.get("created_from")),
    created_to: validDate(searchParams.get("created_to")),
    sort: enumValue(searchParams.get("sort"), SORT_FIELDS) ?? "updated_at",
    direction: searchParams.get("direction") === "asc" ? "asc" : "desc",
  };
}

export function setLiveRunSearchValues(
  current: URLSearchParams,
  values: Record<string, string | undefined>,
) {
  const next = new URLSearchParams(current);
  Object.entries(values).forEach(([key, value]) => {
    const normalized = value?.trim();
    if (normalized) {
      next.set(key, normalized);
    } else {
      next.delete(key);
    }
  });
  return next;
}

function optionalValue(value: string | null) {
  const normalized = value?.trim();
  return normalized || undefined;
}

function enumValue<Value extends string>(
  value: string | null,
  allowed: readonly Value[],
) {
  return allowed.includes(value as Value) ? (value as Value) : undefined;
}

function positiveInteger(value: string | null, fallback: number) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function boundedPageSize(value: string | null) {
  const parsed = positiveInteger(value, 20);
  return [10, 20, 50].includes(parsed) ? parsed : 20;
}

function validDate(value: string | null) {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return undefined;
  }
  const date = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(date.valueOf()) && date.toISOString().slice(0, 10) === value
    ? value
    : undefined;
}
