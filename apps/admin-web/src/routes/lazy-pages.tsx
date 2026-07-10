import { lazy, Suspense, type ReactNode } from "react";

const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const ModulePage = lazy(() => import("@/pages/ModulePage"));
const NotFoundPage = lazy(() => import("@/pages/NotFoundPage"));

type ModuleId =
  | "runs"
  | "games"
  | "players"
  | "voice"
  | "users"
  | "roles"
  | "audit"
  | "settings";

function LazyRoute({ children }: { children: ReactNode }) {
  return <Suspense fallback={<RouteLoading />}>{children}</Suspense>;
}

function RouteLoading() {
  return (
    <div aria-live="polite" className="route-loading" role="status">
      <span />
      正在加载后台模块...
    </div>
  );
}

export function DashboardRoute() {
  return (
    <LazyRoute>
      <DashboardPage />
    </LazyRoute>
  );
}

export function ModuleRoute({ moduleId }: { moduleId: ModuleId }) {
  return (
    <LazyRoute>
      <ModulePage moduleId={moduleId} />
    </LazyRoute>
  );
}

export function NotFoundRoute() {
  return (
    <LazyRoute>
      <NotFoundPage />
    </LazyRoute>
  );
}
