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
    expect(subtitleDisplayForElapsedMs(cues, 730)).toEqual({
      activeText: "",
      completedText: "我先发言",
      pageIndex: 0,
      pendingText: "",
      text: "我先发言",
    });
  });

  it("switches readable single-line pages at strong sentence boundaries", () => {
    const cues = [cue("第一句。第二句！", 0, 2000)];

    expect(subtitleDisplayForElapsedMs(cues, 0)?.text).toBe("第一句");
    expect(subtitleDisplayForElapsedMs(cues, 900)).toMatchObject({
      activeText: "",
      completedText: "第一句",
      pageIndex: 0,
      pendingText: "",
    });
    expect(subtitleDisplayForElapsedMs(cues, 960)).toMatchObject({
      activeText: "第",
      completedText: "",
      pageIndex: 1,
      pendingText: "二句！",
      text: "第二句！",
    });
  });

  it("merges fast sentence fragments so they remain readable", () => {
    const cues = [cue("第一句。第二句！", 0, 800)];

    expect(subtitleDisplayForElapsedMs(cues, 0)?.text).toBe(
      "第一句 第二句！",
    );
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

  it("treats weak punctuation as a candidate boundary and joins short lead-ins", () => {
    const cues = [
      cue("我认为，三号玩家身份偏坏。但是，我还想再听听。", 0, 2600),
    ];

    expect(subtitleDisplayForElapsedMs(cues, 0)?.text).toBe(
      "我认为 三号玩家身份偏坏",
    );
    expect(subtitleDisplayForElapsedMs(cues, 1500)?.text).toBe(
      "但是 我还想再听听",
    );
  });

  it("joins consecutive short punctuation fragments with spaces", () => {
    const cues = [cue("不，是，好人会解释。", 0, 700)];

    expect(subtitleDisplayForElapsedMs(cues, 0)?.text).toBe(
      "不 是 好人会解释",
    );
  });

  it("joins a trailing two-character fragment back to the previous phrase", () => {
    const cues = [cue("我认为三号有问题。你呢？", 0, 1000)];

    expect(subtitleDisplayForElapsedMs(cues, 0)?.text).toBe(
      "我认为三号有问题 你呢？",
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
  it("removes pause punctuation while retaining spacing and expressive marks", () => {
    expect(stripSubtitlePunctuation(" 请听，1号玩家！ Ready, go～? ")).toBe(
      "请听1号玩家！ Ready go?",
    );
  });
});
