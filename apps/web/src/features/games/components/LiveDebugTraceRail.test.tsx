import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { LiveDebugTrace } from "../liveDebugTrace";
import { LiveDebugTraceRail } from "./LiveDebugTraceRail";

const traces: LiveDebugTrace[] = [
  {
    action: "vote",
    actor: "林恩",
    choice: "周明",
    eventIds: [10, 11, 12, 13, 14],
    id: "trace-ok",
    impactSummary: ["票型更新"],
    nodes: [
      { eventId: 10, kind: "request", label: "行动请求", status: "ok" },
      { eventId: 11, kind: "model", label: "模型返回", status: "ok" },
      { eventId: 12, kind: "parsed", label: "解析完成", status: "ok" },
      { eventId: 13, kind: "state", label: "状态更新", status: "ok" },
      { eventId: 14, kind: "stage", label: "舞台同步", status: "ok" },
    ],
    parsed: { vote: "周明" },
    payloads: [
      { eventId: 10, payload: { actor: "林恩" }, type: "action_requested" },
      { eventId: 13, payload: { votes: { 林恩: "周明" } }, type: "state_updated" },
    ],
    phase: "day",
    prompt: "请林恩投票。",
    rawResponse: "我投给周明。",
    relatedPlayers: ["林恩", "周明"],
    round: 2,
    stateDiff: [{ after: "{\"林恩\":\"周明\"}", before: "未记录", label: "票型" }],
    status: "ok",
    title: "林恩 · 投票",
    warnings: [],
  },
  {
    action: "investigate",
    actor: "秦澈",
    choice: "白鹿",
    eventIds: [20, 21],
    id: "trace-warning",
    impactSummary: [],
    nodes: [
      { eventId: 20, kind: "request", label: "行动请求", status: "ok" },
      { eventId: 21, kind: "model", label: "模型返回", status: "warning" },
    ],
    parsed: null,
    payloads: [{ eventId: 20, payload: { target: "白鹿" }, type: "action_requested" }],
    phase: "night",
    prompt: "请预言家查验。",
    rawResponse: "",
    relatedPlayers: ["秦澈", "白鹿"],
    round: 2,
    stateDiff: [],
    status: "warning",
    title: "秦澈 · 查验",
    warnings: ["解析结果缺失", "选择未影响状态"],
  },
  {
    action: "vote",
    actor: "周明",
    choice: "林恩",
    eventIds: [30, 31, 32],
    id: "trace-error",
    impactSummary: ["票型更新"],
    nodes: [
      { eventId: 30, kind: "request", label: "行动请求", status: "ok" },
      { eventId: 31, kind: "parsed", label: "解析完成", status: "error" },
      { eventId: 32, kind: "state", label: "状态更新", status: "ok" },
    ],
    parsed: { vote: "林恩" },
    payloads: [{ eventId: 32, payload: { votes: { 周明: "白鹿" } }, type: "state_updated" }],
    phase: "day",
    prompt: "请周明投票。",
    rawResponse: "林恩。",
    relatedPlayers: ["周明", "林恩"],
    round: 2,
    stateDiff: [{ after: "{\"周明\":\"白鹿\"}", before: "未记录", label: "票型" }],
    status: "error",
    title: "周明 · 投票",
    warnings: ["解析与状态不一致"],
  },
];

describe("LiveDebugTraceRail", () => {
  it("renders trace cards with event range, title, status nodes, and impact summary", () => {
    render(<LiveDebugTraceRail traces={traces} />);

    expect(screen.getByTestId("live-debug-trace-rail")).toHaveTextContent(
      "按行动聚合 · 当前 3 条",
    );

    const card = screen.getByTestId("live-debug-trace-card-trace-ok");
    expect(card).toHaveTextContent("#10-14");
    expect(card).toHaveTextContent("林恩 · 投票");
    expect(card).toHaveTextContent("OK");
    expect(card).toHaveTextContent("票型更新");

    const nodes = within(card).getAllByTestId("live-debug-trace-node");
    expect(nodes.map((node) => node.textContent)).toEqual([
      "request",
      "model",
      "parsed",
      "state",
      "stage",
    ]);
    expect(nodes[0]).toHaveAttribute("aria-label", "request: 行动请求 (ok)");
    expect(nodes[4]).toHaveAttribute("aria-label", "stage: 舞台同步 (ok)");
  });

  it("clicking a trace expands details and calls onSelectTrace(trace)", async () => {
    const user = userEvent.setup();
    const onSelectTrace = vi.fn();

    render(<LiveDebugTraceRail traces={traces} onSelectTrace={onSelectTrace} />);

    await user.click(screen.getByRole("button", { name: /林恩 · 投票/ }));

    expect(onSelectTrace).toHaveBeenCalledWith(traces[0]);
    expect(
      screen.getByRole("button", { name: /林恩 · 投票/ }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("状态变化")).toBeInTheDocument();
    expect(screen.getByText("Prompt")).toBeInTheDocument();
    expect(screen.getByText("Raw response")).toBeInTheDocument();
    expect(screen.getByText("Parsed result")).toBeInTheDocument();
    expect(screen.getByText("Payload JSON")).toBeInTheDocument();
    expect(screen.getByText("请林恩投票。")).toBeInTheDocument();
  });

  it("expands the controlled selected trace and reports selecting a different trace", async () => {
    const user = userEvent.setup();
    const onSelectTrace = vi.fn();

    render(
      <LiveDebugTraceRail
        onSelectTrace={onSelectTrace}
        selectedTraceId="trace-warning"
        traces={traces}
      />,
    );

    expect(
      screen.getByRole("button", { name: /秦澈 · 查验/ }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("请预言家查验。")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /周明 · 投票/ }));

    expect(onSelectTrace).toHaveBeenCalledWith(traces[2]);
  });

  it("filters OK traces when only issues is enabled", async () => {
    const user = userEvent.setup();
    render(<LiveDebugTraceRail traces={traces} />);

    const issueFilter = screen.getByRole("button", { name: "只看异常" });
    expect(issueFilter).toHaveAttribute("aria-pressed", "false");

    await user.click(issueFilter);

    expect(issueFilter).toHaveAttribute("aria-pressed", "true");

    expect(
      screen.queryByTestId("live-debug-trace-card-trace-ok"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("live-debug-trace-card-trace-warning"),
    ).toHaveTextContent("需关注");
    expect(
      screen.getByTestId("live-debug-trace-card-trace-error"),
    ).toHaveTextContent("异常");
  });
});
