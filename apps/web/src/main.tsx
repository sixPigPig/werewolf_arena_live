import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import ReactDOM from "react-dom/client";

import { App } from "./app/App";
import { AppTheme } from "./app/AppTheme";
import { queryClient } from "./lib/query-client";
import "./styles/index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppTheme>
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>
    </AppTheme>
  </StrictMode>,
);
