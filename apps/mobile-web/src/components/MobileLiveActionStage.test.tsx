import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { GodViewPlayer, GodViewState } from "@werewolf-arena/game-client";

import { MobileLiveActionStage } from "./MobileLiveActionStage";
import type { MobileLiveFocusPresentation } from "./mobileLiveActionModel";

function player(overrides: Partial<GodViewPlayer> = {}): GodViewPlayer {
  return {
    seatNumber: 1,
    name: "阿青",
    role: "villager",
    camp: "好人阵营",
    identityGroup: "平民",
    isAlive: true,
    exitKind: null,
    statusLabel: "存活",
    stageStatus: { kind: "idle", label: "存活" },
    isSheriff: false,
    hasRaisedHand: false,
    isSpeaking: false,
    voteTarget: null,
    receivedVotes: 0,
    suspicionScore: 0,
    clueTags: [],
    model: "test-model",
    personalityId: "balanced",
    appearanceId: "default",
    avatarImageUrl: "/avatar.png",
    ...overrides,
  };
}

function stateWith(players: GodViewPlayer[]): GodViewState {
  return {
    boardName: "测试",
    dayNightLabel: "第 1 夜",
    phaseLabel: "夜晚",
    currentSeatLabel: "行动席：1 号",
    countdownLabel: "行动中",
    aliveLabel: "存活 3/3",
    winMode: "屠边",
    winnerLabel: "未结算",
    players,
    progress: {
      wolvesAlive: 1,
      godsAlive: 1,
      villagersAlive: 1,
      totalAlive: 3,
      totalPlayers: 3,
    },
    nightActions: [],
    nightResolution: { label: "等待夜间结算", detail: "", tone: "neutral" },
    nightActionOrder: [],
    deaths: [],
    isPeacefulNight: false,
    vote: { stageLabel: "最近票型", tallies: [], totalVotes: 0, topTarget: null },
    sheriff: {
      current: null,
      badgeFlow: "未移交",
      callTarget: null,
      candidates: [],
      voters: [],
    },
    sheriffSignUp: {
      active: false,
      requestedCount: 0,
      resolvedCount: 0,
      raised: [],
    },
    sheriffRuleState: { enabled: true, label: "警长规则开启" },
    speechOrder: [],
    speakerFlow: { previous: null, current: null, next: null, modeLabel: "等待发言" },
    eventLines: [],
    publicFacts: [],
    replayMarks: [],
    skillTriggers: [],
    winPressure: { label: "局势未到临界", detail: "", tone: "neutral" },
  };
}

function presentation(
  overrides: Partial<MobileLiveFocusPresentation>,
): MobileLiveFocusPresentation {
  return {
    eventId: 1,
    kind: "night-action",
    tone: "neutral",
    actorName: null,
    actorSeat: null,
    actorRole: null,
    targetName: null,
    eyebrow: "待命",
    title: "等待事件",
    detail: "",
    progress: null,
    accessibleText: "等待对局进展",
    ...overrides,
  };
}

