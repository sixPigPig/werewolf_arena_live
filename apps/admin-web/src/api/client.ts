import {
  AdminApiError,
  normalizeProblemDetails,
} from "@/api/problem-details";

const SESSION_EXPIRED_EVENT = "werewolf-admin:session-expired";

export type AdminRequestOptions = RequestInit & {
  notifyOnUnauthorized?: boolean;
};

type SessionExpiredListener = () => void;

export async function adminApiFetch<T>(
  path: string,
  options: AdminRequestOptions = {},
): Promise<T> {
  const { notifyOnUnauthorized = true, ...requestOptions } = options;
  const headers = new Headers(requestOptions.headers);
  headers.set("Accept", "application/json");

  let response: Response;
  try {
    response = await fetch(resolveApiUrl(path), {
      ...requestOptions,
      credentials: "include",
      headers,
    });
  } catch (cause) {
    throw new AdminApiError({
      cause,
      problem: normalizeProblemDetails(undefined, { status: 0 }),
    });
  }

  if (!response.ok) {
    const problem = normalizeProblemDetails(await readJson(response), {
      status: response.status,
      statusText: response.statusText,
      requestId: response.headers.get("X-Request-Id"),
    });

    if (response.status === 401 && notifyOnUnauthorized) {
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
    }

    throw new AdminApiError({ problem });
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const payload = await readJson(response);
  if (payload === undefined) {
    throw new AdminApiError({
      problem: {
        type: "about:blank",
        title: "后台响应无效",
        status: response.status,
        detail: "后台服务返回了无法解析的响应。",
        code: "admin_invalid_response",
        request_id: response.headers.get("X-Request-Id"),
      },
    });
  }

  return payload as T;
}

export function subscribeToAdminSessionExpired(
  listener: SessionExpiredListener,
) {
  window.addEventListener(SESSION_EXPIRED_EVENT, listener);
  return () => window.removeEventListener(SESSION_EXPIRED_EVENT, listener);
}

export function dispatchAdminSessionExpired() {
  window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
}

function resolveApiUrl(path: string) {
  const baseUrl = import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/, "") ?? "";
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${baseUrl}${normalizedPath}`;
}

async function readJson(response: Response): Promise<unknown | undefined> {
  const text = await response.text();
  if (!text) {
    return undefined;
  }

  try {
    return JSON.parse(text) as unknown;
  } catch {
    return undefined;
  }
}
