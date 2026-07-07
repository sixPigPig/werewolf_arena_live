import { describe, expect, it } from "vitest";

import {
  deriveMobileLiveSubtitle,
  type MobileLiveSubtitle,
} from "./mobileLiveSubtitle";

type TestPlayer = {
  name: string;
  seatNumber: number;
};

function narrative(overrides: {
  actorName?: string | null;
  action?: string | null;
  judgeLine?: string;
  kind: string;
  speechText?: string;
}) {
  return {
    cue: {
      eventId: 1,
      kind: overrides.kind,
      tone: "day",
      judgeLine: overrides.judgeLine ?? "",
      performerLine: "",
      detailLine: "",
      actorName: overrides.actorName ?? null,
      action: overrides.action ?? null,
      speechText: overrides.speechText ?? "",
    },
    speaker: null,
    nextSpeakerName: null,
    judgeLine: overrides.judgeLine ?? "",
    performerLine: "",
    detailLine: "",
  };
}

function godView(players: TestPlayer[]) {
  return {
    players,
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
      speakerName: "阿青",
      text: "我先听后置位发言。",
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
        judgeLine: "请听 阿青 的发言。",
        kind: "player-thinking",
      }),
    });

    expect(subtitle).toEqual<MobileLiveSubtitle>({
      speakerName: "法官",
      text: "请听 阿青 的发言。",
      tone: "judge",
      colorIndex: 0,
    });
  });

  it("returns judge subtitles for judge narrative states", () => {
    const subtitle = deriveMobileLiveSubtitle({
      godViewState: godView([]),
      narrativeState: narrative({
        judgeLine: "天黑请闭眼。",
        kind: "judge",
      }),
    });

    expect(subtitle).toEqual<MobileLiveSubtitle>({
      speakerName: "法官",
      text: "天黑请闭眼。",
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

    expect(first?.speakerName).toBe("临时玩家");
    expect(first?.tone).toBe("player");
    expect(first?.colorIndex).toBeGreaterThanOrEqual(0);
    expect(first?.colorIndex).toBeLessThan(8);
    expect(second?.colorIndex).toBe(first?.colorIndex);
  });
});
