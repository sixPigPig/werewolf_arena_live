import { lazy, Suspense, type ReactNode } from "react";

const ForbiddenPage = lazy(() => import("@/pages/ForbiddenPage"));
const LoginPage = lazy(() => import("@/pages/LoginPage"));
const NotFoundPage = lazy(() => import("@/pages/NotFoundPage"));
const PlayerProfilesPage = lazy(
  () => import("@/features/player-profiles/PlayerProfilesPage"),
);
const PlayerProfileEditorPage = lazy(
  () => import("@/features/player-profiles/PlayerProfileEditorPage"),
);

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

export function LoginRoute() {
  return (
    <LazyRoute>
      <LoginPage />
    </LazyRoute>
  );
}

export function ForbiddenRoute() {
  return (
    <LazyRoute>
      <ForbiddenPage />
    </LazyRoute>
  );
}

export function PlayerProfilesRoute() {
  return (
    <LazyRoute>
      <PlayerProfilesPage />
    </LazyRoute>
  );
}

export function PlayerProfileEditorRoute() {
  return (
    <LazyRoute>
      <PlayerProfileEditorPage />
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
