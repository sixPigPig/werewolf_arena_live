export type ApiFetchOptions = {
  baseUrl?: string;
};

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
  }
}

function defaultApiBaseUrl() {
  const meta = import.meta as ImportMeta & {
    env?: { VITE_API_BASE_URL?: string };
  };

  return meta.env?.VITE_API_BASE_URL ?? "";
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
  options: ApiFetchOptions = {},
): Promise<T> {
  const baseUrl = options.baseUrl ?? defaultApiBaseUrl();
  const response = await fetch(`${baseUrl}${path}`, init);

  if (!response.ok) {
    throw new ApiError(response.status);
  }

  if (response.status === 204 || response.status === 205) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
  const body = await response.text();

  if (!body) {
    return undefined as T;
  }

  if (contentType.includes("application/json")) {
    return JSON.parse(body) as T;
  }

  return body as T;
}
