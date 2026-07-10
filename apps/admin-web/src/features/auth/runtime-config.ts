import type { AdminRuntimeMode } from "@/features/auth/types";

type AdminRuntimeEnvironment = {
  DEV: boolean;
  MODE: string;
  VITE_ADMIN_AUTH_ENABLED?: string;
  VITE_ADMIN_DEV_LOGIN_ENABLED?: string;
  VITE_ADMIN_PREVIEW_MODE?: string;
};

export function getAdminRuntimeMode(): AdminRuntimeMode {
  return resolveAdminRuntimeMode(import.meta.env);
}

export function isAdminDevLoginEnabled() {
  return resolveAdminDevLoginEnabled(import.meta.env);
}

export function resolveAdminRuntimeMode(
  environment: AdminRuntimeEnvironment,
): AdminRuntimeMode {
  if (
    environment.VITE_ADMIN_AUTH_ENABLED === "true" ||
    (environment.DEV &&
      environment.VITE_ADMIN_DEV_LOGIN_ENABLED === "true") ||
    (environment.DEV &&
      environment.MODE !== "test" &&
      environment.VITE_ADMIN_PREVIEW_MODE !== "true")
  ) {
    return "authenticated";
  }

  if (
    environment.MODE === "test" ||
    (environment.DEV && environment.VITE_ADMIN_PREVIEW_MODE === "true")
  ) {
    return "preview";
  }

  return "closed";
}

export function resolveAdminDevLoginEnabled(
  environment: Pick<
    AdminRuntimeEnvironment,
    "DEV" | "VITE_ADMIN_DEV_LOGIN_ENABLED"
  >,
) {
  return (
    environment.DEV && environment.VITE_ADMIN_DEV_LOGIN_ENABLED !== "false"
  );
}
