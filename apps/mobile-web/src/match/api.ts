import {
  parseGameCreateResponse,
  parseDirectorLiveSnapshotResponse,
  parseGodViewIdentitySnapshotResponse,
  parseLiveSnapshotResponse,
  type GameCreateRequest,
  type GameCreateResponse,
  type DirectorLiveSnapshot,
  type GodViewIdentitySnapshot,
  type LiveSnapshot,
} from "./contracts";

export class GameCreateError extends Error {
  public readonly status: number;
  public readonly code: string | null;

  constructor(
    status: number,
    code: string | null,
  ) {
    super(`对局创建失败 (${status})`);
    this.name = "GameCreateError";
    this.status = status;
    this.code = code;
  }
}

export async function createGame(
  request: GameCreateRequest,
): Promise<GameCreateResponse> {
  const response = await fetch(resolveHttpUrl("/api/v2/games"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new GameCreateError(response.status, await responseErrorCode(response));
  }
  return parseGameCreateResponse(await response.json());
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

export async function fetchLiveSnapshot(gameId: string): Promise<LiveSnapshot> {
  const path = `/api/v2/live/games/${encodeURIComponent(gameId)}/snapshot`;
  const response = await fetch(resolveHttpUrl(path), {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`V2 座位快照读取失败 (${response.status})`);
  }
  return parseLiveSnapshotResponse(await response.json());
}

export async function fetchDirectorLiveSnapshot(
  gameId: string,
): Promise<DirectorLiveSnapshot> {
  const path = `/api/v2/director/games/${encodeURIComponent(gameId)}/snapshot`;
  const response = await fetch(resolveHttpUrl(path), {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`V2 导演直播快照读取失败 (${response.status})`);
  }
  return parseDirectorLiveSnapshotResponse(await response.json());
}

export async function fetchGodViewIdentitySnapshot(
  gameId: string,
  accessToken: string,
): Promise<GodViewIdentitySnapshot> {
  const path = `/api/v2/god-view/games/${encodeURIComponent(gameId)}/identity-snapshot`;
  const response = await fetch(resolveHttpUrl(path), {
    headers: {
      Accept: "application/json",
      Authorization: `Bearer ${accessToken}`,
    },
  });
  if (!response.ok) {
    throw new Error(`V2 上帝视角身份快照读取失败 (${response.status})`);
  }
  return parseGodViewIdentitySnapshotResponse(await response.json());
}

export function resolveWebSocketUrl(gameId: string): string {
  const configured = import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/, "");
  const base = configured || window.location.origin;
  const url = new URL(
    `/api/v2/live/games/${encodeURIComponent(gameId)}/ws`,
    base,
  );
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export function resolveDirectorWebSocketUrl(gameId: string): string {
  const configured = import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/, "");
  const base = configured || window.location.origin;
  const url = new URL(
    `/api/v2/director/games/${encodeURIComponent(gameId)}/ws`,
    base,
  );
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export function resolveGodViewWebSocketUrl(gameId: string): string {
  const configured = import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/, "");
  const base = configured || window.location.origin;
  const url = new URL(
    `/api/v2/god-view/games/${encodeURIComponent(gameId)}/ws`,
    base,
  );
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

function resolveHttpUrl(path: string): string {
  const configured = import.meta.env.VITE_API_BASE_URL?.replace(/\/+$/, "");
  return new URL(path, configured || window.location.origin).toString();
}
