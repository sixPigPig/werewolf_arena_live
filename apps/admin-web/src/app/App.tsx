import { RouterProvider } from "react-router-dom";

import { createAdminRouter } from "@/routes";

export function App() {
  return <RouterProvider router={createAdminRouter()} />;
}
