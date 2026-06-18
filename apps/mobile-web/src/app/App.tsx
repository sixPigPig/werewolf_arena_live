import { RouterProvider } from "react-router-dom";

import { createMobileRouter } from "../routes";

export function App() {
  return <RouterProvider router={createMobileRouter()} />;
}
