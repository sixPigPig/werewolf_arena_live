import type {
  LiveVoiceQueueItem,
  LiveVoiceSubtitle,
  LiveVoiceSubtitleCue,
} from "./liveVoiceStream";

export const SUBTITLE_CLOCK_POLL_INTERVAL_MS = 50;
export const SUBTITLE_CUE_LEAD_MS = 40;
export const SUBTITLE_PAGE_MAX_COLUMNS = 16;

const MIN_BALANCED_PAGE_COLUMNS = 6;
const SUBTITLE_PUNCTUATION = /^(?:\p{P}|[~～])$/u;
const STRONG_SUBTITLE_BREAK = /^[。！？!?；;.]$/u;
const WEAK_SUBTITLE_BREAK = /^[，,、：:]$/u;
const SUBTITLE_EMOJI = /^\p{Extended_Pictographic}$/u;
const SUBTITLE_SEGMENTER = new Intl.Segmenter("zh-CN", {
  granularity: "grapheme",
});

export type LiveVoiceSubtitleClock = {
  elapsedMs: number;
  utteranceId: string;
} | null;

export type LiveVoiceSubtitleDisplay = {
  activeText: string;
  completedText: string;
  pageIndex: number;
  pendingText: string;
  text: string;
};

type SubtitleBreakStrength = "none" | "weak" | "strong";

type TimedSubtitleUnit = {
  breakAfter: SubtitleBreakStrength;
  columnWidth: number;
  endMs: number;
  startMs: number;
  text: string;
};

type SubtitlePage = {
  startMs: number;
  units: TimedSubtitleUnit[];
};

export function isPcmAudioFormat(audioFormat: string) {
  return audioFormat.toLowerCase() === "pcm";
}

export function subtitleElapsedMsForItem({
  audio,
  context,
  item,
  pcmStartTimes,
}: {
  audio: HTMLAudioElement | null;
  context: AudioContext | null;
  item: LiveVoiceQueueItem;
  pcmStartTimes: Map<string, number>;
}) {
  if (isPcmAudioFormat(item.audioFormat)) {
    if (!context) {
      return null;
    }
    const startTime = pcmStartTimes.get(item.utteranceId);
    if (startTime === undefined) {
      return null;
    }
    return Math.max(0, Math.round((context.currentTime - startTime) * 1000));
  }

  if (!audio) {
    return null;
  }
  return Math.max(0, Math.round(audio.currentTime * 1000));
}

export function currentSubtitleForItem({
  isPaused,
  item,
  subtitleClock,
}: {
  isPaused: boolean;
  item: LiveVoiceQueueItem | null;
  subtitleClock: LiveVoiceSubtitleClock;
}): LiveVoiceSubtitle | null {
  if (
    isPaused ||
    !item ||
    item.status !== "playing" ||
    item.subtitleCues.length === 0 ||
    subtitleClock?.utteranceId !== item.utteranceId
  ) {
    return null;
  }

  const display = subtitleDisplayForElapsedMs(
    item.subtitleCues,
    subtitleClock.elapsedMs,
  );
  if (!display) {
    return null;
  }

  return {
    ...display,
    speakerKind: item.speakerKind,
    speakerName: item.speakerName,
    utteranceId: item.utteranceId,
  };
}

export function subtitleDisplayForElapsedMs(
  cues: LiveVoiceSubtitleCue[],
  elapsedMs: number,
): LiveVoiceSubtitleDisplay | null {
  const pages = subtitlePages(cues);
  const targetMs = elapsedMs + SUBTITLE_CUE_LEAD_MS;
  let pageIndex = -1;

  for (let index = 0; index < pages.length; index += 1) {
    if (pages[index].startMs > targetMs) {
      break;
    }
    pageIndex = index;
  }

  if (pageIndex < 0) {
    return null;
  }

  const page = pages[pageIndex];
  let activeUnitIndex = -1;
  for (let index = 0; index < page.units.length; index += 1) {
    const unit = page.units[index];
    if (!isSubtitleWhitespace(unit.text) && unit.startMs <= targetMs) {
      activeUnitIndex = index;
    }
  }

  const completedText = page.units
    .slice(0, Math.max(0, activeUnitIndex))
    .map((unit) => unit.text)
    .join("");
  const activeText =
    activeUnitIndex >= 0 ? page.units[activeUnitIndex].text : "";
  const pendingText = page.units
    .slice(activeUnitIndex + 1)
    .map((unit) => unit.text)
    .join("");

  return {
    activeText,
    completedText,
    pageIndex,
    pendingText,
    text: page.units.map((unit) => unit.text).join(""),
  };
}

