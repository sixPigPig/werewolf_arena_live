import { useRef, useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { LobbyModal } from "./LobbyModal";

function ModalHarness() {
  const [isOpen, setIsOpen] = useState(false);
  const backgroundRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const initialFocusRef = useRef<HTMLInputElement | null>(null);

  return (
    <main>
      <div ref={backgroundRef}>
        <button ref={triggerRef} onClick={() => setIsOpen(true)} type="button">
          打开选择器
        </button>
      </div>
      {isOpen ? (
        <LobbyModal
          backgroundRef={backgroundRef}
          className="test-dialog"
          initialFocusRef={initialFocusRef}
          labelledBy="test-dialog-title"
          onClose={() => setIsOpen(false)}
          restoreFocusRef={triggerRef}
        >
          <h2 id="test-dialog-title">测试选择器</h2>
          <input aria-label="搜索" ref={initialFocusRef} />
          <button onClick={() => setIsOpen(false)} type="button">
            完成
          </button>
        </LobbyModal>
      ) : null}
    </main>
  );
}

describe("LobbyModal", () => {
  it("isolates the background, traps focus, closes on Escape, and restores focus", async () => {
    const user = userEvent.setup();
    render(<ModalHarness />);
    const trigger = screen.getByRole("button", { name: "打开选择器" });

    await user.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "测试选择器" });
    const search = screen.getByRole("textbox", { name: "搜索" });
    const done = screen.getByRole("button", { name: "完成" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(trigger.parentElement).toHaveAttribute("inert");
    await waitFor(() => expect(search).toHaveFocus());

    await user.tab({ shift: true });
    expect(done).toHaveFocus();
    await user.tab();
    expect(search).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(trigger.parentElement).not.toHaveAttribute("inert");
  });
});
