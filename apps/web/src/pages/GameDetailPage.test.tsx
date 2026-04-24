import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithClient } from "../tests/renderWithClient";
import { GameDetailPage } from "./GameDetailPage";

const sessionId = "session_20260424_050950_66ea9f38";

const detailResponse = {
  session_id: sessionId,
  status: "complete",
  state: {
    session_id: sessionId,
    winner: "狼人阵营",
    error_message: "",
    players: [
      {
        name: "张三",
        role: "werewolf",
        model: "deepseek-chat",
      },
      {
        name: "李四",
        role: "villager",
        model: "minimax",
      },
    ],
    rounds: [
      {
        number: 1,
        players: ["张三", "李四"],
        eliminated: "李四",
        protected: null,
        investigated: null,
        exiled: null,
        debate: [{ speaker: "李四", message: "我不是狼。" }],
        bids: [{ 张三: 0.82 }],
        votes: [{ 李四: "张三" }],
        summaries: { 张三: "继续隐藏身份。" },
        success: true,
      },
    ],
  },
  logs: [
    {
      number: 1,
      eliminate: {
        actor: "张三",
        action: "remove",
        options: ["张三", "李四"],
        choice: "李四",
        lm_log: {
          prompt: "请选择今晚击杀对象。",
          raw_response: "{\"choice\":\"李四\"}",
          result: { choice: "李四" },
        },
      },
      protect: null,
      investigate: null,
      bid: [
        [
          {
            actor: "张三",
            action: "bid",
            options: ["0", "1"],
            choice: "0.82",
            lm_log: {
              prompt: "是否争取发言？",
              raw_response: "{\"score\":0.82}",
              result: { score: 0.82 },
            },
          },
        ],
      ],
      debate: [
        {
          actor: "李四",
          action: "debate",
          options: [],
          choice: "我不是狼。",
          lm_log: {
            prompt: "请发表白天发言。",
            raw_response: "{\"message\":\"我不是狼。\"}",
            result: { message: "我不是狼。" },
          },
        },
      ],
      votes: [
        [
          {
            actor: "李四",
            action: "vote",
            options: ["张三"],
            choice: "张三",
            lm_log: {
              prompt: "请选择放逐对象。",
              raw_response: "{\"choice\":\"张三\"}",
              result: { choice: "张三" },
            },
          },
        ],
      ],
      summaries: [
        {
          actor: "张三",
          action: "summarize",
          options: [],
          choice: "继续隐藏身份。",
          lm_log: {
            prompt: "总结本轮。",
            raw_response: "{\"summary\":\"继续隐藏身份。\"}",
            result: { summary: "继续隐藏身份。" },
          },
        },
      ],
    },
  ],
};

describe("GameDetailPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders replay detail and opens debug output for a selected action", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(detailResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    renderWithClient(
      <Routes>
        <Route path="/games/:sessionId" element={<GameDetailPage />} />
      </Routes>,
      `/games/${sessionId}`,
    );

    expect(await screen.findByText("狼人阵营")).toBeInTheDocument();
    expect(screen.getAllByText("张三").length).toBeGreaterThan(0);
    expect(
      screen.getByRole("heading", { name: "第 1 轮" }),
    ).toBeInTheDocument();
    expect(screen.getByText("李四 -> 我不是狼。")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", {
        name: /狼人击杀 张三 选择 李四/i,
      }),
    );

    expect(screen.getByText("请选择今晚击杀对象。")).toBeInTheDocument();
    expect(screen.getByText('{"choice":"李四"}')).toBeInTheDocument();
  });
});
