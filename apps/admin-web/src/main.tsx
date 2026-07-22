import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import ReactDOM from "react-dom/client";

import { App } from "@/app/App";
import { queryClient } from "@/lib/query-client";
import "antd/dist/reset.css";
import "@/styles/index.css";
import "@/styles/antd-overrides.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
