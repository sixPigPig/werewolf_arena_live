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

const resolvedVoteResponse = {
  ...detailResponse,
  state: {
    ...detailResponse.state,
    winner: "好人阵营",
    rule_set: {
      id: "starter_6",
      version: "2026.04",
      name: "新手 6 人快局",
      player_count: 6,
      roles: [
        { role: "狼人", count: 1, team: "werewolves" },
        { role: "预言家", count: 1, team: "villagers" },
        { role: "医生", count: 1, team: "villagers" },
        { role: "村民", count: 3, team: "villagers" },
      ],
      role_summary: "1 狼人 / 1 预言家 / 1 医生 / 3 村民",
    },
    players: [
      { name: "Dan", role: "狼人", model: "deepseek-chat" },
      { name: "Bert", role: "预言家", model: "deepseek-chat" },
      { name: "David", role: "医生", model: "deepseek-chat" },
      { name: "Paul", role: "村民", model: "deepseek-chat" },
      { name: "Jackson", role: "村民", model: "deepseek-chat" },
      { name: "Scott", role: "村民", model: "deepseek-chat" },
    ],
    rounds: [
      {
        number: 1,
        players: ["Dan", "Bert", "David", "Paul", "Jackson", "Scott"],
        eliminated: "Bert",
        protected: "David",
        investigated: "Dan",
        exiled: "Dan",
        debate: [
          { speaker: "Dan", message: "David 昨晚有点安静。" },
          { speaker: "David", message: "Dan 急着怀疑别人，有点反常。" },
        ],
        bids: [{ Dan: 2, David: 0, Paul: 0, Jackson: 0, Scott: 0 }],
        votes: [
          {
            Dan: "David",
            David: "Dan",
            Paul: "Dan",
            Jackson: "Dan",
            Scott: "Dan",
          },
        ],
        summaries: {},
        success: true,
      },
    ],
  },
  logs: detailResponse.logs,
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

  it("shows protected night attacks as saved attacks in replay", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          ...detailResponse,
          state: {
            ...detailResponse.state,
            rounds: [
              {
                ...detailResponse.state.rounds[0],
                attacked: "李四",
                eliminated: null,
                protected: "李四",
                investigated: "张三",
              },
            ],
          },
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    renderWithClient(
      <Routes>
        <Route path="/games/:sessionId" element={<GameDetailPage />} />
      </Routes>,
      `/games/${sessionId}`,
    );

    expect(await screen.findByText("袭击")).toBeInTheDocument();
    expect(screen.getAllByText("李四").length).toBeGreaterThan(0);
    expect(screen.getByText("李四 被守护，平安夜")).toBeInTheDocument();
  });

  it("shows vote tally, exile resolution, and final winner", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(resolvedVoteResponse), {
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

    expect(await screen.findByText("场次胜者：好人阵营")).toBeInTheDocument();
    expect(screen.getByText("Dan：4票")).toBeInTheDocument();
    expect(screen.getByText("多数门槛 3/5")).toBeInTheDocument();
    expect(screen.getByText("Dan 被放逐")).toBeInTheDocument();
    expect(screen.getByText("Dan 被放逐，狼人全部出局")).toBeInTheDocument();
  });

  it("keeps repeated bid rounds grouped by speaker selection turn", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          ...detailResponse,
          state: {
            ...detailResponse.state,
            players: [
              { name: "Jackson", role: "狼人", model: "deepseek-chat" },
              { name: "Tyler", role: "预言家", model: "deepseek-chat" },
              { name: "Hayley", role: "医生", model: "deepseek-chat" },
              { name: "Mason", role: "村民", model: "deepseek-chat" },
              { name: "Bert", role: "村民", model: "deepseek-chat" },
              { name: "Isaac", role: "村民", model: "deepseek-chat" },
            ],
            rounds: [
              {
                ...detailResponse.state.rounds[0],
                players: ["Jackson", "Tyler", "Hayley", "Mason", "Bert", "Isaac"],
                eliminated: "Tyler",
                protected: "Hayley",
                investigated: "Mason",
                debate: [
                  { speaker: "Bert", message: "Tyler 出局了，先听大家看法。" },
                  { speaker: "Jackson", message: "Tyler 出局有点突然。" },
                ],
                bids: [
                  { Jackson: 0, Hayley: 0, Mason: 0, Bert: 0, Isaac: 0 },
                  { Jackson: 1, Hayley: 0, Mason: 0, Isaac: 0 },
                ],
              },
            ],
          },
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    renderWithClient(
      <Routes>
        <Route path="/games/:sessionId" element={<GameDetailPage />} />
      </Routes>,
      `/games/${sessionId}`,
    );

    expect(await screen.findByText("第 1 次发言竞价")).toBeInTheDocument();
    expect(screen.getByText("发言人：Bert")).toBeInTheDocument();
    expect(screen.getByText("第 2 次发言竞价")).toBeInTheDocument();
    expect(screen.getByText("发言人：Jackson")).toBeInTheDocument();
  });
});
