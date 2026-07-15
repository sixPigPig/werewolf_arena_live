import { lazy, Suspense, type ReactNode } from "react";

const ForbiddenPage = lazy(() => import("@/pages/ForbiddenPage"));
const LoginPage = lazy(() => import("@/pages/LoginPage"));
const NotFoundPage = lazy(() => import("@/pages/NotFoundPage"));
const GameRecordsPage = lazy(
  () => import("@/features/game-records/GameRecordsPage"),
);
const GameRecordDetailPage = lazy(
  () => import("@/features/game-records/GameRecordDetailPage"),
);
const LiveRunsPage = lazy(
  () => import("@/features/live-runs/LiveRunsPage"),
);
const LiveRunDetailPage = lazy(
  () => import("@/features/live-runs/LiveRunDetailPage"),
);
const JudgeVoiceAssetsPage = lazy(
  () => import("@/features/voice-assets/JudgeVoiceAssetsPage"),
);
const PlayerProfilesPage = lazy(
  () => import("@/features/player-profiles/PlayerProfilesPage"),
);
const PlayerProfileEditorPage = lazy(
  () => import("@/features/player-profiles/PlayerProfileEditorPage"),
);
const RuleSetsPage = lazy(() => import("@/features/rule-sets/RuleSetsPage"));
const ModelsPage = lazy(() => import("@/features/models/ModelsPage"));
const RuleSetNewPage = lazy(() => import("@/features/rule-sets/RuleSetsPage").then((module) => ({ default: module.RuleSetNewPage })));
const RuleSetDetailPage = lazy(() => import("@/features/rule-sets/RuleSetsPage").then((module) => ({ default: module.RuleSetDetailPage })));
const AdminUsersPage = lazy(
  () => import("@/features/admin-users/AdminUsersPage"),
);
const AuditEventsPage = lazy(
  () => import("@/features/audit-events/AuditEventsPage"),
);
const OverviewPage = lazy(() => import("@/features/dashboard/OverviewPage"));
const JobsPage = lazy(() => import("@/features/dashboard/JobsPage"));
const SettingsPage = lazy(() => import("@/features/dashboard/SettingsPage"));

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

export function GameRecordsRoute() {
  return (
    <LazyRoute>
      <GameRecordsPage />
    </LazyRoute>
  );
}

export function GameRecordDetailRoute() {
  return (
    <LazyRoute>
      <GameRecordDetailPage />
    </LazyRoute>
  );
}

export function LiveRunsRoute() {
  return (
    <LazyRoute>
      <LiveRunsPage />
    </LazyRoute>
  );
}

export function LiveRunDetailRoute() {
  return (
    <LazyRoute>
      <LiveRunDetailPage />
    </LazyRoute>
  );
}

export function JudgeVoiceAssetsRoute() {
  return (
    <LazyRoute>
      <JudgeVoiceAssetsPage />
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

export function RuleSetsRoute() { return <LazyRoute><RuleSetsPage /></LazyRoute>; }
export function ModelsRoute() { return <LazyRoute><ModelsPage /></LazyRoute>; }
export function RuleSetNewRoute() { return <LazyRoute><RuleSetNewPage /></LazyRoute>; }
export function RuleSetDetailRoute() { return <LazyRoute><RuleSetDetailPage /></LazyRoute>; }

export function AdminUsersRoute() {
  return <LazyRoute><AdminUsersPage /></LazyRoute>;
}

export function AuditEventsRoute() {
  return <LazyRoute><AuditEventsPage /></LazyRoute>;
}

export function OverviewRoute() {
  return <LazyRoute><OverviewPage /></LazyRoute>;
}

export function JobsRoute() {
  return <LazyRoute><JobsPage /></LazyRoute>;
}

export function SettingsRoute() {
  return <LazyRoute><SettingsPage /></LazyRoute>;
}

export function NotFoundRoute() {
  return (
    <LazyRoute>
      <NotFoundPage />
    </LazyRoute>
  );
}
