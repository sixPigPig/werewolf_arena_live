import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import AntApp from "antd/es/app";

import { AdminSessionContext } from "@/features/auth/session-context";
import ModelsPage from "@/features/models/ModelsPage";
import { previewModelCatalog } from "@/features/models/preview";
import type { AdminModelCatalog } from "@/features/models/types";
import {
  expectAntdSelectLabel,
  selectAntdOption,
} from "@/tests/antd-select";
import { expectAdminNotification } from "@/tests/admin-notification";

let catalog: AdminModelCatalog;

function renderModelsPage() {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <AntApp notification={{ placement: "bottomRight" }}>
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
      </AntApp>
    </QueryClientProvider>,
  );
}

describe("model management flow", () => {
  beforeEach(() => {
    catalog = structuredClone(previewModelCatalog);
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input, init) => {
        const url = String(input);
        if (url.endsWith("/api/v1/admin/models") && (!init?.method || init.method === "GET")) {
          return new Response(JSON.stringify(catalog), {
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.endsWith("/api/v1/admin/models/agent-plan/sync")) {
          return new Response(JSON.stringify(catalog), {
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
    expect(screen.getAllByText("手动同步")).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "更新 Agent Plan 模型" }));
    await expectAdminNotification("Agent Plan 模型已同步");
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
    await expectAdminNotification("deepseek-v4-pro 配置已保存");

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
        parameters: {
          thinking: "enabled",
          reasoning_effort: "high",
          max_tokens: 8_192,
          max_tokens_mode: "auto",
        },
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
    const maxTokens = within(model!).getByLabelText("最大输出 tokens");
    expect(thinking).not.toBeDisabled();
    expect(reasoningEffort).not.toBeDisabled();
    expectAntdSelectLabel(reasoningEffort, "high");
    await selectAntdOption(user, reasoningEffort, "max");
    expect(maxTokens).toHaveValue("16384");
    await user.clear(maxTokens);
    await user.type(maxTokens, "1000");
    expect(maxTokens).toHaveValue("1000");
    expect(within(model!).getByText("手动设置")).toBeInTheDocument();
    await selectAntdOption(user, thinking, "关闭");

    expect(reasoningEffort).toBeDisabled();
    expect(maxTokens).toHaveValue("512");
    expect(within(model!).getByText("自动联动")).toBeInTheDocument();
    expect(within(model!).getByText(/已按推理档位更新最大输出 tokens 为 512/)).toBeInTheDocument();
    await selectAntdOption(user, thinking, "开启");
    expectAntdSelectLabel(reasoningEffort, "high");
    expect(maxTokens).toHaveValue("8192");
    await selectAntdOption(user, thinking, "关闭");
    expect(maxTokens).toHaveValue("512");
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
          max_tokens: 512,
          max_tokens_mode: "auto",
        },
      });
    });
  });

  it("uses backend policy values and locks an always-on Thinking model", async () => {
    const template = catalog.models.find((model) => model.model_id === "glm-5-2-260617");
    expect(template).toBeDefined();
    catalog.models.push({
      ...structuredClone(template!),
      model_id: "kimi-k3",
      source_model_id: "kimi-k3",
      display_name: "Kimi K3",
      is_default: false,
      parameters: {
        ...template!.parameters,
        thinking: "enabled",
        reasoning_effort: "low",
        max_tokens: 3_456,
        max_tokens_mode: "auto",
      },
      reasoning_policy: {
        thinking_options: ["enabled"],
        default_thinking: "enabled",
        thinking_locked: true,
        reasoning_effort_options: ["low", "high", "max"],
        default_reasoning_effort: "low",
        max_tokens_by_effort: { low: 3_456, high: 6_789, max: 9_999 },
        default_max_tokens: 3_456,
        disabled_max_tokens: null,
        sampling_parameters_allowed_when_thinking: true,
      },
    });
    const user = userEvent.setup();
    renderModelsPage();

    const model = (await screen.findByText("Kimi K3")).closest("details");
    expect(model).not.toBeNull();
    await user.click(within(model!).getByText("Kimi K3"));

    const thinking = within(model!).getByLabelText("Thinking");
    const effort = within(model!).getByLabelText("Reasoning effort");
    const maxTokens = within(model!).getByLabelText("最大输出 tokens");
    expect(thinking).toBeDisabled();
    expectAntdSelectLabel(thinking, "开启");
    expect(within(model!).getByText(/Thinking 模式由模型能力锁定/)).toBeInTheDocument();

    await user.clear(maxTokens);
    await user.type(maxTokens, "1111");
    expect(within(model!).getByText("手动设置")).toBeInTheDocument();
    await selectAntdOption(user, effort, "high");
    expect(maxTokens).toHaveValue("6789");
    expect(within(model!).getByText("自动联动")).toBeInTheDocument();
    expect(within(model!).getByText(/6,789（自动联动）/)).toBeInTheDocument();
  });

  it("hides unsupported effort and uses default model-level token linkage", async () => {
    const template = catalog.models.find((model) => model.model_id === "glm-5-2-260617");
    expect(template).toBeDefined();
    catalog.models.push({
      ...structuredClone(template!),
      model_id: "minimax-m3",
      source_model_id: "minimax-m3",
      display_name: "MiniMax M3",
      is_default: false,
      parameters: {
        ...template!.parameters,
        thinking: "enabled",
        reasoning_effort: null,
        max_tokens: 4_321,
        max_tokens_mode: "auto",
      },
      reasoning_policy: {
        thinking_options: ["enabled", "disabled"],
        default_thinking: "enabled",
        thinking_locked: false,
        reasoning_effort_options: [],
        default_reasoning_effort: null,
        max_tokens_by_effort: {},
        default_max_tokens: 4_321,
        disabled_max_tokens: 321,
        sampling_parameters_allowed_when_thinking: true,
      },
    });
    const user = userEvent.setup();
    renderModelsPage();

    const model = (await screen.findByText("MiniMax M3")).closest("details");
    expect(model).not.toBeNull();
    await user.click(within(model!).getByText("MiniMax M3"));

    expect(within(model!).queryByLabelText("Reasoning effort")).not.toBeInTheDocument();
    const thinking = within(model!).getByLabelText("Thinking");
    const maxTokens = within(model!).getByLabelText("最大输出 tokens");
    await selectAntdOption(user, thinking, "关闭");
    expect(maxTokens).toHaveValue("321");
    await selectAntdOption(user, thinking, "开启");
    expect(maxTokens).toHaveValue("4321");
  });

  it("uses model-level sampling capability across providers", async () => {
    const template = catalog.models.find(
      (model) => model.model_id === "glm-5-2-260617",
    );
    expect(template).toBeDefined();
    catalog.models.push({
      ...structuredClone(template!),
      model_id: "deepseek-v4-flash-260425",
      source_model_id: "deepseek-v4-flash-260425",
      display_name: "Agent Plan DeepSeek V4",
      is_default: false,
      parameters: {
        ...template!.parameters,
        temperature: 0.6,
      },
      reasoning_policy: {
        ...template!.reasoning_policy,
        sampling_parameters_allowed_when_thinking: false,
      },
    });
    const user = userEvent.setup();
    renderModelsPage();

    const model = (await screen.findByText("Agent Plan DeepSeek V4")).closest(
      "details",
    );
    expect(model).not.toBeNull();
    await user.click(within(model!).getByText("Agent Plan DeepSeek V4"));

    expect(within(model!).getByLabelText("Temperature")).toBeDisabled();
    expect(
      within(model!).getByText(/该模型在 Thinking 开启时不使用 Temperature/),
    ).toBeInTheDocument();
    await user.click(within(model!).getByRole("button", { name: "保存配置" }));

    await waitFor(() => {
      const patch = vi.mocked(fetch).mock.calls.find(([input, init]) =>
        String(input).includes(
          "/api/v1/admin/models/agent_plan/deepseek-v4-flash-260425",
        ) && init?.method === "PATCH",
      );
      expect(patch).toBeDefined();
      expect(JSON.parse(String(patch?.[1]?.body))).toMatchObject({
        parameters: {
          thinking: "enabled",
          reasoning_effort: "high",
          temperature: null,
          top_p: null,
          frequency_penalty: null,
          presence_penalty: null,
        },
      });
    });
  });

  it("can restore auto mode when Thinking and effort are locked", async () => {
    const lockedModel = catalog.models.find(
      (model) => model.model_id === "ep-example",
    );
    expect(lockedModel).toBeDefined();
    lockedModel!.parameters.max_tokens = 999;
    lockedModel!.parameters.max_tokens_mode = "manual";
    const user = userEvent.setup();
    renderModelsPage();

    const model = (await screen.findAllByText("ep-example"))[0].closest("details");
    expect(model).not.toBeNull();
    await user.click(within(model!).getAllByText("ep-example")[0]);

    const thinking = within(model!).getByLabelText("Thinking");
    const maxTokens = within(model!).getByLabelText("最大输出 tokens");
    expect(thinking).toBeDisabled();
    expect(maxTokens).toHaveValue("999");
    await user.click(
      within(model!).getByRole("button", { name: "恢复自动联动" }),
    );

    expect(maxTokens).toHaveValue("512");
    expect(within(model!).getByText("自动联动")).toBeInTheDocument();
  });

  it("prompts Volcengine login after Agent Plan sync auth failure", async () => {
    let syncedAfterLogin = false;
    vi.stubGlobal(
      "fetch",
      vi.fn<typeof fetch>(async (input, init) => {
        const url = String(input);
        if (url.endsWith("/api/v1/admin/models") && (!init?.method || init.method === "GET")) {
          return new Response(JSON.stringify(catalog), {
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.endsWith("/api/v1/admin/models/agent-plan/sync")) {
          if (!syncedAfterLogin) {
            return new Response(
              JSON.stringify({
                type: "urn:werewolf-arena:admin-problem:admin_model_catalog_sync_auth_required",
                title: "Volcengine login required",
                status: 503,
                detail: "Agent Plan sync requires an authenticated arkcli Volc SSO session.",
                code: "admin_model_catalog_sync_auth_required",
                request_id: "req-models-login",
              }),
              {
                headers: { "Content-Type": "application/problem+json" },
                status: 503,
              },
            );
          }
          return new Response(JSON.stringify(catalog), {
            headers: { "Content-Type": "application/json" },
          });
        }
        if (url.endsWith("/api/v1/admin/models/agent-plan/login")) {
          return new Response(
            JSON.stringify({
              authorize_url: "https://signin.volcengine.com/authorize/oauth/authorize?x=1",
              expires_in_sec: 600,
              already_authenticated: false,
            }),
            { headers: { "Content-Type": "application/json" } },
          );
        }
        if (url.endsWith("/api/v1/admin/models/agent-plan/login/complete")) {
          syncedAfterLogin = true;
          return new Response(JSON.stringify({ authenticated: true }), {
            headers: { "Content-Type": "application/json" },
          });
        }
        throw new Error(`Unexpected request: ${url}`);
      }),
    );
    const openSpy = vi.spyOn(window, "open").mockImplementation(() => null);
    const user = userEvent.setup();
    renderModelsPage();

    await user.click(await screen.findByRole("button", { name: "更新 Agent Plan 模型" }));
    const dialog = await screen.findByRole("dialog", { name: "是否登录火山引擎" });
    expect(dialog).toHaveTextContent("是否现在登录");
    expect(screen.queryByText("模型同步失败")).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: /取\s*消/ }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(openSpy).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "更新 Agent Plan 模型" }));
    const confirmDialog = await screen.findByRole("dialog", {
      name: "是否登录火山引擎",
    });
    await user.click(within(confirmDialog).getByRole("button", { name: "确认登录" }));
    expect(await screen.findByRole("dialog", { name: "完成火山引擎登录" })).toBeInTheDocument();
    expect(openSpy).toHaveBeenCalledWith(
      "https://signin.volcengine.com/authorize/oauth/authorize?x=1",
      "_blank",
      "noopener,noreferrer",
    );

    await user.type(screen.getByLabelText("火山引擎授权码"), "encoded-code");
    await user.click(screen.getByRole("button", { name: "完成登录" }));
    await expectAdminNotification("火山引擎已登录");
    await expectAdminNotification("Agent Plan 模型已同步");

    const fetchMock = vi.mocked(fetch);
    const complete = fetchMock.mock.calls.find(([input]) =>
      String(input).endsWith("/api/v1/admin/models/agent-plan/login/complete"),
    );
    expect(complete).toBeDefined();
    expect(JSON.parse(String(complete?.[1]?.body))).toEqual({
      authorization_code: "encoded-code",
    });
    expect(
      fetchMock.mock.calls.filter(([input]) =>
        String(input).endsWith("/api/v1/admin/models/agent-plan/sync"),
      ),
    ).toHaveLength(3);
    openSpy.mockRestore();
  });
});
