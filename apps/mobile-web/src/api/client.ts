export class ApiError extends Error {
  detail: string;
  status: number;

  constructor(message: string, status: number, detail: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

type ErrorBody = {
  detail?: unknown;
};

function normalizeDetail(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => normalizeDetail(item)).join("；");
  }
  if (value && typeof value === "object") {
    return JSON.stringify(value);
  }
  return "请求失败";
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, init);
  if (!response.ok) {
    let body: ErrorBody = {};
    try {
      body = (await response.json()) as ErrorBody;
    } catch {
      body = {};
    }
    const detail = normalizeDetail(body.detail);
    throw new ApiError(detail, response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
