import type {
  PlayerProfileListParams,
  PlayerProfileSortField,
  PlayerProfileStatus,
} from "@/features/player-profiles/types";

const STATUSES: PlayerProfileStatus[] = ["draft", "published", "archived"];
const SORT_FIELDS: PlayerProfileSortField[] = [
  "updated_at",
  "created_at",
  "display_name",
  "display_order",
];

export function playerProfileListParamsFromSearch(
  searchParams: URLSearchParams,
): PlayerProfileListParams {
  const sort =
    enumValue(searchParams.get("sort"), SORT_FIELDS) ?? "display_order";
  const requestedDirection = searchParams.get("direction");
  const direction =
    requestedDirection === "asc" || requestedDirection === "desc"
      ? requestedDirection
      : sort === "updated_at" || sort === "created_at"
        ? "desc"
        : "asc";

  return {
    page: positiveInteger(searchParams.get("page"), 1),
    page_size: boundedPageSize(searchParams.get("page_size")),
    q: optionalValue(searchParams.get("q")),
    status: enumValue(searchParams.get("status"), STATUSES),
    model: optionalValue(searchParams.get("model")),
    personality_id: optionalValue(searchParams.get("personality_id")),
    sort,
    direction,
  };
}

export function setPlayerProfileSearchValues(
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
