import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";

import { App } from "../app/App";

describe("App", () => {
  it("renders the project shell heading", () => {
    const queryClient = new QueryClient();

    render(
      <QueryClientProvider client={queryClient}>
        <App />
      </QueryClientProvider>,
    );

    expect(
      screen.getByRole("heading", { name: /python \+ react monorepo is ready/i }),
    ).toBeInTheDocument();
  });
});
