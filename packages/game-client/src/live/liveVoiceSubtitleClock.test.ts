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

function subtitlePageTexts(text: string, endMs = 4000) {
  const pages = new Map<number, string>();
  const cues = [cue(text, 0, endMs)];

  for (let elapsedMs = 0; elapsedMs <= endMs; elapsedMs += 20) {
    const display = subtitleDisplayForElapsedMs(cues, elapsedMs);
    if (display) {
      pages.set(display.pageIndex, display.text);
    }
  }
  return [...pages.values()];
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

  it("balances long phrases without splitting detected words", () => {
    const cues = [cue("一二三四五六七八九十甲乙丙丁戊己庚辛", 0, 1800)];

    expect(subtitleDisplayForElapsedMs(cues, 0)?.text).toBe(
      "一二三四五六七八",
    );
    expect(subtitleDisplayForElapsedMs(cues, 860)?.text).toBe(
      "九十甲乙丙丁戊己庚辛",
    );
  });

  it("keeps seat numbers and decimal expressions on one page", () => {
    const seatNumberPages = subtitlePageTexts(
      "甲乙丙丁戊己庚辛壬癸子丑寅12号玩家卯辰巳午未申酉戌亥",
    );
    const decimalPages = subtitlePageTexts(
      "甲乙丙丁戊己庚辛壬癸子丑3.5票寅卯辰巳午未申酉戌亥",
    );

    expect(seatNumberPages.filter((page) => /\d/u.test(page))).toEqual([
      expect.stringContaining("12号玩家"),
    ]);
    expect(decimalPages.filter((page) => /\d/u.test(page))).toEqual([
      expect.stringContaining("3.5票"),
    ]);
  });

  it("preserves a numeric expression split across timing cues", () => {
    const cues = [cue("现在是3.", 0, 500), cue("5票", 500, 900)];

    expect(subtitleDisplayForElapsedMs(cues, 400)).toMatchObject({
      activeText: "3.",
      pendingText: "5票",
      text: "现在是3.5票",
    });
  });

  it("keeps English words and game terms on one page", () => {
    const englishPages = subtitlePageTexts(
      "甲乙丙丁戊己庚辛壬癸子丑PlayerOne寅卯辰巳午未申酉戌亥",
    );
    const gameTermPages = subtitlePageTexts(
      "甲乙丙丁戊己庚辛壬癸子丑警徽流寅卯辰巳午未申酉戌亥",
    );

    expect(englishPages.filter((page) => /[A-Z]/u.test(page))).toEqual([
      expect.stringContaining("PlayerOne"),
    ]);
    expect(gameTermPages.filter((page) => /[警徽流]/u.test(page))).toEqual([
      expect.stringContaining("警徽流"),
    ]);
  });

  it("allows up to two overflow columns for a single protected token", () => {
    const number = "123456789012345678";

    expect(subtitlePageTexts(number)).toEqual([number]);
  });
});

describe("stripSubtitlePunctuation", () => {
  it("removes pause punctuation while retaining spacing and expressive marks", () => {
    expect(stripSubtitlePunctuation(" 请听，1号玩家！ Ready, go～? ")).toBe(
      "请听1号玩家！ Ready go?",
    );
  });

  it("retains punctuation that belongs to numeric expressions", () => {
    expect(stripSubtitlePunctuation("3.5票，12:30，1-3号，80%！")).toBe(
      "3.5票12:301-3号80%！",
    );
  });
});
