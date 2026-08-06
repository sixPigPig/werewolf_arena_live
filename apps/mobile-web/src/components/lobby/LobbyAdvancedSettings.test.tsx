import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { LobbyAdvancedSettings } from "./LobbyAdvancedSettings";

function AdvancedHarness({ error = null, initialMaxRounds = "8" }: { error?: string | null; initialMaxRounds?: string }) {
  const [seed, setSeed] = useState("");
  const [maxRounds, setMaxRounds] = useState(initialMaxRounds);
  const [audioMode, setAudioMode] = useState<"tts" | "text_only">("tts");
  return <LobbyAdvancedSettings audioMode={audioMode} disabled={false} maxRounds={maxRounds} maxRoundsError={error} onAudioModeChange={setAudioMode} onMaxRoundsChange={setMaxRounds} onSeedChange={setSeed} seed={seed} />;
}

describe("LobbyAdvancedSettings", () => {
  it("starts closed and exposes controlled settings after expansion", async () => {
    const user = userEvent.setup();
    render(<AdvancedHarness />);
    const summary = screen.getByText("高级设置 · 随机种子 / 8轮 / 语音播报");
    expect(summary.closest("details")).not.toHaveAttribute("open");
    await user.click(summary);
    await user.type(screen.getByRole("spinbutton", { name: "种子" }), "42");
    await user.clear(screen.getByRole("spinbutton", { name: "最大轮数" }));
    await user.type(screen.getByRole("spinbutton", { name: "最大轮数" }), "10");
    expect(screen.getByRole("spinbutton", { name: "种子" })).toHaveValue(42);
    await user.selectOptions(screen.getByRole("combobox", { name: "播报方式" }), "text_only");
    expect(screen.getByText("高级设置 · 种子 42 / 10轮 / 纯文本")).toBeVisible();
  });

  it("opens and focuses maximum rounds when validation fails", () => {
    render(<AdvancedHarness error="最大轮数必须是 1 到 20 的整数" initialMaxRounds="0" />);
    const input = screen.getByRole("spinbutton", { name: "最大轮数" });
    expect(input.closest("details")).toHaveAttribute("open");
    expect(input).toHaveFocus();
    expect(screen.getByRole("alert")).toHaveTextContent("最大轮数必须是 1 到 20 的整数");
  });
});
