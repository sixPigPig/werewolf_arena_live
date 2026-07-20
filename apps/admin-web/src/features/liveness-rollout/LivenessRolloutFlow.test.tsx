import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { routes } from "@/routes";

const session = {
  user: {
    id: "42",
    email: "admin@example.test",
    display_name: "Arena Admin",
    role: "super_admin",
  },
  permissions: ["settings.read", "settings.manage"],
  csrf_token: "csrf-rollout",
  session_expires_at: "2999-01-01T00:00:00Z",
};

const experience = {
  revision: "liveness-v1",
  label: "活人感体验 V1",
  description: "角色心智、分句流式语音、情绪表达和可打断播报的第一版组合。",
  control_summary: "保留异步质量观察与影子心智，不启用分句语音、情绪投递和打断。",
  treatment_summary: "启用角色心智读取、分句语音、情绪投递、预取和确定性打断。",
};

function config(revision: number, treatmentPercent: number) {
  return {
    revision,
    experience_revision: "liveness-v1",
    experiment_id: "lifelike-canary-v1",
    treatment_percent: treatmentPercent,
    control_percent: 100 - treatmentPercent,
    source: "database",
    effective_scope: "new_sessions_only",
    updated_at: "2026-07-20T08:00:00Z",
    available_experiences: [experience],
  };
}

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status: 200,
  });
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(routes, {
    initialEntries: ["/system/liveness-rollout"],
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("liveness rollout control", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_ADMIN_AUTH_ENABLED", "true");
    vi.stubEnv("VITE_ADMIN_DEV_LOGIN_ENABLED", "false");
    vi.stubEnv("VITE_ADMIN_PREVIEW_MODE", "false");
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("saves a new revision with an audited reason and CSRF token", async () => {
    let savedRequest: RequestInit | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input, init) => {
        const url = String(input);
        if (url.endsWith("/api/v1/admin/me")) return jsonResponse(session);
        if (url.endsWith("/api/v1/admin/liveness-rollout") && init?.method === "PUT") {
          savedRequest = init;
          return jsonResponse(config(2, 25));
        }
        if (url.endsWith("/api/v1/admin/liveness-rollout")) {
          return jsonResponse(config(1, 10));
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByRole("heading", { name: "灰度控制" })).toBeInTheDocument();
    expect(screen.getByText("只影响保存后创建的新对局")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "25%" }));
    await user.type(
      screen.getByPlaceholderText(/评审达标/),
      "评审达标，扩大样本观察线上指标",
    );
    await user.click(screen.getByRole("button", { name: "保存灰度配置" }));

    expect(await screen.findByText(/已保存为修订 2/)).toBeInTheDocument();
    expect(new Headers(savedRequest?.headers).get("X-CSRF-Token")).toBe("csrf-rollout");
    expect(JSON.parse(String(savedRequest?.body))).toEqual({
      expected_revision: 1,
      experience_revision: "liveness-v1",
      experiment_id: "lifelike-canary-v1",
      treatment_percent: 25,
      change_reason: "评审达标，扩大样本观察线上指标",
    });
    await waitFor(() => expect(screen.getByText("配置修订 2")).toBeInTheDocument());
  });
});
