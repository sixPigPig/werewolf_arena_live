import { useRef, useState } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { GodViewEventLine, GodViewState } from "@werewolf-arena/game-client";

import { MobileLiveEventRail } from "./MobileLiveEventRail";

function line(overrides: Partial<GodViewEventLine>): GodViewEventLine {
  return {
    id: overrides.id ?? 1,
    time: overrides.time ?? ":00",
    text: overrides.text ?? "事件",
    tone: overrides.tone ?? "default",
    round: overrides.round ?? 1,
    phase: overrides.phase ?? "night",
    detail: overrides.detail ?? "",
  };
}

function stateWith(lines: GodViewEventLine[]): GodViewState {
  return {
    boardName: "测试",
    dayNightLabel: "第 1 夜",
    phaseLabel: "夜晚",
    currentSeatLabel: "行动席：1 号",
    countdownLabel: "行动中",
    aliveLabel: "存活 8/8",
    winMode: "屠边",
    winnerLabel: "未结算",
    players: [],
    progress: {
      wolvesAlive: 0,
      godsAlive: 0,
      villagersAlive: 0,
      totalAlive: 0,
      totalPlayers: 0,
    },
    nightActions: [],
    nightResolution: { label: "等待夜间结算", detail: "", tone: "neutral" },
    nightActionOrder: [],
    deaths: [],
    isPeacefulNight: false,
    vote: { stageLabel: "最近票型", tallies: [], totalVotes: 0, topTarget: null },
    sheriff: {
      current: null,
      badgeFlow: "未移交",
      callTarget: null,
      candidates: [],
      voters: [],
    },
    sheriffRuleState: { enabled: true, label: "警长规则开启" },
    speechOrder: [],
    speakerFlow: { previous: null, current: null, next: null, modeLabel: "等待发言" },
    eventLines: lines,
    publicFacts: [],
    replayMarks: [],
    skillTriggers: [],
    winPressure: { label: "局势未到临界", detail: "", tone: "neutral" },
  };
}