describe("MobileLiveActionStage", () => {
  it("renders the speech portrait, name and public-speech label unchanged", () => {
    const currentPlayer = player({
      seatNumber: 1,
      name: "阿青",
      avatarImageUrl: "/avatar.png",
    });
    render(
      <MobileLiveActionStage
        presentation={presentation({
          kind: "speech",
          actorName: "阿青",
          actorSeat: 1,
          title: "1号 阿青发言",
          eyebrow: "公开发言",
          accessibleText: "1号 阿青公开发言",
        })}
        currentPlayer={currentPlayer}
        godViewState={stateWith([currentPlayer])}
      />,
    );

    const stage = screen.getByRole("status");
    expect(within(stage).getByText("阿青")).toBeVisible();
    expect(within(stage).getByText("公开发言")).toBeVisible();
    expect(stage.querySelector(".mobile-live-presenter img")).toHaveAttribute(
      "src",
      "/avatar.png",
    );
  });

  it("renders a parsed werewolf team action with target and tone", () => {
    render(
      <MobileLiveActionStage
        presentation={presentation({
          kind: "night-action",
          tone: "danger",
          actorName: "狼人阵营",
          actorSeat: null,
          eyebrow: "狼人阵营",
          title: "狼人目标",
          detail: "7号",
          accessibleText: "狼人阵营选择袭击 7号",
        })}
        currentPlayer={null}
        godViewState={stateWith([])}
      />,
    );

    const stage = screen.getByRole("status");
    expect(within(stage).getByText("狼人目标")).toBeVisible();
    expect(within(stage).getByText("7号")).toBeVisible();
    expect(stage.className).toContain("mobile-live-action-tone-danger");
    expect(stage.querySelector(".mobile-live-presenter img")).toBeNull();
    expect(stage.querySelector(".mobile-live-presenter svg")).not.toBeNull();
  });

  it("renders a witch save skip as 未使用 instead of hiding the action", () => {
    render(
      <MobileLiveActionStage
        presentation={presentation({
          kind: "night-action",
          tone: "neutral",
          actorName: "2号 女巫",
          actorSeat: 2,
          actorRole: "女巫",
          eyebrow: "女巫",
          title: "女巫解药",
          detail: "未使用",
          accessibleText: "女巫未使用解药",
        })}
        currentPlayer={null}
        godViewState={stateWith([])}
      />,
    );

    const stage = screen.getByRole("status");
    expect(within(stage).getByText("女巫解药")).toBeVisible();
    expect(within(stage).getByText("未使用")).toBeVisible();
    expect(within(stage).getByText("2号 女巫")).toBeVisible();
  });

  it("renders a parsed vote with voter, target and tally progress", () => {
    render(
      <MobileLiveActionStage
        presentation={presentation({
          kind: "vote-action",
          tone: "warning",
          actorName: "8号 猎人",
          actorSeat: 8,
          eyebrow: "白天投票",
          title: "8号 -> 1号",
          detail: "已投票",
          progress: "1/3",
          accessibleText: "8号投给1号，已投票",
        })}
        currentPlayer={null}
        godViewState={stateWith([])}
      />,
    );

    const stage = screen.getByRole("status");
    expect(within(stage).getByText("8号 -> 1号")).toBeVisible();
    expect(within(stage).getByText("已投票")).toBeVisible();
    expect(within(stage).getByText("1/3")).toBeVisible();
  });

  it("renders the top three vote totals and tie text", () => {
    render(
      <MobileLiveActionStage
        presentation={presentation({
          kind: "vote-result",
          tone: "warning",
          eyebrow: "投票结果",
          title: "平票",
          detail: "3号 2票 / 6号 2票",
          accessibleText: "平票，3号 2票，6号 2票",
        })}
        currentPlayer={null}
        godViewState={stateWith([])}
      />,
    );

    const stage = screen.getByRole("status");
    expect(within(stage).getByText("平票")).toBeVisible();
    expect(within(stage).getByText("3号 2票 / 6号 2票")).toBeVisible();
  });

  it("renders a night resolution outcome", () => {
    render(
      <MobileLiveActionStage
        presentation={presentation({
          kind: "night-result",
          tone: "danger",
          eyebrow: "夜间结算",
          title: "3号 夜晚死亡",
          detail: "3号 夜晚死亡，6号 被毒杀",
          accessibleText: "昨夜3号 夜晚死亡，6号 被毒杀",
        })}
        currentPlayer={null}
        godViewState={stateWith([])}
      />,
    );

    const stage = screen.getByRole("status");
    expect(within(stage).getByText("3号 夜晚死亡")).toBeVisible();
    expect(stage.querySelector(".mobile-live-action-detail")).toHaveTextContent(
      "6号 被毒杀",
    );
    expect(stage.className).toContain("mobile-live-action-tone-danger");
  });

  it("renders a readable fallback for unknown or malformed actions", () => {
    render(
      <MobileLiveActionStage
        presentation={presentation({
          kind: "night-action",
          tone: "neutral",
          actorName: "未知行动者",
          eyebrow: "狼人目标",
          title: "狼人目标",
          detail: "行动结果待确认",
          accessibleText: "未知行动者狼人目标待确认",
        })}
        currentPlayer={null}
        godViewState={stateWith([])}
      />,
    );

    const stage = screen.getByRole("status");
    expect(within(stage).getByText("行动结果待确认")).toBeVisible();
    expect(within(stage).queryByText("?")).not.toBeInTheDocument();
  });

  it("exposes one atomic polite status message and hides decorative icons", () => {
    render(
      <MobileLiveActionStage
        presentation={presentation({
          kind: "night-action",
          tone: "danger",
          actorName: "狼人阵营",
          eyebrow: "狼人阵营",
          title: "狼人目标",
          detail: "7号",
          accessibleText: "狼人阵营选择袭击 7号",
        })}
        currentPlayer={null}
        godViewState={stateWith([])}
      />,
    );

    const stage = screen.getByRole("status");
    expect(stage).toHaveAttribute("aria-live", "polite");
    expect(stage).toHaveAttribute("aria-atomic", "true");
    expect(stage).toHaveAttribute("aria-label", "当前舞台");
    expect(within(stage).getByText("狼人阵营")).toBeVisible();
    expect(within(stage).getByText("狼人目标")).toBeVisible();
    expect(stage.querySelector(".mobile-sr-only")).toHaveTextContent(
      "狼人阵营选择袭击 7号",
    );
    const presenter = stage.querySelector(".mobile-live-presenter");
    expect(presenter).toHaveAttribute("aria-hidden", "true");
  });
});
