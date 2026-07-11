import { adminApiFetch } from "@/api/client";
import {
  parseAdminJobList,
  parseAdminOverview,
  parseAdminSearch,
  parseAdminSettings,
} from "@/features/dashboard/parsers";
import type { AdminJobList, AdminJobStatus } from "@/features/dashboard/types";

export async function getAdminOverview(signal?: AbortSignal) {
  return parseAdminOverview(await adminApiFetch<unknown>("/api/v1/admin/overview", { signal }));
}
export async function listAdminJobs(
  params: { page: number; page_size: number; status?: AdminJobStatus },
  signal?: AbortSignal,
): Promise<AdminJobList> {
  const search = new URLSearchParams({ page: String(params.page), page_size: String(params.page_size) });
  if (params.status) search.set("status", params.status);
  return parseAdminJobList(await adminApiFetch<unknown>(`/api/v1/admin/jobs?${search}`, { signal }));
}

export async function getAdminSettings(signal?: AbortSignal) {
  return parseAdminSettings(await adminApiFetch<unknown>("/api/v1/admin/settings", { signal }));
}

export async function searchAdminResources(query: string, signal?: AbortSignal) {
  const search = new URLSearchParams({ q: query });
  return parseAdminSearch(await adminApiFetch<unknown>(`/api/v1/admin/search?${search}`, { signal }));
}
