import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DebugPanel } from "./DebugPanel";
import type { DebugItem } from "../types";

describe("DebugPanel", () => {
  it("renders debug metadata and parsed fields with Chinese labels", () => {
    const item: DebugItem = {
      id: "debug-1",
      roundNumber: 2,
      phase: "day",
      title: "放逐投票",
      actor: "阿宁",
      action: "vote",
      choice: "老周",
      prompt: "请输出合法 JSON。",
      rawResponse: '{"reasoning":"他发言矛盾","vote":"老周"}',
      parsed: { reasoning: "他发言矛盾", vote: "老周" },
    };

    render(<DebugPanel item={item} />);

    expect(screen.getByText("轮次")).toBeInTheDocument();
    expect(screen.getByText("玩家")).toBeInTheDocument();
    expect(screen.getByText("选择")).toBeInTheDocument();
    expect(screen.getByText("提示词")).toBeInTheDocument();
    expect(screen.getByText("模型原文")).toBeInTheDocument();
    expect(screen.getByText("解析结果")).toBeInTheDocument();
    expect(screen.getByText(/推理：他发言矛盾/)).toBeInTheDocument();
    expect(screen.getByText(/投票对象：老周/)).toBeInTheDocument();
  });
});
