import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import ReactDOM from "react-dom/client";

import { App } from "./app/App";
import { queryClient } from "./lib/query-client";
import { installRootFontSize } from "./styles/rem";
import "./styles/index.css";

installRootFontSize();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
