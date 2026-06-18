import { createBrowserRouter } from "react-router-dom";

import { routes } from "./definitions";

export { routes } from "./definitions";

export function createAppRouter() {
  return createBrowserRouter(routes);
}

export const router = createAppRouter();
