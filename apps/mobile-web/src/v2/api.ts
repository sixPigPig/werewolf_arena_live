import {
  parseV2GameCreateResponse,
  parseV2GodViewIdentitySnapshotResponse,
  parseV2LiveSnapshotResponse,
  type V2GameCreateRequest,
  type V2GameCreateResponse,
  type V2GodViewIdentitySnapshot,
  type V2LiveSnapshot,
} from "./contracts";

export async function createV2Game(
  request: V2GameCreateRequest,
): Promise<V2GameCreateResponse> {
  const response = await fetch(resolveV2HttpUrl("/api/v2/games"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new Error(`V2 对局创建失败 (${response.status})`);
  }
  return parseV2GameCreateResponse(await response.json());
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
