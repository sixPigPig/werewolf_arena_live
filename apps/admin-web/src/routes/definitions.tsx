import { Navigate, type RouteObject } from "react-router-dom";

import { AdminPreviewBoundary } from "@/app/AdminPreviewBoundary";
import { AdminShell } from "@/app/AdminShell";
import { AdminSessionBoundary } from "@/features/auth/AdminSessionBoundary";
import { RequireAdminPermission } from "@/features/auth/RequireAdminPermission";
import {
  ForbiddenRoute,
  GameRecordDetailRoute,
  GameRecordsRoute,
  JudgeVoiceAssetsRoute,
  JudgeConfigurationRoute,
  LoginRoute,
  LiveRunDetailRoute,
  LiveRunsRoute,
  NotFoundRoute,
  PlayerProfileEditorRoute,
  PlayerProfilesRoute,
  AdminUsersRoute,
  AuditEventsRoute,
  JobsRoute,
  OverviewRoute,
  SettingsRoute,
  RuleSetsRoute,
  RuleSetNewRoute,
  RuleSetDetailRoute,
  ModelsRoute,
  V2GameRecordDetailRoute,
  V2GameRecordsRoute,
} from "@/routes/lazy-pages";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AdminPreviewBoundary />,
    children: [
      { path: "login", element: <LoginRoute /> },
      { path: "403", element: <ForbiddenRoute /> },
      {
        element: <AdminSessionBoundary />,
        children: [
          {
            element: <AdminShell />,
            children: [
              { index: true, element: <Navigate replace to="/overview" /> },
              {
                path: "overview",
                element: (
                  <RequireAdminPermission permission="overview.read">
                    <OverviewRoute />
                  </RequireAdminPermission>
                ),
              },
              {
                path: "v2/operations/games",
                element: (
                  <RequireAdminPermission permission="v2_games.read">
                    <V2GameRecordsRoute />
                  </RequireAdminPermission>
                ),
              },
              {
                path: "v2/operations/games/:gameId",
                element: (
                  <RequireAdminPermission permission="v2_games.read">
                    <V2GameRecordDetailRoute />
                  </RequireAdminPermission>
                ),
              },
              {
                path: "operations/runs",
                element: (
                  <RequireAdminPermission permission="runs.read">
                    <LiveRunsRoute />
                  </RequireAdminPermission>
                ),
              },
              {
                path: "operations/runs/:runId",
                element: (
                  <RequireAdminPermission permission="runs.read">
                    <LiveRunDetailRoute />
                  </RequireAdminPermission>
                ),
              },
              {
                path: "operations/games",
                element: (
                  <RequireAdminPermission permission="games.read">
                    <GameRecordsRoute />
                  </RequireAdminPermission>
                ),
              },
              {
                path: "operations/games/:sessionId",
                element: (
                  <RequireAdminPermission permission="games.read">
                    <GameRecordDetailRoute />
                  </RequireAdminPermission>
                ),
              },
              {
                path: "content/judge",
                element: (
                  <RequireAdminPermission permission="settings.read">
                    <JudgeConfigurationRoute />
                  </RequireAdminPermission>
                ),
              },
              {
                path: "content/voice-assets",
                element: (
                  <RequireAdminPermission permission="voice.read">
                    <JudgeVoiceAssetsRoute />
                  </RequireAdminPermission>
                ),
              },
              {
                path: "content/players",
                element: (
                  <RequireAdminPermission permission="players.read">
                    <PlayerProfilesRoute />
                  </RequireAdminPermission>
                ),
              },
              {
                path: "content/players/new",
                element: (
                  <RequireAdminPermission permission="players.write">
                    <PlayerProfileEditorRoute />
                  </RequireAdminPermission>
                ),
              },
              {
                path: "content/players/:profileId",
                element: (
                  <RequireAdminPermission permission="players.read">
                    <PlayerProfileEditorRoute />
                  </RequireAdminPermission>
                ),
              },
              {
                path: "content/rules",
                element: <RequireAdminPermission permission="rules.read"><RuleSetsRoute /></RequireAdminPermission>,
              },
              {
                path: "content/rules/new",
                element: <RequireAdminPermission permission="rules.read"><RuleSetNewRoute /></RequireAdminPermission>,
              },
              {
                path: "content/rules/:ruleSetId",
                element: <RequireAdminPermission permission="rules.read"><RuleSetDetailRoute /></RequireAdminPermission>,
              },
              {
                path: "content/models",
                element: <RequireAdminPermission permission="settings.read"><ModelsRoute /></RequireAdminPermission>,
              },
              {
                path: "system/jobs",
                element: (
                  <RequireAdminPermission permission="voice.read">
                    <JobsRoute />
                  </RequireAdminPermission>
                ),
              },
              {
                path: "system/users",
                element: (
                  <RequireAdminPermission permission="users.manage">
                    <AdminUsersRoute />
                  </RequireAdminPermission>
                ),
              },
              {
                path: "system/audit",
                element: (
                  <RequireAdminPermission permission="audit.read">
                    <AuditEventsRoute />
                  </RequireAdminPermission>
                ),
              },
              {
                path: "system/settings",
                element: (
                  <RequireAdminPermission permission="settings.read">
                    <SettingsRoute />
                  </RequireAdminPermission>
                ),
              },
              { path: "*", element: <NotFoundRoute /> },
            ],
          },
        ],
      },
    ],
  },
];