export function subtitleTextForElapsedMs(
  cues: LiveVoiceSubtitleCue[],
  elapsedMs: number,
) {
  return subtitleDisplayForElapsedMs(cues, elapsedMs)?.text ?? "";
}

export function removeSubtitlePunctuation(value: string) {
  return splitSubtitleGraphemes(value)
    .filter((grapheme) => !isSubtitlePunctuation(grapheme))
    .join("");
}

export function stripSubtitlePunctuation(value: string) {
  return removeSubtitlePunctuation(value).replace(/\s+/gu, " ").trim();
}

function subtitlePages(cues: LiveVoiceSubtitleCue[]) {
  const units = timedSubtitleUnits(cues);
  const semanticRanges: TimedSubtitleUnit[][] = [];
  let rangeStart = 0;

  for (let index = 0; index < units.length; index += 1) {
    if (units[index].breakAfter === "strong") {
      const range = trimSubtitleUnits(units.slice(rangeStart, index + 1));
      if (range.length > 0) {
        semanticRanges.push(range);
      }
      rangeStart = index + 1;
    }
  }

  const finalRange = trimSubtitleUnits(units.slice(rangeStart));
  if (finalRange.length > 0) {
    semanticRanges.push(finalRange);
  }

  return semanticRanges
    .flatMap(paginateSubtitleRange)
    .map<SubtitlePage>((page) => ({
      startMs: firstSpokenUnit(page)?.startMs ?? page[0].startMs,
      units: page,
    }));
}

function timedSubtitleUnits(cues: LiveVoiceSubtitleCue[]) {
  const units: TimedSubtitleUnit[] = [];
  const sortedCues = cues
    .filter((cue) => cue.text && cue.endMs > cue.startMs)
    .slice()
    .sort(
      (left, right) => left.startMs - right.startMs || left.endMs - right.endMs,
    );

  for (const cue of sortedCues) {
    const graphemes = splitSubtitleGraphemes(cue.text);
    const spokenGraphemes = graphemes.filter(
      (grapheme) =>
        !isSubtitlePunctuation(grapheme) && !isSubtitleWhitespace(grapheme),
    );
    const spokenCount = spokenGraphemes.length;
    const durationMs = cue.endMs - cue.startMs;
    let spokenIndex = 0;

    for (const grapheme of graphemes) {
      if (/^[\r\n]$/u.test(grapheme)) {
        attachSubtitleBreak(units, "strong");
        continue;
      }
      if (isSubtitlePunctuation(grapheme)) {
        attachSubtitleBreak(units, subtitleBreakStrength(grapheme));
        continue;
      }
      if (isSubtitleWhitespace(grapheme)) {
        if (units.length > 0 && !isSubtitleWhitespace(units.at(-1)?.text ?? "")) {
          const whitespaceMs =
            cue.startMs +
            (durationMs * spokenIndex) / Math.max(1, spokenCount);
          units.push({
            breakAfter: "none",
            columnWidth: 0.5,
            endMs: whitespaceMs,
            startMs: whitespaceMs,
            text: " ",
          });
        }
        continue;
      }

      const startMs =
        cue.startMs + (durationMs * spokenIndex) / Math.max(1, spokenCount);
      spokenIndex += 1;
      const endMs =
        cue.startMs + (durationMs * spokenIndex) / Math.max(1, spokenCount);
      units.push({
        breakAfter: "none",
        columnWidth: subtitleColumnWidth(grapheme),
        endMs,
        startMs,
        text: grapheme,
      });
    }
  }

  return trimSubtitleUnits(units);
}

