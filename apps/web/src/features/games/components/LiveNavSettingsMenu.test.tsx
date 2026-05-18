import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import type { LiveNavStatus } from "../liveNavStatus";
import type { GameRun } from "../types";
import { LiveNavSettingsMenu } from "./LiveNavSettingsMenu";

const liveStatus: LiveNavStatus = {
  detailItems: ["1x"],
  kind: "live",
  label: "直播中",
  tone: "good",
};

const run: GameRun = {
  completed_at: null,
  created_at: "2026-04-24T12:00:00Z",
  error: null,
  event_count: 1,
  max_rounds: 8,
  rule_set: {
    id: "beginner_6",
    name: "新手 6 人快局",
    player_count: 6,
    role_summary: "1 狼人 / 1 预言家 / 1 医生 / 3 村民",
    roles: [
      { count: 1, role: "狼人" },
      { count: 1, role: "预言家" },
      { count: 1, role: "医生" },
      { count: 3, role: "村民" },
    ],
    rule_tags: ["新手"],
    version: "2026.04",
  },
  run_id: "run_1234abcd",
  seed: null,
  session_id: "game_1200abcd",
  started_at: "2026-04-24T12:00:01Z",
  status: "running",
  villager_model: "deepseek-chat",
  werewolf_model: "deepseek-chat",
  winner: null,
};

function renderMenu(
  overrides: Partial<Parameters<typeof LiveNavSettingsMenu>[0]> = {},
) {
  const props = {
    backlogCount: 3,
    canResumeRun: false,
    isPaused: false,
    isResuming: false,
    onCatchUpToLatest: vi.fn(),
    onResumeRun: vi.fn(),
    onSpeedChange: vi.fn(),
    onTogglePaused: vi.fn(),
    run,
    speed: 1 as const,
    status: liveStatus,
    ...overrides,
  };

  render(
    <MemoryRouter>
      <LiveNavSettingsMenu {...props} />
    </MemoryRouter>,
  );

  return props;
}

describe("LiveNavSettingsMenu", () => {
  it("opens a settings dialog with the live rule summary", async () => {
    const user = userEvent.setup();

    renderMenu();

    await user.click(screen.getByRole("button", { name: "实时设置" }));

    const dialog = screen.getByRole("dialog", { name: "实时设置" });
    expect(dialog).toHaveTextContent("game_1200abcd");
    expect(dialog).toHaveTextContent("直播中");
    expect(dialog).toHaveTextContent("新手 6 人快局");
    expect(dialog).toHaveTextContent("v2026.04");
    expect(dialog).toHaveTextContent("6 人");
    expect(dialog).toHaveTextContent("1 狼人 / 1 预言家 / 1 医生 / 3 村民");
  });

  it("shows playback controls and reports catch-up and speed changes", async () => {
    const user = userEvent.setup();
    const props = renderMenu();

    await user.click(screen.getByRole("button", { name: "实时设置" }));

    const dialog = screen.getByRole("dialog", { name: "实时设置" });
    expect(
      within(dialog).getByRole("button", { name: "暂停" }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "追到最新" }),
    ).toBeInTheDocument();
    expect(within(dialog).getByLabelText("播放速度")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "返回大厅" })).toHaveAttribute(
      "href",
      "/games",
    );

    await user.click(within(dialog).getByRole("button", { name: "追到最新" }));
    expect(props.onCatchUpToLatest).toHaveBeenCalledTimes(1);

    await user.selectOptions(within(dialog).getByLabelText("播放速度"), "2");
    expect(props.onSpeedChange).toHaveBeenCalledWith(2);
  });

  it("uses fallback rule data when the run has no rule set", async () => {
    const user = userEvent.setup();
    renderMenu({
      run: {
        ...run,
        player_configs: [
          { seat: 1, name: "Alice" },
          { seat: 2, name: "Bob" },
        ],
        rule_set: null,
      },
    });

    await user.click(screen.getByRole("button", { name: "实时设置" }));

    const dialog = screen.getByRole("dialog", { name: "实时设置" });
    expect(dialog).toHaveTextContent("实时对局");
    expect(within(dialog).getByText("-")).toBeInTheDocument();
    expect(within(dialog).queryByText("v-")).not.toBeInTheDocument();
    expect(dialog).toHaveTextContent("2 人");
  });

  it("shows resume instead of playback controls for resumable failed runs", async () => {
    const user = userEvent.setup();
    const props = renderMenu({
      canResumeRun: true,
      run: { ...run, error: "model timeout", status: "failed" },
      status: {
        detailItems: ["失败"],
        kind: "interrupted",
        label: "异常中断",
        tone: "danger",
      },
    });

    await user.click(screen.getByRole("button", { name: "实时设置" }));

    const dialog = screen.getByRole("dialog", { name: "实时设置" });
    expect(
      within(dialog).getByRole("button", { name: "继续对局" }),
    ).toBeInTheDocument();
    expect(
      within(dialog).queryByRole("button", { name: "暂停" }),
    ).not.toBeInTheDocument();
    expect(within(dialog).queryByLabelText("播放速度")).not.toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "继续对局" }));
    expect(props.onResumeRun).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape and returns focus to the settings button", async () => {
    const user = userEvent.setup();
    renderMenu();

    const settingsButton = screen.getByRole("button", { name: "实时设置" });
    await user.click(settingsButton);
    expect(screen.getByRole("dialog", { name: "实时设置" })).toBeInTheDocument();

    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("dialog", { name: "实时设置" })).not.toBeInTheDocument();
    expect(settingsButton).toHaveFocus();
  });

  it("closes on backdrop mouse down and returns focus to the settings button", async () => {
    const user = userEvent.setup();
    renderMenu();

    const settingsButton = screen.getByRole("button", { name: "实时设置" });
    await user.click(settingsButton);
    expect(screen.getByRole("dialog", { name: "实时设置" })).toBeInTheDocument();

    fireEvent.mouseDown(screen.getByTestId("live-settings-backdrop"));

    expect(screen.queryByRole("dialog", { name: "实时设置" })).not.toBeInTheDocument();
    expect(settingsButton).toHaveFocus();
  });

  it("loops focus through the settings dialog with Tab and Shift+Tab", async () => {
    const user = userEvent.setup();
    renderMenu();

    await user.click(screen.getByRole("button", { name: "实时设置" }));

    const dialog = screen.getByRole("dialog", { name: "实时设置" });
    const closeButton = within(dialog).getByRole("button", {
      name: "关闭实时设置",
    });
    const lobbyLink = within(dialog).getByRole("link", { name: "返回大厅" });

    lobbyLink.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(closeButton).toHaveFocus();

    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(lobbyLink).toHaveFocus();
  });
});
