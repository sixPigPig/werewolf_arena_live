import { describe, expect, it } from "vitest";

import {
  stripSubtitlePunctuation,
  subtitleDisplayForElapsedMs,
} from "./liveVoiceSubtitleClock";
import type { LiveVoiceSubtitleCue } from "./liveVoiceStream";

function cue(
  text: string,
  startMs: number,
  endMs: number,
): LiveVoiceSubtitleCue {
  return { endMs, startMs, text };
}

describe("subtitleDisplayForElapsedMs", () => {
  it("shows the full punctuation-free phrase while lighting timed characters", () => {
    const cues = [cue("我", 0, 180), cue("先发言。", 180, 820)];

    expect(subtitleDisplayForElapsedMs(cues, 0)).toEqual({
      activeText: "我",
      completedText: "",
      pageIndex: 0,
      pendingText: "先发言",
      text: "我先发言",
    });
    expect(subtitleDisplayForElapsedMs(cues, 400)).toEqual({
      activeText: "发",
      completedText: "我先",
      pageIndex: 0,
      pendingText: "言",
      text: "我先发言",
    });
  });

  it("switches complete single-line pages at strong sentence boundaries", () => {
    const cues = [cue("第一句。第二句！", 0, 800)];

    expect(subtitleDisplayForElapsedMs(cues, 0)?.text).toBe("第一句");
    expect(subtitleDisplayForElapsedMs(cues, 360)).toMatchObject({
      activeText: "第",
      completedText: "",
      pageIndex: 1,
      pendingText: "二句",
      text: "第二句",
    });
  });

  it("uses weak punctuation when it produces two readable pages", () => {
    const cues = [cue("我觉得三号玩家有问题，但是现在不能下结论。", 0, 1900)];

    expect(subtitleDisplayForElapsedMs(cues, 0)?.text).toBe(
      "我觉得三号玩家有问题",
    );
    expect(subtitleDisplayForElapsedMs(cues, 960)?.text).toBe(
      "但是现在不能下结论",
    );
  });

  it("balances long phrases instead of leaving an orphaned final page", () => {
    const cues = [cue("一二三四五六七八九十甲乙丙丁戊己庚辛", 0, 1800)];

    expect(subtitleDisplayForElapsedMs(cues, 0)?.text).toBe(
      "一二三四五六七八九",
    );
    expect(subtitleDisplayForElapsedMs(cues, 860)?.text).toBe(
      "十甲乙丙丁戊己庚辛",
    );
  });
});

describe("stripSubtitlePunctuation", () => {
  it("removes Chinese and western punctuation while retaining word spacing", () => {
    expect(stripSubtitlePunctuation(" 请听，1号玩家！ Ready, go～? ")).toBe(
      "请听1号玩家 Ready go",
    );
  });
});
