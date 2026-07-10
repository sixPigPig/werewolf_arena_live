import { apiFetch } from "./client";
import type { PublicSessionResponse } from "../types";

let cachedPublicSession: PublicSessionResponse | null = null;
let publicSessionBootstrap: Promise<PublicSessionResponse> | null = null;

export function clearPublicSessionCache(expectedSession?: PublicSessionResponse) {
  if (!expectedSession || cachedPublicSession === expectedSession) {
    cachedPublicSession = null;
  }
}

export function ensurePublicSession(): Promise<PublicSessionResponse> {
  if (isSessionUsable(cachedPublicSession)) {
    return Promise.resolve(cachedPublicSession);
  }

  if (publicSessionBootstrap) {
    return publicSessionBootstrap;
  }

  publicSessionBootstrap = apiFetch<PublicSessionResponse>(
    "/api/v1/public/session",
    {
      credentials: "include",
      method: "POST",
    },
  )
    .then((session) => {
      cachedPublicSession = session;
      return session;
    })
    .finally(() => {
      publicSessionBootstrap = null;
    });

  return publicSessionBootstrap;
}

function isSessionUsable(
  session: PublicSessionResponse | null,
): session is PublicSessionResponse {
  if (!session) {
    return false;
  }

  const expiresAt = Date.parse(session.session_expires_at);
  return Number.isFinite(expiresAt) && expiresAt - Date.now() > 30_000;
}
