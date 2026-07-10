import { Navigate, type RouteObject } from "react-router-dom";

import { AdminPreviewBoundary } from "@/app/AdminPreviewBoundary";
import { AdminShell } from "@/app/AdminShell";
import {
  DashboardRoute,
  ModuleRoute,
  NotFoundRoute,
} from "@/routes/lazy-pages";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AdminPreviewBoundary />,
    children: [
      {
        element: <AdminShell />,
        children: [
          { index: true, element: <Navigate replace to="/overview" /> },
          { path: "overview", element: <DashboardRoute /> },
          {
            path: "operations/runs",
            element: <ModuleRoute moduleId="runs" />,
          },
          {
            path: "operations/games",
            element: <ModuleRoute moduleId="games" />,
          },
          {
            path: "content/players",
            element: <ModuleRoute moduleId="players" />,
          },
          {
            path: "content/voice-assets",
            element: <ModuleRoute moduleId="voice" />,
          },
          {
            path: "access/users",
            element: <ModuleRoute moduleId="users" />,
          },
          {
            path: "access/roles",
            element: <ModuleRoute moduleId="roles" />,
          },
          {
            path: "system/audit-logs",
            element: <ModuleRoute moduleId="audit" />,
          },
          {
            path: "system/settings",
            element: <ModuleRoute moduleId="settings" />,
          },
          { path: "*", element: <NotFoundRoute /> },
        ],
      },
    ],
  },
];
