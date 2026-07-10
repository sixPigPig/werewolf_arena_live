import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { subscribeToAdminSessionExpired } from "@/api/client";
import { AdminApiError, isAdminApiError } from "@/api/problem-details";
import {
  createAdminDevSession,
  deleteAdminSession,
  getAdminSession,
} from "@/features/auth/auth-api";
import { isAdminDevLoginEnabled } from "@/features/auth/runtime-config";
import {
  AdminSessionContext,
  type AdminSessionContextValue,
  type AdminSessionStatus,
  type UnauthenticatedReason,
} from "@/features/auth/session-context";
import { adminSessionQueryKey } from "@/features/auth/session-query";
import type {
  AdminRuntimeMode,
  AdminSession,
} from "@/features/auth/types";

const PREVIEW_SESSION: AdminSession = {
  user: {
    id: "preview-super-admin",
    email: "preview@werewolf-arena.local",
    display_name: "超级管理员",
    role: "super_admin",
  },
  permissions: ["*"],
  csrf_token: "preview-only",
  session_expires_at: "2999-12-31T23:59:59.000Z",
};

export function AdminSessionProvider({
  children,
  runtimeMode,
}: {
  children: ReactNode;
  runtimeMode: AdminRuntimeMode;
}) {
  const queryClient = useQueryClient();
  const authenticatedOnce = useRef(false);
  const [pendingAction, setPendingAction] = useState<
    AdminSessionContextValue["pendingAction"]
  >(null);
  const [actionError, setActionError] = useState<AdminApiError | null>(null);
  const [unauthenticatedReason, setUnauthenticatedReason] =
    useState<UnauthenticatedReason>(null);

  const sessionQuery = useQuery<AdminSession | null, AdminApiError>({
    enabled: runtimeMode === "authenticated",
    queryFn: getAdminSession,
    queryKey: adminSessionQueryKey,
    retry: false,
    staleTime: 30_000,
  });

  const session =
    runtimeMode === "preview" ? PREVIEW_SESSION : (sessionQuery.data ?? null);

  const clearCachedAdminData = useCallback(
    (reason: Exclude<UnauthenticatedReason, null>) => {
      void queryClient.cancelQueries({ queryKey: ["admin"] });
      queryClient.removeQueries({
        predicate: (query) => query.queryKey[0] === "admin",
      });
      queryClient.setQueryData<AdminSession | null>(adminSessionQueryKey, null);
      authenticatedOnce.current = false;
      setUnauthenticatedReason(reason);
    },
    [queryClient],
  );

  useEffect(() => {
    if (session) {
      authenticatedOnce.current = true;
    }
  }, [session]);

  useEffect(() => {
    if (runtimeMode !== "authenticated") {
      return undefined;
    }

    return subscribeToAdminSessionExpired(() => {
      clearCachedAdminData("expired");
    });
  }, [clearCachedAdminData, runtimeMode]);

  useEffect(() => {
    if (!session || runtimeMode !== "authenticated") {
      return undefined;
    }

    const remainingMilliseconds =
      Date.parse(session.session_expires_at) - Date.now();
    const timeout = window.setTimeout(
      () => clearCachedAdminData("expired"),
      Math.max(0, Math.min(remainingMilliseconds, 2_147_483_647)),
    );
    return () => window.clearTimeout(timeout);
  }, [clearCachedAdminData, runtimeMode, session]);

  useEffect(() => {
    if (
      authenticatedOnce.current &&
      isAdminApiError(sessionQuery.error, 401)
    ) {
      clearCachedAdminData("expired");
    }
  }, [clearCachedAdminData, sessionQuery.error]);

  const loginWithDevSession = useCallback(async () => {
    setActionError(null);
    if (!isAdminDevLoginEnabled()) {
      const error = new AdminApiError({
        problem: {
          type: "about:blank",
          title: "开发登录未启用",
          status: 404,
          detail: "当前环境没有启用开发登录。",
          code: "admin_dev_login_disabled",
          request_id: null,
        },
      });
      setActionError(error);
      throw error;
    }

    setPendingAction("login");
    try {
      const nextSession = await createAdminDevSession();
      queryClient.setQueryData<AdminSession | null>(
        adminSessionQueryKey,
        nextSession,
      );
      authenticatedOnce.current = true;
      setUnauthenticatedReason(null);
      return nextSession;
    } catch (error) {
      const apiError = toAdminApiError(error);
      setActionError(apiError);
      throw apiError;
    } finally {
      setPendingAction(null);
    }
  }, [queryClient]);

  const logout = useCallback(async () => {
    if (!session || runtimeMode === "preview") {
      return;
    }

    setActionError(null);
    setPendingAction("logout");
    try {
      await deleteAdminSession(session.csrf_token);
      clearCachedAdminData("signed-out");
    } catch (error) {
      if (isAdminApiError(error, 401)) {
        clearCachedAdminData("signed-out");
        return;
      }
      const apiError = toAdminApiError(error);
      setActionError(apiError);
      throw apiError;
    } finally {
      setPendingAction(null);
    }
  }, [clearCachedAdminData, runtimeMode, session]);

  const refreshSession = useCallback(async () => {
    setActionError(null);
    setUnauthenticatedReason(null);
    await sessionQuery.refetch();
  }, [sessionQuery]);

  const status = resolveSessionStatus({
    runtimeMode,
    session,
    sessionError: sessionQuery.error,
    sessionPending: sessionQuery.isPending,
    unauthenticatedReason,
  });
  const error = actionError ?? sessionQuery.error ?? null;

  const value = useMemo<AdminSessionContextValue>(
    () => ({
      clearError: () => setActionError(null),
      error,
      loginWithDevSession,
      logout,
      pendingAction,
      refreshSession,
      runtimeMode,
      session,
      status,
      unauthenticatedReason,
    }),
    [
      error,
      loginWithDevSession,
      logout,
      pendingAction,
      refreshSession,
      runtimeMode,
      session,
      status,
      unauthenticatedReason,
    ],
  );

  return (
    <AdminSessionContext.Provider value={value}>
      {children}
    </AdminSessionContext.Provider>
  );
}

function resolveSessionStatus({
  runtimeMode,
  session,
  sessionError,
  sessionPending,
  unauthenticatedReason,
}: {
  runtimeMode: AdminRuntimeMode;
  session: AdminSession | null;
  sessionError: AdminApiError | null;
  sessionPending: boolean;
  unauthenticatedReason: UnauthenticatedReason;
}): AdminSessionStatus {
  if (runtimeMode === "preview") {
    return "authenticated";
  }
  if (unauthenticatedReason) {
    return "unauthenticated";
  }
  if (
    session &&
    Date.parse(session.session_expires_at) <= Date.now()
  ) {
    return "unauthenticated";
  }
  if (session) {
    return "authenticated";
  }
  if (sessionPending) {
    return "loading";
  }
  if (isAdminApiError(sessionError, 401)) {
    return "unauthenticated";
  }
  if (isAdminApiError(sessionError, 403)) {
    return "forbidden";
  }
  return sessionError ? "error" : "unauthenticated";
}

function toAdminApiError(error: unknown) {
  if (error instanceof AdminApiError) {
    return error;
  }
  return new AdminApiError({
    cause: error,
    problem: {
      type: "about:blank",
      title: "后台请求失败",
      status: 0,
      detail: "后台请求未能完成，请稍后重试。",
      code: "admin_request_failed",
      request_id: null,
    },
  });
}
