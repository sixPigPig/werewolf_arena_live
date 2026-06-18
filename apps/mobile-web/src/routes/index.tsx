import { createBrowserRouter } from "react-router-dom";

import { routes } from "./definitions";

export { routes } from "./definitions";

export function createMobileRouter() {
  return createBrowserRouter(routes);
}
