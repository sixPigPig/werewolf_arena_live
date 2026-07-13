import type { RuleSetListParams, RuleSetOptions, RuleSetSortField } from "./types";
const KEYS = ["page", "page_size", "q", "status", "player_count", "sort", "direction"] as const;

type RuleSetSearchKey = (typeof KEYS)[number];
export type RuleSetSearchValues = Partial<Record<RuleSetSearchKey, string | undefined>>;

export function ruleSetListParamsFromSearch(search: URLSearchParams, options: RuleSetOptions): RuleSetListParams {
  const advertisedSorts = options.sorts.map(({ value }) => value);
  const requestedSort = `${search.get("direction") === "desc" ? "-" : ""}${search.get("sort") ?? ""}`;
  const selectedSort = advertisedSorts.includes(requestedSort as RuleSetOptions["sorts"][number]["value"])
    ? requestedSort
    : advertisedSorts[0];
  return {
    page: positive(search.get("page"), 1),
    page_size: pageSize(search.get("page_size")),
    q: optional(search.get("q")),
    status: enumValue(search.get("status"), options.statuses.map(({ value }) => value)),
    player_count: optionalPositive(search.get("player_count")),
    sort: selectedSort.replace(/^-/, "") as RuleSetSortField,
    direction: selectedSort.startsWith("-") ? "desc" : "asc",
  };
}

export function setRuleSetSearchValues(
  current: URLSearchParams,
  values: RuleSetSearchValues,
  options: RuleSetOptions,
): URLSearchParams {
  const merged = new URLSearchParams();
  for (const key of KEYS) {
    const value = Object.prototype.hasOwnProperty.call(values, key) ? values[key] : current.get(key);
    if (value !== undefined && value !== null) merged.set(key, value);
  }

  const before = ruleSetListParamsFromSearch(current, options);
  const params = ruleSetListParamsFromSearch(merged, options);
  const filterChanged =
    before.q !== params.q ||
    before.status !== params.status ||
    before.player_count !== params.player_count ||
    before.page_size !== params.page_size;
  if (filterChanged && !Object.prototype.hasOwnProperty.call(values, "page")) params.page = 1;

  return ruleSetListParamsToSearch(params);
}

function ruleSetListParamsToSearch(params: RuleSetListParams): URLSearchParams {
  const result = new URLSearchParams();
  result.set("page", String(params.page));
  result.set("page_size", String(params.page_size));
  if (params.q) result.set("q", params.q);
  if (params.status) result.set("status", params.status);
  if (params.player_count !== undefined) result.set("player_count", String(params.player_count));
  result.set("sort", params.sort);
  result.set("direction", params.direction);
  return result;
}

function optional(value: string | null): string | undefined {
  const normalized = value?.trim();
  return normalized || undefined;
}

function enumValue<T extends string>(value: string | null, allowed: readonly T[]): T | undefined {
  return allowed.includes(value as T) ? (value as T) : undefined;
}

function positive(value: string | null, fallback: number): number {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

function optionalPositive(value: string | null): number | undefined {
  if (value === null || value.trim() === "") return undefined;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
}

function pageSize(value: string | null): number {
  const parsed = positive(value, 20);
  return [10, 20, 50].includes(parsed) ? parsed : 20;
}
