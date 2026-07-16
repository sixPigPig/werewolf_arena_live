import { describe, expect, it } from "vitest";

import type {
  GodViewPlayer,
  GodViewState,
  LiveNarrativeState,
  NarrativeCue,
} from "@werewolf-arena/game-client";

import {
  deriveMobileLiveSubtitle,
  type MobileLiveSubtitle,
  voiceSubtitleToMobileSubtitle,
} from "./mobileLiveSubtitle";

type TestPlayer = Pick<GodViewPlayer, "name" | "seatNumber">;

function narrative(overrides: {
  actorName?: string | null;
  action?: NarrativeCue["action"];
  judgeLine?: string;
  kind: NarrativeCue["kind"];
  speechText?: string;
}): LiveNarrativeState {
  const cue: NarrativeCue = {
    eventId: 1,
    kind: overrides.kind,
    tone: "day",
    judgeLine: overrides.judgeLine ?? "",
    performerLine: "",
    detailLine: "",
    actorName: overrides.actorName ?? null,
    action: overrides.action ?? null,
    speechText: overrides.speechText ?? "",
  };

  return {
    cue,
    speaker: null,
    nextSpeakerName: null,
    judgeLine: overrides.judgeLine ?? "",
    performerLine: "",
    detailLine: "",
  };
}

function godView(players: TestPlayer[]): Pick<GodViewState, "players"> {
  return {
    players: players.map(player),
  };
}

function player(overrides: TestPlayer): GodViewPlayer {
  return {
    seatNumber: overrides.seatNumber,
    name: overrides.name,
    role: "",
    camp: "好人阵营",
    identityGroup: "未知",
    isAlive: true,
    exitKind: null,
    statusLabel: "",
    stageStatus: {
      kind: "idle",
      label: "",
    },
    isSheriff: false,
    hasRaisedHand: false,
    hasWithdrawn: false,
    isSpeaking: false,
    voteTarget: null,
    receivedVotes: 0,
    suspicionScore: 0,
    clueTags: [],
    model: "",
    personalityId: "",
    appearanceId: "",
    avatarImageUrl: "",
  };
}

describe("deriveMobileLiveSubtitle", () => {
  it("returns player speech subtitles with seat-based color indexes", () => {
    const subtitle = deriveMobileLiveSubtitle({
      godViewState: godView([{ name: "阿青", seatNumber: 3 }]),
      narrativeState: narrative({
        actorName: "阿青",
        action: "debate",
        kind: "player-speaking",
        speechText: " 我先听后置位发言。 ",
      }),
    });

    expect(subtitle).toEqual<MobileLiveSubtitle>({
      activeText: "",
      completedText: "我先听后置位发言",
      pageIndex: 0,
      pendingText: "",
      speakerName: "3号玩家",
      text: "我先听后置位发言",
      tone: "player",
      colorIndex: 2,
    });
  });

  it("returns judge subtitles for public speech prompts", () => {
    const subtitle = deriveMobileLiveSubtitle({
      godViewState: godView([{ name: "阿青", seatNumber: 1 }]),
      narrativeState: narrative({
        actorName: "阿青",
        action: "sheriff_speech",
        judgeLine: "请听 1号玩家 的发言。",
        kind: "player-thinking",
      }),
    });

    expect(subtitle).toEqual<MobileLiveSubtitle>({
      activeText: "",
      completedText: "请听 1号玩家 的发言",
      pageIndex: 0,
      pendingText: "",
      speakerName: "法官",
      text: "请听 1号玩家 的发言",
      tone: "judge",
      colorIndex: 0,
    });
  });

  it("returns judge subtitles for judge narrative states", () => {
    const subtitle = deriveMobileLiveSubtitle({
      godViewState: godView([]),
      narrativeState: narrative({
        judgeLine: "夜晚降临，所有玩家请闭眼。",
        kind: "judge",
      }),
    });

    expect(subtitle).toEqual<MobileLiveSubtitle>({
      activeText: "",
      completedText: "夜晚降临所有玩家请闭眼",
      pageIndex: 0,
      pendingText: "",
      speakerName: "法官",
      text: "夜晚降临所有玩家请闭眼",
      tone: "judge",
      colorIndex: 0,
    });
  });

  it("filters non-speech narrative states", () => {
    const subtitle = deriveMobileLiveSubtitle({
      godViewState: godView([{ name: "阿青", seatNumber: 1 }]),
      narrativeState: narrative({
        actorName: "阿青",
        action: "vote",
        judgeLine: "请玩家投票。",
        kind: "vote",
        speechText: "投票给白石",
      }),
    });

    expect(subtitle).toBeNull();
  });

  it("falls back to a deterministic player color when no seat matches", () => {
    const first = deriveMobileLiveSubtitle({
      godViewState: godView([]),
      narrativeState: narrative({
        actorName: "临时玩家",
        action: "debate",
        kind: "player-speaking",
        speechText: "我会解释我的站边。",
      }),
    });
    const second = deriveMobileLiveSubtitle({
      godViewState: godView([]),
      narrativeState: narrative({
        actorName: "临时玩家",
        action: "debate",
        kind: "player-speaking",
        speechText: "第二句。",
      }),
    });

    expect(first?.speakerName).toBe("当前玩家");
    expect(first?.tone).toBe("player");
    expect(first?.colorIndex).toBeGreaterThanOrEqual(0);
    expect(first?.colorIndex).toBeLessThan(8);
    expect(second?.colorIndex).toBe(first?.colorIndex);
  });
});

describe("voiceSubtitleToMobileSubtitle", () => {
  it("preserves KTV progress while removing pause punctuation", () => {
    expect(
      voiceSubtitleToMobileSubtitle({
        activeText: "发",
        completedText: "我先，",
        pageIndex: 2,
        pendingText: "言。",
        speakerKind: "player",
        speakerName: "3号玩家",
        text: "我先，发言。",
        utteranceId: "voice-1",
      }),
    ).toEqual<MobileLiveSubtitle>({
      activeText: "发",
      colorIndex: 2,
      completedText: "我先",
      pageIndex: 2,
      pendingText: "言",
      speakerName: "3号玩家",
      text: "我先发言",
      tone: "player",
    });
  });

  it("keeps question and exclamation marks that carry spoken intent", () => {
    expect(
      voiceSubtitleToMobileSubtitle({
        activeText: "吗？",
        completedText: "你确定",
        pageIndex: 0,
        pendingText: "我不信！",
        speakerKind: "player",
        speakerName: "5号玩家",
        text: "你确定吗？我不信！",
        utteranceId: "voice-2",
      }),
    ).toMatchObject({
      activeText: "吗？",
      completedText: "你确定",
      pendingText: "我不信！",
      text: "你确定吗？我不信！",
    });
  });

  it("preserves KTV progress when numeric punctuation is active", () => {
    expect(
      voiceSubtitleToMobileSubtitle({
        activeText: "3.",
        completedText: "现在是",
        pageIndex: 0,
        pendingText: "5票",
        speakerKind: "player",
        speakerName: "2号玩家",
        text: "现在是3.5票",
        utteranceId: "voice-3",
      }),
    ).toMatchObject({
      activeText: "3.",
      completedText: "现在是",
      pendingText: "5票",
      text: "现在是3.5票",
    });
  });
});
