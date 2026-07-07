# Mobile Live Subtitles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add mobile live theater subtitles that show only judge narration and public player speech, with distinct judge/player colors.

**Architecture:** Derive a small mobile subtitle view model from the existing `deriveLiveNarrativeState` output, then pass it into the shared `MobileLiveTheater` used by live and replay pages. Keep event interpretation in page-level data derivation and keep the theater component focused on rendering.

**Tech Stack:** React 19, TypeScript, Vite, Vitest, Testing Library, shared `@werewolf-arena/game-client` live helpers, CSS in `apps/mobile-web/src/styles/index.css`.

---

## File Structure

- Create `apps/mobile-web/src/components/mobileLiveSubtitle.ts`.
  - Responsibility: convert `LiveNarrativeState` plus `GodViewState` into `MobileLiveSubtitle | null`.
  - Exports: `PUBLIC_SPEECH_ACTIONS`, `MobileLiveSubtitle`, `deriveMobileLiveSubtitle`.
- Create `apps/mobile-web/src/components/mobileLiveSubtitle.test.ts`.
  - Responsibility: pure unit coverage for player speech, judge speech prompts, non-speech filtering, and color indexing.
- Modify `apps/mobile-web/src/pages/LivePage.tsx`.
  - Responsibility: derive `narrativeState`, derive `subtitle`, and pass it to `MobileLiveTheater`.
- Modify `apps/mobile-web/src/pages/LiveReplayPage.tsx`.
  - Responsibility: same subtitle derivation for saved live playback.
- Modify `apps/mobile-web/src/components/MobileLiveTheater.tsx`.
  - Responsibility: accept `subtitle`, pass it to `LiveCenterStage`, and render a lower-third subtitle element.
- Modify `apps/mobile-web/src/pages/LivePage.test.tsx`.
  - Responsibility: route-level coverage for live subtitle rendering and style hooks.
- Modify `apps/mobile-web/src/pages/LiveReplayPage.test.tsx`.
  - Responsibility: route-level coverage that replay uses the same subtitle behavior.
- Modify `apps/mobile-web/src/styles/index.css`.
  - Responsibility: lower-third subtitle layout and color classes.

---

## Task 1: Subtitle View Model

**Files:**

- Create: `apps/mobile-web/src/components/mobileLiveSubtitle.ts`
- Create: `apps/mobile-web/src/components/mobileLiveSubtitle.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `apps/mobile-web/src/components/mobileLiveSubtitle.test.ts`:

```ts
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/components/mobileLiveSubtitle.test.ts
```

Expected: FAIL because `./mobileLiveSubtitle` does not exist.

- [ ] **Step 3: Implement the subtitle view model**

Create `apps/mobile-web/src/components/mobileLiveSubtitle.ts`:

```ts
import type {
  deriveGodViewState,
  deriveLiveNarrativeState,
} from "@werewolf-arena/game-client";

type GodViewState = ReturnType<typeof deriveGodViewState>;
type LiveNarrativeState = ReturnType<typeof deriveLiveNarrativeState>;

export const PUBLIC_SPEECH_ACTIONS = [
  "debate",
  "sheriff_speech",
  "sheriff_pk_speech",
] as const;

export type MobileLiveSubtitle = {
  speakerName: string;
  text: string;
  tone: "judge" | "player";
  colorIndex: number;
};

const PLAYER_COLOR_COUNT = 8;

export function deriveMobileLiveSubtitle({
  godViewState,
  narrativeState,
}: {
  godViewState: Pick<GodViewState, "players">;
  narrativeState: LiveNarrativeState;
}): MobileLiveSubtitle | null {
  const cue = narrativeState.cue;

  if (cue.kind === "player-speaking") {
    const text = cue.speechText.trim();
    if (!text) {
      return null;
    }

    const speakerName =
      cue.actorName?.trim() || narrativeState.speaker?.name || "当前玩家";

    return {
      speakerName,
      text,
      tone: "player",
      colorIndex: playerColorIndex(speakerName, godViewState.players),
    };
  }

  if (
    cue.kind === "judge" ||
    (cue.kind === "player-thinking" && isPublicSpeechAction(cue.action))
  ) {
    const text = cue.judgeLine.trim();
    if (!text) {
      return null;
    }

    return {
      speakerName: "法官",
      text,
      tone: "judge",
      colorIndex: 0,
    };
  }

  return null;
}