function RailHarness({
  lines,
  onSelectEvent,
}: {
  lines: GodViewEventLine[];
  onSelectEvent?: (eventId: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const backgroundRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const handleSelect = (eventId: number) => {
    onSelectEvent?.(eventId);
    setOpen(false);
  };
  return (
    <main ref={backgroundRef}>
      <MobileLiveEventRail
        backgroundRef={backgroundRef}
        eventLines={lines}
        godViewState={stateWith(lines)}
        onCloseSheet={() => setOpen(false)}
        onSelectEvent={handleSelect}
        onToggleSheet={() => setOpen((value) => !value)}
        sheetOpen={open}
        triggerRef={triggerRef}
      />
    </main>
  );
}

describe("MobileLiveEventRail", () => {
  it("renders an empty state and disables 全部 when there are no moments", () => {
    render(<RailHarness lines={[]} />);

    expect(screen.getByText("等待首个关键事件")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "查看全部战报，共 0 条" }),
    ).toBeDisabled();
  });

  it("renders the latest meaningful moments in order", () => {
    const lines = [
      line({ id: 1, text: "夜幕降临" }),
      line({ id: 2, text: "狼人 -> 7号" }),
      line({ id: 3, text: "守卫守护 7号" }),
    ];
    render(<RailHarness lines={lines} />);

    const rail = screen.getByRole("log");
    const chips = within(rail).getAllByRole("listitem");
    expect(chips.map((chip) => chip.textContent)).toEqual([
      "夜幕降临",
      "狼人 -> 7号",
      "守卫守护 7号",
    ]);
  });

  it("normalizes newest-first event data into chronological display order", () => {
    const lines = [
      line({ id: 3, text: "守卫守护 7号" }),
      line({ id: 2, text: "狼人 -> 7号" }),
      line({ id: 1, text: "夜幕降临" }),
    ];
    render(<RailHarness lines={lines} />);

    const rail = screen.getByRole("log");
    const chips = within(rail).getAllByRole("listitem");
    expect(chips.map((chip) => chip.textContent)).toEqual([
      "夜幕降临",
      "狼人 -> 7号",
      "守卫守护 7号",
    ]);
    expect(chips.at(-1)).toHaveAttribute("aria-current", "true");
  });

  it("marks the latest moment as current", () => {
    const lines = [
      line({ id: 1, text: "夜幕降临" }),
      line({ id: 2, text: "狼人 -> 7号" }),
    ];
    render(<RailHarness lines={lines} />);

    const chips = screen.getAllByRole("listitem");
    expect(chips.at(-1)).toHaveAttribute("aria-current", "true");
  });

  it("uses a polite log region and excludes events outside its props", () => {
    const lines = [line({ id: 1, text: "夜幕降临" })];
    render(<RailHarness lines={lines} />);

    const rail = screen.getByRole("log");
    expect(rail).toHaveAttribute("aria-live", "polite");
    expect(rail).toHaveAttribute("aria-relevant", "additions");
    expect(rail).not.toHaveTextContent("model_thinking_tick");
    expect(rail).not.toHaveTextContent("投票结果更新");
  });

  it("keeps duplicate text with different event IDs distinct", () => {
    const lines = [
      line({ id: 1, text: "8号 -> 1号" }),
      line({ id: 2, text: "8号 -> 1号" }),
    ];
    render(<RailHarness lines={lines} />);

    const chips = screen.getAllByRole("listitem");
    expect(chips).toHaveLength(2);
    expect(chips[0]).toHaveAttribute("data-event-id", "1");
    expect(chips[1]).toHaveAttribute("data-event-id", "2");
  });

  it("includes the moment count in the 全部 accessible name", () => {
    const lines = [
      line({ id: 1, text: "夜幕降临" }),
      line({ id: 2, text: "狼人 -> 7号" }),
      line({ id: 3, text: "守卫守护 7号" }),
    ];
    render(<RailHarness lines={lines} />);

    expect(
      screen.getByRole("button", { name: "查看全部战报，共 3 条" }),
    ).toBeVisible();
  });

  it("opens the sheet, moves focus inside, and groups moments", async () => {
    const user = userEvent.setup();
    const lines = [
      line({ id: 1, text: "夜幕降临", phase: "night", round: 1 }),
      line({ id: 2, text: "狼人 -> 7号", phase: "night", round: 1 }),
      line({ id: 3, text: "8号 -> 1号", phase: "vote", round: 1 }),
    ];
    render(<RailHarness lines={lines} />);

    await user.click(
      screen.getByRole("button", { name: "查看全部战报，共 3 条" }),
    );

    const dialog = await screen.findByRole("dialog", { name: "本轮战报" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    await waitFor(() => {
      const active = document.activeElement;
      expect(active).not.toBeNull();
      expect(dialog.contains(active)).toBe(true);
    });
    expect(within(dialog).getByText("夜幕降临")).toBeVisible();
    expect(within(dialog).getByText("狼人 -> 7号")).toBeVisible();
  });

  it("restores focus to 全部 on Escape and close", async () => {
    const user = userEvent.setup();
    const lines = [line({ id: 1, text: "夜幕降临" })];
    render(<RailHarness lines={lines} />);

    const trigger = screen.getByRole("button", { name: "查看全部战报，共 1 条" });
    await user.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "本轮战报" });
    expect(dialog).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("keeps Tab focus inside the sheet while open", async () => {
    const user = userEvent.setup();
    const lines = [line({ id: 1, text: "夜幕降临" })];
    render(<RailHarness lines={lines} />);

    await user.click(
      screen.getByRole("button", { name: "查看全部战报，共 1 条" }),
    );
    const dialog = await screen.findByRole("dialog", { name: "本轮战报" });

    // Focus starts inside the dialog; repeated Tabs must not leave it.
    await user.tab();
    await user.tab();
    const active = document.activeElement;
    expect(active).not.toBeNull();
    expect(dialog.contains(active)).toBe(true);
  });

  it("makes the background inert while open and restores it on close", async () => {
    const user = userEvent.setup();
    const lines = [line({ id: 1, text: "夜幕降临" })];
    const { container } = render(<RailHarness lines={lines} />);
    const main = container.querySelector("main") as HTMLElement;

    expect(main).not.toHaveAttribute("inert");

    await user.click(
      screen.getByRole("button", { name: "查看全部战报，共 1 条" }),
    );
    await screen.findByRole("dialog", { name: "本轮战报" });
    expect(main).toHaveAttribute("inert");
    expect(main.querySelector('[role="dialog"]')).toBeNull();

    await user.click(screen.getByRole("button", { name: "关闭" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await waitFor(() =>
      expect(main).not.toHaveAttribute("inert"),
    );
  });

  it("selects an event by id and closes the sheet", async () => {
    const user = userEvent.setup();
    const onSelectEvent = vi.fn();
    const lines = [
      line({ id: 1, text: "夜幕降临", phase: "night", round: 1 }),
      line({ id: 2, text: "狼人 -> 7号", phase: "night", round: 1 }),
    ];
    render(<RailHarness lines={lines} onSelectEvent={onSelectEvent} />);

    await user.click(
      screen.getByRole("button", { name: "查看全部战报，共 2 条" }),
    );
    const dialog = await screen.findByRole("dialog", { name: "本轮战报" });

    await user.click(
      within(dialog).getByRole("button", { name: /跳转到.*狼人 -> 7号/ }),
    );

    expect(onSelectEvent).toHaveBeenCalledWith(2);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
