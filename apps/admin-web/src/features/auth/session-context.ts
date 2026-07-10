import { createContext, useContext } from "react";

import { AdminApiError } from "@/api/problem-details";
import type {
  AdminRuntimeMode,
  AdminSession,
} from "@/features/auth/types";

export type AdminSessionStatus =
  | "authenticated"
  | "error"
  | "forbidden"
  | "loading"
  | "unauthenticated";

export type UnauthenticatedReason =
  | "expired"
  | "required"
  | "signed-out"
  | null;

export type AdminSessionContextValue = {
  clearError: () => void;
  error: AdminApiError | null;
  loginWithDevSession: () => Promise<AdminSession>;
  logout: () => Promise<void>;
  pendingAction: "login" | "logout" | null;
  refreshSession: () => Promise<void>;
  runtimeMode: AdminRuntimeMode;
  session: AdminSession | null;
  status: AdminSessionStatus;
  unauthenticatedReason: UnauthenticatedReason;
};

export const AdminSessionContext =
  createContext<AdminSessionContextValue | null>(null);

export function useAdminSession() {
  const context = useContext(AdminSessionContext);
  if (!context) {
    throw new Error("useAdminSession must be used inside AdminSessionProvider");
  }
  return context;
}