function paginateSubtitleRange(units: TimedSubtitleUnit[]) {
  const pages: TimedSubtitleUnit[][] = [];
  let remaining = trimSubtitleUnits(units);

  while (subtitleUnitsWidth(remaining) > SUBTITLE_PAGE_MAX_COLUMNS) {
    const totalWidth = subtitleUnitsWidth(remaining);
    const hardLimitIndex = subtitleEndIndexForWidth(
      remaining,
      SUBTITLE_PAGE_MAX_COLUMNS,
    );
    let pageEndIndex = -1;

    for (let index = 0; index <= hardLimitIndex; index += 1) {
      if (remaining[index].breakAfter !== "weak") {
        continue;
      }
      const leadingWidth = subtitleUnitsWidth(remaining.slice(0, index + 1));
      const trailingWidth = totalWidth - leadingWidth;
      if (
        leadingWidth >= MIN_BALANCED_PAGE_COLUMNS &&
        trailingWidth >= MIN_BALANCED_PAGE_COLUMNS
      ) {
        pageEndIndex = index;
      }
    }

    if (pageEndIndex < 0) {
      const pageCount = Math.ceil(totalWidth / SUBTITLE_PAGE_MAX_COLUMNS);
      const balancedWidth = Math.ceil(totalWidth / pageCount);
      pageEndIndex = subtitleEndIndexForWidth(remaining, balancedWidth);
    }

    const page = trimSubtitleUnits(remaining.slice(0, pageEndIndex + 1));
    if (page.length > 0) {
      pages.push(page);
    }
    remaining = trimSubtitleUnits(remaining.slice(pageEndIndex + 1));
  }

  if (remaining.length > 0) {
    pages.push(remaining);
  }
  return pages;
}

function subtitleEndIndexForWidth(units: TimedSubtitleUnit[], targetWidth: number) {
  let width = 0;
  let endIndex = 0;
  for (let index = 0; index < units.length; index += 1) {
    const nextWidth = width + units[index].columnWidth;
    if (nextWidth > targetWidth && index > 0) {
      break;
    }
    width = nextWidth;
    endIndex = index;
  }
  return endIndex;
}

function subtitleUnitsWidth(units: TimedSubtitleUnit[]) {
  return units.reduce((total, unit) => total + unit.columnWidth, 0);
}

function trimSubtitleUnits(units: TimedSubtitleUnit[]) {
  let start = 0;
  let end = units.length;
  while (start < end && isSubtitleWhitespace(units[start].text)) {
    start += 1;
  }
  while (end > start && isSubtitleWhitespace(units[end - 1].text)) {
    end -= 1;
  }
  return units.slice(start, end);
}

function firstSpokenUnit(units: TimedSubtitleUnit[]) {
  return units.find((unit) => !isSubtitleWhitespace(unit.text));
}

function attachSubtitleBreak(
  units: TimedSubtitleUnit[],
  strength: SubtitleBreakStrength,
) {
  if (strength === "none") {
    return;
  }
  const unit = units.findLast(
    (candidate) => !isSubtitleWhitespace(candidate.text),
  );
  if (!unit || unit.breakAfter === "strong") {
    return;
  }
  unit.breakAfter = strength;
}

function subtitleBreakStrength(grapheme: string): SubtitleBreakStrength {
  if (STRONG_SUBTITLE_BREAK.test(grapheme)) {
    return "strong";
  }
  if (WEAK_SUBTITLE_BREAK.test(grapheme)) {
    return "weak";
  }
  return "none";
}

function subtitleColumnWidth(grapheme: string) {
  if (SUBTITLE_EMOJI.test(grapheme)) {
    return 2;
  }
  if (/^[\u0000-\u00ff]$/u.test(grapheme)) {
    return 0.56;
  }
  return 1;
}

function isSubtitlePunctuation(grapheme: string) {
  return SUBTITLE_PUNCTUATION.test(grapheme);
}

function isSubtitleWhitespace(grapheme: string) {
  return /^\s$/u.test(grapheme);
}

function splitSubtitleGraphemes(value: string) {
  return Array.from(SUBTITLE_SEGMENTER.segment(value), ({ segment }) => segment);
}
