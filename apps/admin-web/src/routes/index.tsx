import { createBrowserRouter } from "react-router-dom";

import { routes } from "@/routes/definitions";

export { routes } from "@/routes/definitions";

export function createAdminRouter() {
  return createBrowserRouter(routes);
}
