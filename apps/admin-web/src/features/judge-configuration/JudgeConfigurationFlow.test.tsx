import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { previewJudgeConfiguration } from "@/features/judge-configuration/preview";
import { routes } from "@/routes";
import { expectAdminNotification } from "@/tests/admin-notification";
import { selectAntdOption } from "@/tests/antd-select";

function renderRoute() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(routes, {
    initialEntries: ["/content/judge"],
  });
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe("admin judge configuration flow", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_ADMIN_AUTH_ENABLED", "true");
    vi.stubEnv("VITE_ADMIN_DEV_LOGIN_ENABLED", "false");
    vi.stubEnv("VITE_ADMIN_PREVIEW_MODE", "false");
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("switches from fixed voice to a per-game random pool", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/me")) {
        return jsonResponse({
          user: {
            id: "judge-admin",
            email: "judge@example.test",
            display_name: "法官管理员",
            role: "super_admin",
          },
          permissions: ["settings.read", "settings.manage"],
          csrf_token: "csrf-judge",
          session_expires_at: "2999-01-01T00:00:00Z",
        });
      }
      if (url.endsWith("/api/v1/admin/judge-configuration") && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body));
        return jsonResponse({
          ...previewJudgeConfiguration,
          ...body,
          tts_speaker:
            body.voice_mode === "random"
              ? body.random_tts_speakers[0]
              : body.tts_speaker,
          version: 2,
        });
      }
      if (url.endsWith("/api/v1/admin/judge-configuration")) {
        return jsonResponse(previewJudgeConfiguration);
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderRoute();

    expect(
      await screen.findByRole("heading", { name: "法官配置" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("combobox")).toHaveLength(2);
    expect(screen.queryByLabelText("模型")).toBeNull();
    expect(screen.queryByLabelText(/人设|策略|性格|背景故事/)).toBeNull();

    await selectAntdOption(
      user,
      screen.getByLabelText("音色模式"),
      "每局随机音色",
    );
    await selectAntdOption(
      user,
      screen.getByLabelText("随机音色池"),
      "Vivi 2.0",
    );
    await selectAntdOption(
      user,
      screen.getByLabelText("随机音色池"),
      "阳光青年 2.0",
    );
    await user.click(screen.getByRole("button", { name: "保存配置" }));

    await expectAdminNotification("法官配置已保存");
    const patch = fetchMock.mock.calls.find(
      ([input, init]) =>
        String(input).endsWith("/api/v1/admin/judge-configuration") &&
        init?.method === "PATCH",
    );
    expect(patch).toBeDefined();
    await waitFor(() =>
      expect(JSON.parse(String(patch?.[1]?.body))).toEqual({
        voice_mode: "random",
        tts_speaker: null,
        random_tts_speakers: [
          "zh_female_vv_uranus_bigtts",
          "zh_male_yangguangqingnian_uranus_bigtts",
        ],
        expected_version: 1,
      }),
    );
  });
});

function jsonResponse(value: unknown) {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}
