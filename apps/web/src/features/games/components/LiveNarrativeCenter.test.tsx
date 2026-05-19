import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { LiveNarrativeState } from "../liveNarrative";
import { LiveNarrativeCenter } from "./LiveNarrativeCenter";

function narrative(
  overrides: Partial<LiveNarrativeState> = {},
): LiveNarrativeState {
  return {
    cue: {
      action: "debate",
      actorName: "Sam",
      detailLine: "下一位：Isaac",
      eventId: 12,
      judgeLine: "请听 Sam 的发言。",
      kind: "player-speaking",
      performerLine: "Sam 正在发言。",
      speechText: "我会先盘昨晚平安夜，再解释为什么 Isaac 可疑。",
      tone: "day",
    },
    detailLine: "下一位：Isaac",
    judgeLine: "请听 Sam 的发言。",
    nextSpeakerName: "Isaac",
    performerLine: "Sam 正在发言。",
    speaker: {
      appearanceId: "moonlit",
      avatarImageUrl: "",
      camp: "好人阵营",
      name: "Sam",
      role: "村民",
      seatNumber: 8,
    },
    ...overrides,
  };
}

describe("LiveNarrativeCenter", () => {
  it("renders judge narration, speaker identity, badges, tone, and speech text", () => {
    render(<LiveNarrativeCenter narrative={narrative()} />);

    const center = screen.getByTestId("live-narrative-center");
    expect(center).toHaveAttribute("data-narrative-tone", "day");
    expect(screen.getByText("法官旁白")).toBeInTheDocument();
    expect(screen.getByText("公开发言")).toBeInTheDocument();
    expect(screen.getByText("#12")).toBeInTheDocument();
    expect(screen.getByText("请听 Sam 的发言。")).toBeInTheDocument();
    expect(screen.getByText("8 号")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sam" })).toBeInTheDocument();
    expect(screen.getByText("村民")).toBeInTheDocument();
    expect(screen.getByText("好人阵营")).toBeInTheDocument();
    expect(
      screen.getByText("我会先盘昨晚平安夜，再解释为什么 Isaac 可疑。"),
    ).toBeInTheDocument();
    expect(screen.getByText("下一位：Isaac")).toBeInTheDocument();
  });

  it("renders performer and detail lines when no speech text exists", () => {
    render(
      <LiveNarrativeCenter
        narrative={narrative({
          cue: {
            action: "vote",
            actorName: null,
            detailLine: "当前最高票：Isaac，2 票。",
            eventId: 20,
            judgeLine: "投票结果公布。",
            kind: "vote",
            performerLine: "票型已经更新。",
            speechText: "",
            tone: "vote",
          },
          detailLine: "当前最高票：Isaac，2 票。",
          judgeLine: "投票结果公布。",
          nextSpeakerName: null,
          performerLine: "票型已经更新。",
          speaker: null,
        })}
      />,
    );

    expect(screen.getByTestId("live-narrative-center")).toHaveAttribute(
      "data-narrative-tone",
      "vote",
    );
    expect(screen.getByText("投票")).toBeInTheDocument();
    expect(screen.getByText("#20")).toBeInTheDocument();
    expect(screen.getByText("投票结果公布。")).toBeInTheDocument();
    expect(screen.getByText("票型已经更新。")).toBeInTheDocument();
    expect(screen.getByText("当前最高票：Isaac，2 票。")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sam" })).not.toBeInTheDocument();
  });

  it("omits event id and detail badges when values are empty", () => {
    render(
      <LiveNarrativeCenter
        narrative={narrative({
          cue: {
            action: null,
            actorName: null,
            detailLine: "",
            eventId: null,
            judgeLine: "等待导播事件",
            kind: "fallback",
            performerLine: "等待玩家行动。",
            speechText: "",
            tone: "neutral",
          },
          detailLine: "",
          judgeLine: "等待导播事件",
          nextSpeakerName: null,
          performerLine: "等待玩家行动。",
          speaker: null,
        })}
      />,
    );

    expect(screen.queryByText(/^#/)).not.toBeInTheDocument();
    expect(screen.getByText("等待导播事件")).toBeInTheDocument();
    expect(screen.getByText("等待玩家行动。")).toBeInTheDocument();
  });
});
