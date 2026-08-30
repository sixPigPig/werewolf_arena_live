const TOKEN_PREFIX = "live-v2:god-view:";

export function saveGodViewAccessToken(gameId: string, token: string): void {
  if (!validGodViewAccessToken(token)) return;
  window.sessionStorage.setItem(`${TOKEN_PREFIX}${gameId}`, token);
}

export function readGodViewAccessToken(gameId: string): string | null {
  const token = window.sessionStorage.getItem(`${TOKEN_PREFIX}${gameId}`);
  return token && validGodViewAccessToken(token) ? token : null;
}

export function godViewAccessTokenFromHash(hash: string): string | null {
  const value = new URLSearchParams(hash.replace(/^#/, "")).get("access_token");
  return value && validGodViewAccessToken(value) ? value : null;
}

export function godViewPageUrl(gameId: string, token: string): string {
  return `/v2/games/${encodeURIComponent(gameId)}/live/god#access_token=${encodeURIComponent(token)}`;
}

function validGodViewAccessToken(value: string): boolean {
  return /^[A-Za-z0-9_-]{32,128}$/.test(value);
}
