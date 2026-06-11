import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useCallback, useRef, useState } from "react";
import { describe, expect, it } from "vitest";

import type { RuleSetSummary } from "../types";
import { RuleDetailsDrawer } from "./RuleDetailsDrawer";

const classicRule: RuleSetSummary = {
  id: "classic_8",
  version: "2026.04",
  name: "经典 8 人局",
  description: "标准配置，适合完整推演。",
  player_count: 8,
  roles: [],
  role_summary: "2 狼人 / 6 好人",
  sheriff_enabled: false,
  speech_policy: "sequential",
  rule_tags: ["屠边"],
};

function Harness() {
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const closeDrawer = useCallback(() => setOpen(false), []);

  return (
    <>
      <button onClick={() => setOpen(true)} ref={triggerRef} type="button">
        规则详情
      </button>
      <RuleDetailsDrawer
        onClose={closeDrawer}
        open={open}
        returnFocusRef={triggerRef}
        rule={classicRule}
      />
    </>
  );
}

describe("RuleDetailsDrawer", () => {
  it("shows rule details, focuses close, and restores trigger focus on Escape", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    const trigger = screen.getByRole("button", { name: "规则详情" });
    await user.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "经典 8 人局规则" });
    expect(within(dialog).getByText("阵营配置")).toBeInTheDocument();
    expect(within(dialog).getByText("无警长")).toBeInTheDocument();
    expect(within(dialog).getByText(/好人放逐所有狼人/)).toBeInTheDocument();

    const closeButton = within(dialog).getByRole("button", {
      name: "关闭规则详情",
    });
    expect(closeButton).toHaveFocus();

    await user.keyboard("{Escape}");

    expect(
      screen.queryByRole("dialog", { name: "经典 8 人局规则" }),
    ).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("closes only when the backdrop itself receives a mouse down", async () => {
    const user = userEvent.setup();
    const { container } = render(<Harness />);

    await user.click(screen.getByRole("button", { name: "规则详情" }));

    const dialog = screen.getByRole("dialog", { name: "经典 8 人局规则" });
    fireEvent.mouseDown(dialog);
    expect(dialog).toBeInTheDocument();

    const backdrop = container.querySelector(".lobby-rule-drawer-backdrop");
    expect(backdrop).not.toBeNull();
    fireEvent.mouseDown(backdrop as Element);

    expect(
      screen.queryByRole("dialog", { name: "经典 8 人局规则" }),
    ).not.toBeInTheDocument();
  });

  it("keeps Tab focus inside the drawer", async () => {
    const user = userEvent.setup();
    render(<Harness />);

    await user.click(screen.getByRole("button", { name: "规则详情" }));

    const dialog = screen.getByRole("dialog", { name: "经典 8 人局规则" });
    const closeButton = screen.getByRole("button", {
      name: "关闭规则详情",
    });
    const disabledButton = document.createElement("button");
    disabledButton.disabled = true;
    dialog.prepend(disabledButton);
    const finalLink = document.createElement("a");
    finalLink.href = "#rules-end";
    finalLink.textContent = "规则末尾";
    dialog.append(finalLink);

    finalLink.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(closeButton).toHaveFocus();
  });
});
