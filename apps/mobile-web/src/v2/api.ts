import {
  parseV2GameCreateResponse,
  parseV2DirectorLiveSnapshotResponse,
  parseV2GodViewIdentitySnapshotResponse,
  parseV2LiveSnapshotResponse,
  type V2GameCreateRequest,
  type V2GameCreateResponse,
  type V2DirectorLiveSnapshot,
  type V2GodViewIdentitySnapshot,
  type V2LiveSnapshot,
} from "./contracts";

export class V2GameCreateError extends Error {
  public readonly status: number;
  public readonly code: string | null;

  constructor(
    status: number,
    code: string | null,
  ) {
    super(`V2 对局创建失败 (${status})`);
    this.name = "V2GameCreateError";
    this.status = status;
    this.code = code;
  }
}

export async function createV2Game(
  request: V2GameCreateRequest,
): Promise<V2GameCreateResponse> {
  const response = await fetch(resolveV2HttpUrl("/api/v2/games"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new V2GameCreateError(response.status, await responseErrorCode(response));
  }
  return parseV2GameCreateResponse(await response.json());
}

async function responseErrorCode(response: Response): Promise<string | null> {
  try {
    const payload: unknown = await response.json();
    if (!payload || typeof payload !== "object") {
      return null;
    }
    const detail = "detail" in payload ? payload.detail : payload;
    if (!detail || typeof detail !== "object" || !("code" in detail)) {
      return null;
    }
    return typeof detail.code === "string" ? detail.code : null;
  } catch {
    return null;
  }
}

export async function fetchV2LiveSnapshot(gameId: string): Promise<V2LiveSnapshot> {
  const path = `/api/v2/live/games/${encodeURIComponent(gameId)}/snapshot`;
  const response = await fetch(resolveV2HttpUrl(path), {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`V2 座位快照读取失败 (${response.status})`);
  }
  return parseV2LiveSnapshotResponse(await response.json());
}

export async function fetchV2DirectorLiveSnapshot(
  gameId: string,
): Promise<V2DirectorLiveSnapshot> {
  const path = `/api/v2/director/games/${encodeURIComponent(gameId)}/snapshot`;
  const response = await fetch(resolveV2HttpUrl(path), {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`V2 导演直播快照读取失败 (${response.status})`);
  }
  return parseV2DirectorLiveSnapshotResponse(await response.json());
}

export async function fetchV2GodViewIdentitySnapshot(
  gameId: string,
  accessToken: string,
): Promise<V2GodViewIdentitySnapshot> {
  const path = `/api/v2/god-view/games/${encodeURIComponent(gameId)}/identity-snapshot`;
  const response = await fetch(resolveV2HttpUrl(path), {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
  });
  if (!response.ok) {
    throw new Error(`V2 上帝视角身份快照读取失败 (${response.status})`);
  }
  return parseV2GodViewIdentitySnapshotResponse(await response.json());
}

export function resolveV2WebSocketUrl(gameId: string): string {
  const configured = import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/, "");
  const base = configured || window.location.origin;
  const url = new URL(
    `/api/v2/live/games/${encodeURIComponent(gameId)}/ws`,
    base,
  );
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export function resolveV2DirectorWebSocketUrl(gameId: string): string {
  const configured = import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/, "");
  const base = configured || window.location.origin;
  const url = new URL(
    `/api/v2/director/games/${encodeURIComponent(gameId)}/ws`,
    base,
  );
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export function resolveV2GodViewWebSocketUrl(gameId: string): string {
  const configured = import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/, "");
  const base = configured || window.location.origin;
  const url = new URL(
    `/api/v2/god-view/games/${encodeURIComponent(gameId)}/ws`,
    base,
  );
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

function resolveV2HttpUrl(path: string): string {
  const configured = import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/, "");
  return new URL(path, configured || window.location.origin).toString();
}