function isPublicSpeechAction(action: string | null) {
  return PUBLIC_SPEECH_ACTIONS.includes(
    action as (typeof PUBLIC_SPEECH_ACTIONS)[number],
  );
}

function playerColorIndex(
  speakerName: string,
  players: Pick<GodViewState["players"][number], "name" | "seatNumber">[],
) {
  const player = players.find((item) => item.name === speakerName);
  if (player && Number.isFinite(player.seatNumber)) {
    return modulo(player.seatNumber - 1, PLAYER_COLOR_COUNT);
  }

  return modulo(hashSpeakerName(speakerName), PLAYER_COLOR_COUNT);
}

function hashSpeakerName(value: string) {
  return Array.from(value).reduce(
    (hash, character) => hash + character.codePointAt(0)!,
    0,
  );
}

function modulo(value: number, divisor: number) {
  return ((value % divisor) + divisor) % divisor;
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/components/mobileLiveSubtitle.test.ts
```

Expected: PASS for all tests in `mobileLiveSubtitle.test.ts`.

- [ ] **Step 5: Commit**

Run:

```bash
git add apps/mobile-web/src/components/mobileLiveSubtitle.ts apps/mobile-web/src/components/mobileLiveSubtitle.test.ts
git commit -m "feat(mobile): derive live subtitles"
```

Expected: commit succeeds.

---

## Task 2: Live Page Subtitle Data Flow

**Files:**

- Modify: `apps/mobile-web/src/pages/LivePage.test.tsx`
- Modify: `apps/mobile-web/src/pages/LivePage.tsx`

- [ ] **Step 1: Write failing route tests**

In `apps/mobile-web/src/pages/LivePage.test.tsx`, add this event near the existing live event fixtures:

```ts
const speechRequestEvent: LiveGameEvent = {
  ...gameStartedEvent,
  id: 2,
  type: "model_request_started",
  actor: "阿青",
  action: "debate",
  payload: { request_id: "req-judge-speech" },
};
```

Then add these tests inside `describe("LivePage", () => { ... })`:

```ts
  it("renders a lower-third subtitle for public player speech", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent, backlogRequestEvent, backlogSpeakingDeltaEvent],
      latestEvent: backlogSpeakingDeltaEvent,
    });

    renderLiveRoute();

    const subtitle = await screen.findByRole("status", {
      name: "直播字幕",
    });

    expect(subtitle).toHaveClass("mobile-live-subtitle");
    expect(subtitle).toHaveClass("mobile-live-subtitle-player-0");
    expect(within(subtitle).getByText("阿青")).toBeVisible();
    expect(within(subtitle).getByText("我先听后置位发言。")).toBeVisible();
  });

  it("renders a judge subtitle for public speech prompts", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent, speechRequestEvent],
      latestEvent: speechRequestEvent,
    });

    renderLiveRoute();

    const subtitle = await screen.findByRole("status", {
      name: "直播字幕",
    });

    expect(subtitle).toHaveClass("mobile-live-subtitle-judge");
    expect(within(subtitle).getByText("法官")).toBeVisible();
    expect(within(subtitle).getByText("请 阿青 发言。")).toBeVisible();
  });

  it("does not render subtitles for non-speech live events", async () => {
    gameClientMocks.useGameRunEvents.mockReturnValue({
      connectionState: "open",
      events: [gameStartedEvent],
      latestEvent: gameStartedEvent,
    });

    renderLiveRoute();

    await screen.findByRole("region", { name: "当前舞台" });

    expect(
      screen.queryByRole("status", { name: "直播字幕" }),
    ).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/LivePage.test.tsx
```

Expected: FAIL because the subtitle status region does not exist.

- [ ] **Step 3: Wire subtitle derivation into the live page**

Modify the import from `@werewolf-arena/game-client` in `apps/mobile-web/src/pages/LivePage.tsx` to include `deriveLiveNarrativeState`:

```ts
import {
  buildLivePhaseSegments,
  deriveGodViewState,
  deriveLiveNarrativeState,
  deriveLiveNavStatus,
  deriveLiveSpectatorState,
  getGameRun,
  resumeGameRun,
  useGameRunEvents,
  useLiveDirector,
  type LiveGameEvent,
} from "@werewolf-arena/game-client";
```

Add this import below the existing component import:

```ts
import { deriveMobileLiveSubtitle } from "../components/mobileLiveSubtitle";
```

After `godViewState` is derived, add:

```ts
  const narrativeState = useMemo(
    () =>
      deriveLiveNarrativeState({
        cue: director.currentCue,
        events: stageEvents,
        godViewState,
        spectatorState,
      }),
    [director.currentCue, godViewState, spectatorState, stageEvents],
  );
  const subtitle = useMemo(
    () =>
      deriveMobileLiveSubtitle({
        godViewState,
        narrativeState,
      }),
    [godViewState, narrativeState],
  );
```

In the `MobileLiveTheater` JSX props, add:

```tsx
          subtitle={subtitle}
```

- [ ] **Step 4: Add the theater prop and minimal render**

Modify `apps/mobile-web/src/components/MobileLiveTheater.tsx`.

Add the subtitle type import:

```ts
import type { MobileLiveSubtitle } from "./mobileLiveSubtitle";
```

Add the prop to `MobileLiveTheaterProps`:

```ts
  subtitle: MobileLiveSubtitle | null;
```

Destructure it in `MobileLiveTheater`:

```ts
  subtitle,
```

Pass it to `LiveCenterStage`:

```tsx
        <LiveCenterStage
          currentEvent={currentEvent}
          currentPlayer={currentPlayer}
          godViewState={godViewState}
          subtitle={subtitle}
        />
```

Add the prop to `LiveCenterStageProps`:

```ts
  subtitle: MobileLiveSubtitle | null;
```

Destructure it in `LiveCenterStage`:

```ts
  subtitle,
```

Render it after the existing event label paragraph:

```tsx
      {subtitle ? <LiveSubtitle subtitle={subtitle} /> : null}
```

Add the component before `LiveTheaterControls`:

```tsx
type LiveSubtitleProps = {
  subtitle: MobileLiveSubtitle;
};

function LiveSubtitle({ subtitle }: LiveSubtitleProps) {
  const className = [
    "mobile-live-subtitle",
    subtitle.tone === "judge"
      ? "mobile-live-subtitle-judge"
      : `mobile-live-subtitle-player-${subtitle.colorIndex}`,
  ].join(" ");

  return (
    <div aria-label="直播字幕" className={className} role="status">
      <strong>{subtitle.speakerName}</strong>
      <span>{subtitle.text}</span>
    </div>
  );
}
```

- [ ] **Step 5: Run tests to verify they pass or expose missing styles only**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/LivePage.test.tsx
```

Expected: The new route subtitle behavior tests pass. Existing style tests may fail until Task 4 adds CSS.

- [ ] **Step 6: Commit if route behavior is passing**

Run only if the new subtitle behavior tests pass and any failures are limited to missing CSS assertions planned in Task 4:

```bash
git add apps/mobile-web/src/pages/LivePage.tsx apps/mobile-web/src/pages/LivePage.test.tsx apps/mobile-web/src/components/MobileLiveTheater.tsx
git commit -m "feat(mobile): show live speech subtitles"
```

Expected: commit succeeds.

---

## Task 3: Replay Page Subtitle Data Flow

**Files:**

- Modify: `apps/mobile-web/src/pages/LiveReplayPage.test.tsx`
- Modify: `apps/mobile-web/src/pages/LiveReplayPage.tsx`

- [ ] **Step 1: Write failing replay tests**

Add this test to `apps/mobile-web/src/pages/LiveReplayPage.test.tsx`:

```ts
  it("renders replay subtitles for public player speech", async () => {
    renderLiveReplayRoute();

    const subtitle = await screen.findByRole("status", {
      name: "直播字幕",
    });

    expect(subtitle).toHaveClass("mobile-live-subtitle");
    expect(subtitle).toHaveClass("mobile-live-subtitle-player-0");
    expect(within(subtitle).getByText("阿青")).toBeVisible();
    expect(within(subtitle).getByText("我先听后置位发言。")).toBeVisible();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/LiveReplayPage.test.tsx
```

Expected: FAIL because `LiveReplayPage` does not pass `subtitle` to `MobileLiveTheater`, and TypeScript or render output is missing the subtitle.

- [ ] **Step 3: Wire subtitle derivation into replay**

Modify the import from `@werewolf-arena/game-client` in `apps/mobile-web/src/pages/LiveReplayPage.tsx` to include `deriveLiveNarrativeState`:

```ts
import {
  buildLivePhaseSegments,
  deriveGodViewState,
  deriveLiveNarrativeState,
  deriveLiveSpectatorState,
  getGamePlayback,
  resumeGameRun,
  useLiveDirector,
  type GamePlayback,
  type GameRunStatus,
  type LiveGameEvent,
} from "@werewolf-arena/game-client";
```

Add this import below the theater import:

```ts
import { deriveMobileLiveSubtitle } from "../components/mobileLiveSubtitle";
```

After `godViewState` is derived, add:

```ts
  const narrativeState = useMemo(
    () =>
      deriveLiveNarrativeState({
        cue: director.currentCue,
        events: stageEvents,
        godViewState,
        spectatorState,
      }),
    [director.currentCue, godViewState, spectatorState, stageEvents],
  );
  const subtitle = useMemo(
    () =>
      deriveMobileLiveSubtitle({
        godViewState,
        narrativeState,
      }),
    [godViewState, narrativeState],
  );
```

In the `MobileLiveTheater` JSX props, add:

```tsx
          subtitle={subtitle}
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/LiveReplayPage.test.tsx
```

Expected: PASS for `LiveReplayPage.test.tsx`.

- [ ] **Step 5: Commit**

Run:

```bash
git add apps/mobile-web/src/pages/LiveReplayPage.tsx apps/mobile-web/src/pages/LiveReplayPage.test.tsx
git commit -m "feat(mobile): show replay speech subtitles"
```

Expected: commit succeeds.

---

## Task 4: Subtitle Styling And Style Tests

**Files:**

- Modify: `apps/mobile-web/src/pages/LivePage.test.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Write failing style tests**

Add this test to `apps/mobile-web/src/pages/LivePage.test.tsx`:

```ts
  it("styles mobile live subtitles as a lower-third speech HUD", () => {
    const styles = readFileSync("src/styles/index.css", "utf8");
    const subtitleRule =
      styles.match(/(?:^|\n)\.mobile-live-subtitle\s*{[^}]+}/)?.[0] ?? "";
    const judgeRule =
      styles.match(/(?:^|\n)\.mobile-live-subtitle-judge\s*{[^}]+}/)?.[0] ?? "";
    const playerZeroRule =
      styles.match(/(?:^|\n)\.mobile-live-subtitle-player-0\s*{[^}]+}/)?.[0] ?? "";
    const shortScreenRule =
      styles.match(
        /@media \(max-height: 860px\) {[\s\S]*?\.mobile-live-subtitle\s*{[^}]+}/,
      )?.[0] ?? "";

    expect(subtitleRule).toContain("max-width: 100%");
    expect(subtitleRule).toContain("grid-template-columns: auto minmax(0, 1fr)");
    expect(subtitleRule).toContain("-webkit-line-clamp: 2");
    expect(subtitleRule).toContain("word-break: break-word");
    expect(judgeRule).toContain("--mobile-live-subtitle-accent: #f4c76d");
    expect(playerZeroRule).toContain("--mobile-live-subtitle-accent: #8ddfd0");
    expect(styles).toContain(".mobile-live-subtitle-player-7");
    expect(shortScreenRule).toContain("font-size: 11px");
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/LivePage.test.tsx
```

Expected: FAIL because subtitle CSS classes are not defined.

- [ ] **Step 3: Add subtitle CSS**

In `apps/mobile-web/src/styles/index.css`, add these rules after `.mobile-live-center-stage p { ... }` and before `.mobile-live-center-stage small { ... }`:

```css
.mobile-live-subtitle {
  --mobile-live-subtitle-accent: #f4c76d;
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: start;
  gap: 7px;
  max-width: 100%;
  box-sizing: border-box;
  border: 1px solid color-mix(in srgb, var(--mobile-live-subtitle-accent) 62%, transparent);
  border-radius: 0;
  padding: 7px 9px;
  background:
    linear-gradient(180deg, rgb(255 239 192 / 7%), rgb(0 0 0 / 18%)),
    rgb(5 8 12 / 72%);
  color: #fff2bf;
  box-shadow:
    inset 0 1px 0 rgb(255 245 202 / 10%),
    0 6px 16px rgb(0 0 0 / 30%),
    0 0 18px color-mix(in srgb, var(--mobile-live-subtitle-accent) 22%, transparent);
  text-align: left;
}

.mobile-live-subtitle strong {
  color: var(--mobile-live-subtitle-accent);
  font-size: 12px;
  font-weight: 900;
  line-height: 1.4;
  white-space: nowrap;
  text-shadow: 0 2px 5px rgb(0 0 0 / 72%);
}

.mobile-live-subtitle span {
  display: -webkit-box;
  min-width: 0;
  overflow: hidden;
  color: #fff4cf;
  font-size: 12px;
  font-weight: 800;
  line-height: 1.4;
  text-shadow: 0 2px 5px rgb(0 0 0 / 72%);
  white-space: normal;
  word-break: break-word;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.mobile-live-subtitle-judge {
  --mobile-live-subtitle-accent: #f4c76d;
}

.mobile-live-subtitle-player-0 {
  --mobile-live-subtitle-accent: #8ddfd0;
}

.mobile-live-subtitle-player-1 {
  --mobile-live-subtitle-accent: #82c9ff;
}

.mobile-live-subtitle-player-2 {
  --mobile-live-subtitle-accent: #c9a7ff;
}

.mobile-live-subtitle-player-3 {
  --mobile-live-subtitle-accent: #ff9ab1;
}

.mobile-live-subtitle-player-4 {
  --mobile-live-subtitle-accent: #f4c76d;
}

.mobile-live-subtitle-player-5 {
  --mobile-live-subtitle-accent: #86e6a8;
}

.mobile-live-subtitle-player-6 {
  --mobile-live-subtitle-accent: #8fb4ff;
}

.mobile-live-subtitle-player-7 {
  --mobile-live-subtitle-accent: #f2a1dc;
}
```

Inside the existing `@media (max-height: 860px) { ... }` block, add this rule after `.mobile-live-center-stage { ... }`:

```css
  .mobile-live-subtitle {
    gap: 5px;
    padding: 5px 7px;
  }

  .mobile-live-subtitle strong,
  .mobile-live-subtitle span {
    font-size: 11px;
  }
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/pages/LivePage.test.tsx
```

Expected: PASS for `LivePage.test.tsx`.

- [ ] **Step 5: Commit**

Run:

```bash
git add apps/mobile-web/src/styles/index.css apps/mobile-web/src/pages/LivePage.test.tsx
git commit -m "style(mobile): add live subtitle lower third"
```

Expected: commit succeeds.

---

## Task 5: Full Verification

**Files:**

- No source edits expected.

- [ ] **Step 1: Run focused mobile subtitle tests**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run src/components/mobileLiveSubtitle.test.ts src/pages/LivePage.test.tsx src/pages/LiveReplayPage.test.tsx
```

Expected: PASS.

- [ ] **Step 2: Run all mobile tests**

Run:

```bash
pnpm test:mobile
```

Expected: PASS.

- [ ] **Step 3: Run mobile lint**

Run:

```bash
pnpm lint:mobile
```

Expected: PASS with no lint errors.

- [ ] **Step 4: Run mobile build**

Run:

```bash
pnpm build:mobile
```

Expected: PASS and Vite build output completes.

- [ ] **Step 5: Inspect git status**

Run:

```bash
git status --short
```

Expected: no uncommitted files from this subtitle implementation. If unrelated user files appear, leave them untouched and mention them in the final response.

---

## Self-Review

- Spec coverage: Tasks cover the mobile-only scope, reuse of `deriveLiveNarrativeState`, lower-third placement, judge/player filtering, deterministic player colors, live and replay data flow, CSS classes, and verification.
- Placeholder scan: The plan contains no placeholder markers. Each code-writing step includes the concrete code or insertion.
- Type consistency: `MobileLiveSubtitle`, `deriveMobileLiveSubtitle`, `subtitle`, and CSS class names are consistent across tasks.
