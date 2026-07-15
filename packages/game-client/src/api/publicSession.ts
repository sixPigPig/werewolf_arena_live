import { ApiError, apiFetch } from "./client";
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

export async function withFreshPublicSession<T>(
  request: (session: PublicSessionResponse) => Promise<T>,
): Promise<T> {
  const session = await ensurePublicSession();
  try {
    return await request(session);
  } catch (error) {
    if (
      !(error instanceof ApiError) ||
      (error.status !== 401 && error.status !== 403)
    ) {
      throw error;
    }

    clearPublicSessionCache(session);
    return request(await ensurePublicSession());
  }
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
