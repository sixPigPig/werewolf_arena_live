import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AdminSessionContext } from "@/features/auth/session-context";
import ModelsPage from "@/features/models/ModelsPage";
import { previewModelCatalog } from "@/features/models/preview";
import {
  expectAntdSelectLabel,
  selectAntdOption,
} from "@/tests/antd-select";

function renderModelsPage() {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <AdminSessionContext.Provider
        value={{
          clearError: vi.fn(),
          error: null,
          loginWithDevSession: vi.fn(),
          logout: vi.fn(),
          pendingAction: null,
          refreshSession: vi.fn(),
          runtimeMode: "authenticated",
          session: {
            user: {
              id: "1",
              email: "admin@example.test",
              display_name: "模型管理员",
              role: "super_admin",
            },
            permissions: ["settings.read", "settings.manage"],
            csrf_token: "csrf-models",
            session_expires_at: "2999-01-01T00:00:00Z",
          },
          status: "authenticated",
          unauthenticatedReason: null,
        }}
      >
        <ModelsPage />
      </AdminSessionContext.Provider>
    </QueryClientProvider>,
  );
}

describe("model management flow", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input, init) => {
        const url = String(input);
        if (url.endsWith("/api/v1/admin/models") && (!init?.method || init.method === "GET")) {
          return new Response(JSON.stringify(previewModelCatalog), {
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.endsWith("/api/v1/admin/models/agent-plan/sync")) {
          return new Response(JSON.stringify(previewModelCatalog), {
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.includes("/api/v1/admin/models/") && init?.method === "PATCH") {
          return new Response(null, { status: 204 });
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows source semantics, syncs Agent Plan, and saves a model configuration", async () => {
    const user = userEvent.setup();
    renderModelsPage();

    expect(await screen.findByRole("heading", { name: "模型管理" })).toBeInTheDocument();
    expect(await screen.findByText("官方实时")).toBeInTheDocument();
    expect(screen.getByText("手动同步")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "更新 Agent Plan 模型" }));
    await waitFor(() => {
      const fetchMock = vi.mocked(fetch);
      expect(
        fetchMock.mock.calls.some(([input]) =>
          String(input).endsWith("/api/v1/admin/models/agent-plan/sync"),
        ),
      ).toBe(true);
    });

    const proText = screen.getAllByText("deepseek-v4-pro")[0];
    const details = proText.closest("details");
    expect(details).not.toBeNull();
    await user.click(proText);
    await user.click(within(details!).getByLabelText("允许虚拟玩家使用"));
    await user.click(within(details!).getByRole("button", { name: "保存配置" }));

    await waitFor(() => {
      const patch = vi.mocked(fetch).mock.calls.find(([input, init]) =>
        String(input).includes("/api/v1/admin/models/deepseek/deepseek-v4-pro") &&
        init?.method === "PATCH",
      );
      expect(patch).toBeDefined();
      expect(new Headers(patch?.[1]?.headers).get("X-CSRF-Token")).toBe("csrf-models");
      expect(JSON.parse(String(patch?.[1]?.body))).toMatchObject({
        enabled: true,
        is_default: false,
        parameters: { thinking: "default" },
      });
    });
  });

  it("shows a Chinese parameter description after clicking the question mark", async () => {
    const user = userEvent.setup();
    renderModelsPage();

    await screen.findByRole("heading", { name: "模型管理" });
    const defaultModel = (await screen.findAllByText(
      "doubao-seed-2-0-lite-260215",
    ))[0].closest("details");
    expect(defaultModel).not.toBeNull();
    const helpButton = within(defaultModel!).getByRole("button", {
      name: "查看 Temperature 参数说明",
    });

    expect(helpButton).toHaveAttribute("aria-expanded", "false");
    await user.click(helpButton);

    expect(helpButton).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("tooltip")).toHaveTextContent(
      "控制输出的随机性",
    );

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(helpButton).toHaveAttribute("aria-expanded", "false");
  });

  it("clears and disables reasoning effort when Thinking is disabled", async () => {
    const user = userEvent.setup();
    renderModelsPage();

    await screen.findByRole("heading", { name: "模型管理" });
    const model = (await screen.findAllByText("glm-5-2-260617"))[0].closest(
      "details",
    );
    expect(model).not.toBeNull();
    await user.click(within(model!).getAllByText("glm-5-2-260617")[0]);

    const thinking = within(model!).getByLabelText("Thinking");
    const reasoningEffort = within(model!).getByLabelText("Reasoning effort");
    expect(thinking).not.toBeDisabled();
    expect(reasoningEffort).not.toBeDisabled();
    await selectAntdOption(user, reasoningEffort, "medium");
    await selectAntdOption(user, thinking, "关闭");

    expect(reasoningEffort).toBeDisabled();
    expectAntdSelectLabel(reasoningEffort, "跟随提供方默认");
    expect(within(model!).getByText(/关闭 Thinking 时 Reasoning effort 不可用/)).toBeInTheDocument();

    await user.click(within(model!).getByRole("button", { name: "保存配置" }));
    await waitFor(() => {
      const patch = vi.mocked(fetch).mock.calls.find(([input, init]) =>
        String(input).includes("/api/v1/admin/models/agent_plan/glm-5-2-260617") &&
        init?.method === "PATCH",
      );
      expect(patch).toBeDefined();
      expect(JSON.parse(String(patch?.[1]?.body))).toMatchObject({
        parameters: {
          thinking: "disabled",
          reasoning_effort: null,
        },
      });
    });
  });
});
