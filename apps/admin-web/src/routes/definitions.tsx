import { Navigate, type RouteObject } from "react-router-dom";

import { AdminPreviewBoundary } from "@/app/AdminPreviewBoundary";
import { AdminShell } from "@/app/AdminShell";
import { AdminSessionBoundary } from "@/features/auth/AdminSessionBoundary";
import { RequireAdminPermission } from "@/features/auth/RequireAdminPermission";
import {
  ForbiddenRoute,
  GameRecordDetailRoute,
  GameRecordsRoute,
  LoginRoute,
  LiveRunDetailRoute,
  LiveRunsRoute,
  NotFoundRoute,
  PlayerProfileEditorRoute,
  PlayerProfilesRoute,
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
              { index: true, element: <Navigate replace to="/content/players" /> },
              { path: "overview", element: <Navigate replace to="/content/players" /> },
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
              { path: "*", element: <NotFoundRoute /> },
            ],
          },
        ],
      },
    ],
  },
];
