import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderWithClient } from "../tests/renderWithClient";
import { GameDetailPage } from "./GameDetailPage";

const sessionId = "session_20260424_050950_66ea9f38";
const nextSessionId = "session_20260424_060000_next";

const detailResponse = {
  session_id: sessionId,
  status: "complete",
  state: {
    session_id: sessionId,
    winner: "狼人阵营",
    error_message: "",
    rule_set: {
      id: "social_8",
      version: "2026.04",
      name: "无神职心理局",
      player_count: 8,
      roles: [
        { role: "狼人", count: 2 },
        { role: "村民", count: 6 },
      ],
      role_summary: "2 狼人 / 6 村民",
    },
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
        bids: [{ 张三: 0.82 }, { 张三: 0.41 }],
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
          {
            actor: "张三",
            action: "bid",
            options: ["0", "1"],
            choice: "0.41",
            lm_log: {
              prompt: "是否继续争取发言？",
              raw_response: "{\"score\":0.41}",
              result: { score: 0.41 },
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

const nextDetailResponse = {
  ...detailResponse,
  session_id: nextSessionId,
  state: {
    ...detailResponse.state,
    session_id: nextSessionId,
    winner: "好人阵营",
    rounds: [
      {
        ...detailResponse.state.rounds[0],
        eliminated: "张三",
        bids: [{ 李四: 0.33 }],
      },
    ],
  },
  logs: [
    {
      ...detailResponse.logs[0],
      eliminate: {
        ...detailResponse.logs[0].eliminate,
        choice: "张三",
        lm_log: {
          prompt: "新对局请选择今晚击杀对象。",
          raw_response: "{\"choice\":\"张三\"}",
          result: { choice: "张三" },
        },
      },
      bid: [
        [
          {
            actor: "李四",
            action: "bid",
            options: ["0", "1"],
            choice: "0.33",
            lm_log: {
              prompt: "新对局是否争取发言？",
              raw_response: "{\"score\":0.33}",
              result: { score: 0.33 },
            },
          },
        ],
      ],
    },
  ],
};

function mockGameDetailFetch() {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    const body = url.includes(nextSessionId)
      ? nextDetailResponse
      : detailResponse;

    return Promise.resolve(
      new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
}

describe("GameDetailPage", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders replay detail and opens debug output for a selected action", async () => {
    mockGameDetailFetch();

    const { container } = renderWithClient(
      <Routes>
        <Route path="/games/:sessionId" element={<GameDetailPage />} />
      </Routes>,
      `/games/${sessionId}`,
    );

    expect(await screen.findByText("狼人阵营")).toBeInTheDocument();
    const pageMain = container.querySelector("main");
    expect(container.querySelectorAll("main")).toHaveLength(1);
    expect(pageMain).toHaveClass(
      "max-w-7xl",
      "grid",
      "lg:grid-cols-[18rem_minmax(0,1fr)_22rem]",
    );
    expect(await screen.findByText("无神职心理局")).toBeInTheDocument();
    expect(screen.getByText("2 狼人 / 6 村民")).toBeInTheDocument();
    expect(screen.getAllByText("张三").length).toBeGreaterThan(0);
    expect(
      screen.getByRole("heading", { name: "第 1 轮" }),
    ).toBeInTheDocument();
    expect(screen.getByText("李四 -> 我不是狼。")).toBeInTheDocument();
    expect(screen.getByText("请选择今晚击杀对象。")).toBeInTheDocument();
    expect(screen.getByText('{"choice":"李四"}')).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", {
        name: /发言竞价 张三 选择 0.82/i,
      }),
    );

    expect(screen.queryByText("请选择今晚击杀对象。")).not.toBeInTheDocument();
    expect(screen.getByText("是否争取发言？")).toBeInTheDocument();
    expect(screen.getByText('{"score":0.82}')).toBeInTheDocument();
  });

  it("resets the selected debug item when navigating to another session", async () => {
    mockGameDetailFetch();

    renderWithClient(
      <>
        <Link to={`/games/${nextSessionId}`}>下一局</Link>
        <Routes>
          <Route path="/games/:sessionId" element={<GameDetailPage />} />
        </Routes>
      </>,
      `/games/${sessionId}`,
    );

    expect(await screen.findByText("请选择今晚击杀对象。")).toBeInTheDocument();

    await userEvent.click(
      screen.getByRole("button", {
        name: /发言竞价 张三 选择 0.82/i,
      }),
    );

    expect(screen.getByText("是否争取发言？")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("link", { name: "下一局" }));

    expect(
      await screen.findByText("新对局请选择今晚击杀对象。"),
    ).toBeInTheDocument();
    expect(screen.queryByText("新对局是否争取发言？")).not.toBeInTheDocument();
  });
});
