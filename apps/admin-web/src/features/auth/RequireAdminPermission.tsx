import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import type { AdminPermission } from "@/app/admin-navigation";
import { hasAdminPermission } from "@/features/auth/permissions";
import { useAdminSession } from "@/features/auth/session-context";

export function RequireAdminPermission({
  children,
  permission,
}: {
  children: ReactNode;
  permission: AdminPermission;
}) {
  const location = useLocation();
  const { session } = useAdminSession();

  if (!session || !hasAdminPermission(session.permissions, permission)) {
    return <Navigate replace state={{ from: location.pathname }} to="/403" />;
  }

  return children;
}
