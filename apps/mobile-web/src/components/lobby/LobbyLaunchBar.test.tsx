import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LobbyLaunchBar } from "./LobbyLaunchBar";

const incomplete = { assignedCount: 5, emptySeatCount: 3, profileShortageCount: 0, summaryText: "已选 5/8 · 可自动补齐", ctaLabel: "还差 3 位", canLaunch: false };

describe("LobbyLaunchBar", () => {
  it("renders one disabled remaining-seat action", () => {
    render(<LobbyLaunchBar error={null} isLaunchDisabled isPending={false} onLaunch={vi.fn()} status={incomplete} />);
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "还差 3 位" })).toBeDisabled();
  });

  it("shows pending and create-error states without losing progress", () => {
    render(<LobbyLaunchBar error="无法发起对局" isLaunchDisabled isPending onLaunch={vi.fn()} status={{ assignedCount: 8, emptySeatCount: 0, profileShortageCount: 0, summaryText: "已选 8/8 · 阵容已就绪", ctaLabel: "开始对局", canLaunch: true }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("无法发起对局");
    expect(screen.getByRole("button", { name: "发起中…" })).toBeDisabled();
    expect(screen.getByText("已选 8/8 · 阵容已就绪")).toBeVisible();
  });
});
