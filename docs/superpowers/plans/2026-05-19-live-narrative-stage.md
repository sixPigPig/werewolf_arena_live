# 狼人杀直播叙事舞台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a frontend narrative layer that turns existing live/replay events into a狼人杀-style “法官旁白 + 玩家发言表演” stage.

**Architecture:** Add a pure `liveNarrative.ts` derivation module beside existing game feature derivations, then render its output through a focused `LiveNarrativeCenter` component inside `LiveDirectorStage`. `DirectorCue` remains responsible for playback timing, `GodViewState` remains responsible for game facts, and the new narrative state only controls how the current moment is phrased for spectators.

**Tech Stack:** React 19, TypeScript, Vitest, Testing Library, existing Vite app, existing UI helpers and Tailwind utility classes.

---

## File Structure

- Create: `apps/web/src/features/games/liveNarrative.ts`
  - Pure derivation from `events`, `director.currentCue`, `godViewState`, and `spectatorState` to `LiveNarrativeState`.
  - Owns deterministic judge/player wording, public information guardrails, and fallback behavior.

- Create: `apps/web/src/features/games/liveNarrative.test.ts`
  - Pure unit tests covering phase narration, player thinking, streaming speech, vote/death announcements, terminal announcements, and unknown-event fallback.

- Create: `apps/web/src/features/games/components/LiveNarrativeCenter.tsx`
  - Focused render component for the center of `LiveDirectorStage`.
  - Owns the judge subtitle, performer line, player identity chips, speech/detail panel, and tone styling.

- Create: `apps/web/src/features/games/components/LiveNarrativeCenter.test.tsx`
  - Component tests for narrative rendering and empty speech fallback.

- Modify: `apps/web/src/features/games/components/LiveStageExperience.tsx`
  - Calls `deriveLiveNarrativeState()` and passes `narrativeState` to `LiveDirectorStage`.

- Modify: `apps/web/src/features/games/components/LiveDirectorStage.tsx`
  - Adds a `narrativeState` prop.
  - Replaces the central title/body block with `LiveNarrativeCenter` while preserving the surrounding stage, player rails, debug highlights, queue badges, and auto-follow control.

- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`
  - Adds user-visible assertions for judge narration and player speech on live SSE.

- Modify: `apps/web/src/pages/GamePlaybackPage.test.tsx`
  - Adds user-visible assertions that playback reuses the same narrative stage.

## Task 1: Pure Narrative Derivation

**Files:**
- Create: `apps/web/src/features/games/liveNarrative.test.ts`
- Create: `apps/web/src/features/games/liveNarrative.ts`

- [ ] **Step 1: Write the failing pure-function tests**

Create `apps/web/src/features/games/liveNarrative.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { buildDirectorCues, toDirectorCue } from "./liveDirector";
import { deriveGodViewState } from "./liveGodView";
import { deriveLiveNarrativeState } from "./liveNarrative";
import { deriveLiveSpectatorState } from "./liveSpectator";
import type { LiveGameEvent } from "./types";

function event(partial: Partial<LiveGameEvent>): LiveGameEvent {
  return {
    id: partial.id ?? 1,
    type: partial.type ?? "game_started",
    run_id: "run_1234abcd",
    session_id: "game_1200abcd",
    created_at: partial.created_at ?? "2026-05-19T00:00:00Z",
    round: partial.round ?? null,
    phase: partial.phase ?? null,
    actor: partial.actor ?? null,
    action: partial.action ?? null,
    payload: partial.payload ?? {},
  };
}

function narrativeFor(
  events: LiveGameEvent[],
  cue = toDirectorCue(events.at(-1) ?? event({})),
) {
  const spectatorState = deriveLiveSpectatorState(events);
  const godViewState = deriveGodViewState(
    events,
    spectatorState,
    "经典 8 人局",
    { sheriffEnabled: false },
  );

  return deriveLiveNarrativeState({
    cue,
    events,
    godViewState,
    spectatorState,
  });
}

describe("deriveLiveNarrativeState", () => {
  it("narrates core phase transitions like a judge", () => {
    expect(
      narrativeFor([
        event({
          id: 1,
          type: "phase_started",
          round: 1,
          phase: "night",
          payload: { active_players: ["Sam", "Isaac"] },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "judge",
      tone: "night",
      judgeLine: "天黑请闭眼。",
      detailLine: "夜间行动开始，存活玩家请依次行动。",
    });

    expect(
      narrativeFor([
        event({
          id: 2,
          type: "state_updated",
          round: 1,
          phase: "night",
          payload: {
            attacked: "Isaac",
            protected: "Isaac",
            eliminated: null,
            active_players: ["Sam", "Isaac"],
          },
        }),
        event({
          id: 3,
          type: "phase_started",
          round: 1,
          phase: "day",
          payload: { active_players: ["Sam", "Isaac"] },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "judge",
      tone: "day",
      judgeLine: "天亮了，昨夜平安无事。",
    });

    expect(
      narrativeFor([
        event({
          id: 4,
          type: "phase_started",
          round: 1,
          phase: "vote",
          payload: { active_players: ["Sam", "Isaac"] },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "vote",
      tone: "vote",
      judgeLine: "发言结束，进入放逐投票。",
    });
  });

  it("turns action requests into player performance states", () => {
    const state = narrativeFor([
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [
            { name: "Sam", role: "村民", model: "deepseek-chat" },
            { name: "Isaac", role: "狼人", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "action_requested",
        round: 1,
        phase: "day",
        actor: "Sam",
        action: "debate",
        payload: { options: [] },
      }),
    ]);

    expect(state.speaker).toMatchObject({
      name: "Sam",
      seatNumber: 1,
      role: "村民",
    });
    expect(state.cue).toMatchObject({
      kind: "player-thinking",
      actorName: "Sam",
      action: "debate",
      judgeLine: "请 Sam 发言。",
      performerLine: "Sam 正在整理公开发言。",
      detailLine: "下一位：Isaac",
    });
  });

  it("uses coalesced streaming cue text as live player speech", () => {
    const events = [
      event({
        id: 1,
        type: "game_started",
        payload: {
          players: [
            { name: "张三", role: "狼人", model: "deepseek-chat" },
            { name: "李四", role: "村民", model: "deepseek-chat" },
          ],
        },
      }),
      event({
        id: 2,
        type: "model_request_started",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_123",
          model: "deepseek-chat",
          message: "玩家正在组织公开发言...",
          stream_field: "say",
          is_public: true,
        },
      }),
      event({
        id: 3,
        type: "model_response_delta",
        round: 1,
        phase: "day",
        actor: "张三",
        action: "debate",
        payload: {
          request_id: "req_123",
          visible_text: "我不是狼",
          is_public: true,
        },
      }),
    ];
    const cues = buildDirectorCues(events);

    expect(narrativeFor(events, cues[0]).cue).toMatchObject({
      kind: "player-speaking",
      tone: "day",
      judgeLine: "请听 张三 的发言。",
      performerLine: "张三 正在发言。",
      speechText: "我不是狼",
    });
  });

  it("announces vote, exile, night death, and terminal results", () => {
    expect(
      narrativeFor([
        event({
          id: 1,
          type: "state_updated",
          round: 1,
          phase: "vote",
          payload: {
            votes: { Sam: "Isaac", Isaac: "Sam", Leah: "Isaac" },
            vote_weights: {},
          },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "vote",
      tone: "vote",
      judgeLine: "投票结果公布。",
      detailLine: "当前最高票：Isaac，2 票。",
    });

    expect(
      narrativeFor([
        event({
          id: 2,
          type: "state_updated",
          round: 1,
          phase: "vote",
          payload: {
            exiled: "Isaac",
            day_deaths: [{ player: "Isaac", cause: "vote_exile" }],
            active_players: ["Sam"],
          },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "death",
      tone: "danger",
      judgeLine: "Isaac 被放逐出局。",
    });

    expect(
      narrativeFor([
        event({
          id: 3,
          type: "state_updated",
          round: 2,
          phase: "night",
          payload: {
            eliminated: "Sam",
            night_deaths: [{ player: "Sam", cause: "werewolf_attack" }],
            active_players: ["Isaac"],
          },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "death",
      tone: "danger",
      judgeLine: "天亮了，昨夜 Sam 出局。",
    });

    expect(
      narrativeFor([
        event({
          id: 4,
          type: "game_completed",
          payload: { winner: "狼人阵营" },
        }),
      ]).cue,
    ).toMatchObject({
      kind: "terminal",
      tone: "terminal",
      judgeLine: "对局结束，狼人阵营获胜。",
    });
  });

  it("falls back to the director cue for unknown events", () => {
    const state = narrativeFor([
      event({
        id: 5,
        type: "custom_diagnostic",
        payload: { note: "debug value" },
      }),
    ]);

    expect(state.cue).toMatchObject({
      kind: "fallback",
      judgeLine: "custom_diagnostic",
    });
    expect(state.cue.detailLine).toContain("debug value");
  });
});
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/liveNarrative.test.ts
```

Expected: FAIL with an import error for `./liveNarrative`.

- [ ] **Step 3: Implement `liveNarrative.ts`**

Create `apps/web/src/features/games/liveNarrative.ts`:

```ts
import type { DirectorCue } from "./liveDirector";
import type { GodViewPlayer, GodViewState } from "./liveGodView";
import type { LiveSpectatorState } from "./liveSpectator";
import type { LiveGameEvent } from "./types";

export type NarrativeCueKind =
  | "judge"
  | "player-thinking"
  | "player-speaking"
  | "player-action"
  | "vote"
  | "death"
  | "terminal"
  | "fallback";

export type NarrativeCueTone =
  | "neutral"
  | "night"
  | "day"
  | "danger"
  | "safe"
  | "vote"
  | "terminal";

export type NarrativeCue = {
  eventId: number | null;
  kind: NarrativeCueKind;
  tone: NarrativeCueTone;
  judgeLine: string;
  performerLine: string;
  detailLine: string;
  actorName: string | null;
  action: string | null;
  speechText: string;
};

export type NarrativeSpeaker = {
  name: string;
  seatNumber: number | null;
  role: string;
  camp: string;
  appearanceId: string;
  avatarImageUrl: string;
};

export type LiveNarrativeState = {
  cue: NarrativeCue;
  speaker: NarrativeSpeaker | null;
  nextSpeakerName: string | null;
  judgeLine: string;
  performerLine: string;
  detailLine: string;
};

type DeriveLiveNarrativeStateArgs = {
  cue: DirectorCue | null;
  events: LiveGameEvent[];
  godViewState: GodViewState;
  spectatorState: LiveSpectatorState;
};

export function deriveLiveNarrativeState({
  cue,
  events,
  godViewState,
  spectatorState,
}: DeriveLiveNarrativeStateArgs): LiveNarrativeState {
  const event = cue
    ? events.find((item) => item.id === cue.eventId) ?? null
    : null;
  const payload = event ? payloadForEvent(event) : {};
  const actorName =
    cue?.actor ??
    event?.actor ??
    godViewState.speakerFlow.current?.name ??
    spectatorState.activePlayerName ??
    null;
  const nextSpeakerName = godViewState.speakerFlow.next?.name ?? null;
  const speaker = speakerFor(actorName, godViewState);
  const narrativeCue = cueForEvent({
    cue,
    event,
    payload,
    actorName,
    nextSpeakerName,
    godViewState,
  });

  return {
    cue: narrativeCue,
    speaker,
    nextSpeakerName,
    judgeLine: narrativeCue.judgeLine,
    performerLine: narrativeCue.performerLine,
    detailLine: narrativeCue.detailLine,
  };
}

function cueForEvent({
  cue,
  event,
  payload,
  actorName,
  nextSpeakerName,
  godViewState,
}: {
  cue: DirectorCue | null;
  event: LiveGameEvent | null;
  payload: Record<string, unknown>;
  actorName: string | null;
  nextSpeakerName: string | null;
  godViewState: GodViewState;
}): NarrativeCue {
  if (!cue) {
    return makeCue({
      eventId: null,
      kind: "fallback",
      tone: "neutral",
      judgeLine: "等待导播事件",
      performerLine: "等待玩家行动。",
      detailLine: "实时事件到达后，法官旁白会在这里展开。",
      actorName,
      action: null,
      speechText: "",
    });
  }

  if (isPublicSpeechAction(cue.action) && cue.importance === "key") {
    const speechText = speechTextFromCue(cue.body, cue.actor);
    if (speechText) {
      return makeCue({
        eventId: cue.eventId,
        kind: "player-speaking",
        tone: "day",
        judgeLine: `请听 ${cue.actor ?? actorName ?? "当前玩家"} 的发言。`,
        performerLine: `${cue.actor ?? actorName ?? "当前玩家"} 正在发言。`,
        detailLine: nextLine(nextSpeakerName),
        actorName: cue.actor ?? actorName,
        action: cue.action,
        speechText,
      });
    }
  }

  if (!event) {
    return fallbackCue(cue, actorName);
  }

  if (event.type === "phase_started") {
    return phaseCue(cue, event.phase, godViewState, actorName);
  }

  if (event.type === "action_requested") {
    return actionRequestedCue(cue, actorName, nextSpeakerName);
  }

  if (
    event.type === "model_request_started" ||
    event.type === "model_thinking_tick"
  ) {
    return modelWaitingCue(cue, payload, actorName, nextSpeakerName);
  }

  if (event.type === "action_parsed") {
    return parsedActionCue(cue, payload, actorName, nextSpeakerName);
  }

  if (event.type === "state_updated") {
    return stateUpdatedCue(cue, payload, actorName, nextSpeakerName, godViewState);
  }

  if (event.type === "game_completed") {
    const winner = stringField(payload, "winner") || "胜利阵营";
    return makeCue({
      eventId: cue.eventId,
      kind: "terminal",
      tone: "terminal",
      judgeLine: `对局结束，${winner}获胜。`,
      performerLine: "胜负已经揭晓。",
      detailLine: `胜利阵营：${winner}`,
      actorName: null,
      action: cue.action,
      speechText: "",
    });
  }

  if (event.type === "game_failed") {
    return makeCue({
      eventId: cue.eventId,
      kind: "terminal",
      tone: "danger",
      judgeLine: "对局异常中断。",
      performerLine: "本局无法继续播放。",
      detailLine: stringField(payload, "error") || cue.body,
      actorName: null,
      action: cue.action,
      speechText: "",
    });
  }

  return fallbackCue(cue, actorName);
}

function phaseCue(
  cue: DirectorCue,
  phase: string | null,
  godViewState: GodViewState,
  actorName: string | null,
): NarrativeCue {
  if (phase === "night") {
    return makeCue({
      eventId: cue.eventId,
      kind: "judge",
      tone: "night",
      judgeLine: "天黑请闭眼。",
      performerLine: "夜间角色开始行动。",
      detailLine: "夜间行动开始，存活玩家请依次行动。",
      actorName,
      action: cue.action,
      speechText: "",
    });
  }

  if (phase === "day") {
    return makeCue({
      eventId: cue.eventId,
      kind: "judge",
      tone: "day",
      judgeLine: dayJudgeLine(godViewState),
      performerLine: "进入白天发言。",
      detailLine:
        godViewState.speakerFlow.current?.name
          ? `当前发言：${godViewState.speakerFlow.current.name}`
          : "等待首位玩家发言。",
      actorName,
      action: cue.action,
      speechText: "",
    });
  }

  if (phase === "vote") {
    return makeCue({
      eventId: cue.eventId,
      kind: "vote",
      tone: "vote",
      judgeLine: "发言结束，进入放逐投票。",
      performerLine: "所有拥有投票权的玩家开始投票。",
      detailLine: "投票结果会在票型公布后揭晓。",
      actorName,
      action: cue.action,
      speechText: "",
    });
  }

  if (phase === "summary") {
    return makeCue({
      eventId: cue.eventId,
      kind: "judge",
      tone: "neutral",
      judgeLine: "本轮进入总结，玩家整理自己的判断。",
      performerLine: "总结阶段进行中。",
      detailLine: "玩家会记录本轮观察，供后续回合参考。",
      actorName,
      action: cue.action,
      speechText: "",
    });
  }

  return fallbackCue(cue, actorName);
}

function actionRequestedCue(
  cue: DirectorCue,
  actorName: string | null,
  nextSpeakerName: string | null,
): NarrativeCue {
  const actor = actorName ?? "当前玩家";
  const action = cue.action;

  if (isPublicSpeechAction(action)) {
    return makeCue({
      eventId: cue.eventId,
      kind: "player-thinking",
      tone: "day",
      judgeLine: `请 ${actor} 发言。`,
      performerLine: `${actor} 正在整理公开发言。`,
      detailLine: nextLine(nextSpeakerName),
      actorName,
      action,
      speechText: "",
    });
  }

  if (isVoteAction(action)) {
    return makeCue({
      eventId: cue.eventId,
      kind: "player-thinking",
      tone: "vote",
      judgeLine: "请玩家投票。",
      performerLine: `${actor} 正在权衡投票。`,
      detailLine: "投票目标将在公开结果中公布。",
      actorName,
      action,
      speechText: "",
    });
  }

  return makeCue({
    eventId: cue.eventId,
    kind: "player-action",
    tone: cue.phase === "night" ? "night" : "neutral",
    judgeLine: cue.phase === "night" ? "夜间行动进行中。" : "玩家行动进行中。",
    performerLine: `${actor} 正在行动。`,
    detailLine: cue.body || "等待模型返回行动结果。",
    actorName,
    action,
    speechText: "",
  });
}

function modelWaitingCue(
  cue: DirectorCue,
  payload: Record<string, unknown>,
  actorName: string | null,
  nextSpeakerName: string | null,
): NarrativeCue {
  const actor = actorName ?? "当前玩家";
  const message = stringField(payload, "message") || cue.body;

  if (isPublicSpeechAction(cue.action)) {
    return makeCue({
      eventId: cue.eventId,
      kind: "player-thinking",
      tone: "day",
      judgeLine: `请听 ${actor} 的发言。`,
      performerLine: `${actor} 正在组织发言。`,
      detailLine: message || nextLine(nextSpeakerName),
      actorName,
      action: cue.action,
      speechText: "",
    });
  }

  return makeCue({
    eventId: cue.eventId,
    kind: "player-action",
    tone: cue.phase === "night" ? "night" : "neutral",
    judgeLine: cue.phase === "night" ? "夜间行动进行中。" : "玩家正在思考。",
    performerLine: `${actor} 正在等待模型返回。`,
    detailLine: message,
    actorName,
    action: cue.action,
    speechText: "",
  });
}

function parsedActionCue(
  cue: DirectorCue,
  payload: Record<string, unknown>,
  actorName: string | null,
  nextSpeakerName: string | null,
): NarrativeCue {
  const visibleText = visibleSpeechText(payload);
  if (visibleText && isPublicSpeechAction(cue.action)) {
    const actor = actorName ?? "当前玩家";
    return makeCue({
      eventId: cue.eventId,
      kind: "player-speaking",
      tone: "day",
      judgeLine: `请听 ${actor} 的发言。`,
      performerLine: `${actor} 完成发言。`,
      detailLine: nextLine(nextSpeakerName),
      actorName,
      action: cue.action,
      speechText: visibleText,
    });
  }

  return makeCue({
    eventId: cue.eventId,
    kind: isVoteAction(cue.action) ? "vote" : "player-action",
    tone: isVoteAction(cue.action) ? "vote" : cue.phase === "night" ? "night" : "neutral",
    judgeLine: isVoteAction(cue.action) ? "投票选择已记录。" : "玩家行动已解析。",
    performerLine: actorName ? `${actorName} 已完成行动。` : "行动已完成。",
    detailLine: cue.body,
    actorName,
    action: cue.action,
    speechText: "",
  });
}

function stateUpdatedCue(
  cue: DirectorCue,
  payload: Record<string, unknown>,
  actorName: string | null,
  nextSpeakerName: string | null,
  godViewState: GodViewState,
): NarrativeCue {
  const debateEntry = payload.debate_entry;
  if (isRecord(debateEntry) && typeof debateEntry.speaker === "string") {
    const message =
      typeof debateEntry.message === "string" ? debateEntry.message : "";
    return makeCue({
      eventId: cue.eventId,
      kind: "player-speaking",
      tone: "day",
      judgeLine: `请听 ${debateEntry.speaker} 的发言。`,
      performerLine: `${debateEntry.speaker} 完成发言。`,
      detailLine: nextLine(nextSpeakerName),
      actorName: debateEntry.speaker,
      action: cue.action,
      speechText: message,
    });
  }

  const exiled = stringField(payload, "exiled");
  if (exiled) {
    return makeCue({
      eventId: cue.eventId,
      kind: "death",
      tone: "danger",
      judgeLine: `${exiled} 被放逐出局。`,
      performerLine: "放逐结果已经生效。",
      detailLine: activePlayersLine(payload),
      actorName: exiled,
      action: cue.action,
      speechText: "",
    });
  }

  const deathNames = deathNamesFromPayload(payload);
  if (deathNames.length > 0) {
    return makeCue({
      eventId: cue.eventId,
      kind: "death",
      tone: "danger",
      judgeLine: `天亮了，昨夜 ${deathNames.join("、")} 出局。`,
      performerLine: "夜间结算公布。",
      detailLine: activePlayersLine(payload),
      actorName: deathNames[0],
      action: cue.action,
      speechText: "",
    });
  }

  if (isPeacefulNightPayload(payload)) {
    return makeCue({
      eventId: cue.eventId,
      kind: "judge",
      tone: "safe",
      judgeLine: "天亮了，昨夜平安无事。",
      performerLine: godViewState.nightResolution.detail,
      detailLine: activePlayersLine(payload),
      actorName,
      action: cue.action,
      speechText: "",
    });
  }

  if (isRecord(payload.votes)) {
    const topTarget = godViewState.vote.topTarget;
    const topTally = godViewState.vote.tallies.find(
      (item) => item.target === topTarget,
    );
    return makeCue({
      eventId: cue.eventId,
      kind: "vote",
      tone: "vote",
      judgeLine: "投票结果公布。",
      performerLine: "票型已经更新。",
      detailLine:
        topTally && topTarget
          ? `当前最高票：${topTarget}，${topTally.count} 票。`
          : "本轮暂未形成有效票型。",
      actorName,
      action: cue.action,
      speechText: "",
    });
  }

  const skillLine = skillJudgeLine(payload);
  if (skillLine) {
    return makeCue({
      eventId: cue.eventId,
      kind: "player-action",
      tone: "danger",
      judgeLine: skillLine,
      performerLine: "技能效果已经公开。",
      detailLine: activePlayersLine(payload),
      actorName,
      action: cue.action,
      speechText: "",
    });
  }

  return fallbackCue(cue, actorName);
}

function fallbackCue(cue: DirectorCue, actorName: string | null): NarrativeCue {
  return makeCue({
    eventId: cue.eventId,
    kind: "fallback",
    tone: toneFromDirectorCue(cue),
    judgeLine: cue.title,
    performerLine: actorName ? `${actorName} 的事件更新。` : "对局事件更新。",
    detailLine: cue.body,
    actorName,
    action: cue.action,
    speechText: "",
  });
}

function makeCue(cue: NarrativeCue): NarrativeCue {
  return cue;
}

function speakerFor(
  actorName: string | null,
  godViewState: GodViewState,
): NarrativeSpeaker | null {
  if (!actorName) {
    return null;
  }
  const player =
    godViewState.players.find((item) => item.name === actorName) ??
    godViewState.speakerFlow.current;
  if (!player) {
    return null;
  }
  return playerToSpeaker(player);
}

function playerToSpeaker(player: GodViewPlayer): NarrativeSpeaker {
  return {
    name: player.name,
    seatNumber: player.seatNumber,
    role: player.role,
    camp: player.camp,
    appearanceId: player.appearanceId,
    avatarImageUrl: player.avatarImageUrl,
  };
}

function dayJudgeLine(godViewState: GodViewState): string {
  if (godViewState.nightResolution.label === "平安夜") {
    return "天亮了，昨夜平安无事。";
  }
  const deathNames = godViewState.deaths.map((death) => death.player);
  if (deathNames.length > 0) {
    return `天亮了，昨夜 ${deathNames.join("、")} 出局。`;
  }
  return "天亮了，进入白天发言。";
}

function visibleSpeechText(payload: Record<string, unknown>): string {
  const visibleResult = payload.visible_result;
  if (isRecord(visibleResult)) {
    return stringField(visibleResult, "say") || stringField(visibleResult, "summary");
  }
  const result = payload.result;
  if (isRecord(result)) {
    return stringField(result, "say") || stringField(result, "summary");
  }
  return "";
}

function speechTextFromCue(body: string, actorName: string | null): string {
  if (actorName && body.startsWith(`${actorName}：`)) {
    return body.slice(actorName.length + 1);
  }
  return body;
}

function deathNamesFromPayload(payload: Record<string, unknown>): string[] {
  const deaths = payload.night_deaths;
  if (Array.isArray(deaths)) {
    return deaths
      .map((death) =>
        isRecord(death) && typeof death.player === "string" ? death.player : "",
      )
      .filter(Boolean);
  }
  const eliminated = stringField(payload, "eliminated");
  return eliminated ? [eliminated] : [];
}

function isPeacefulNightPayload(payload: Record<string, unknown>): boolean {
  const attacked = stringField(payload, "attacked");
  const protectedPlayer = stringField(payload, "protected");
  const eliminated = payload.eliminated;
  return Boolean(
    (attacked && protectedPlayer === attacked) ||
      (protectedPlayer && eliminated === null),
  );
}

function skillJudgeLine(payload: Record<string, unknown>): string {
  const selfExploded = stringField(payload, "werewolf_self_exploded");
  if (selfExploded) {
    return `${selfExploded} 发动狼人自爆。`;
  }
  const hunterShot = stringField(payload, "hunter_shot");
  if (hunterShot) {
    return `猎人开枪带走 ${hunterShot}。`;
  }
  const idiotRevealed = stringField(payload, "idiot_revealed");
  if (idiotRevealed) {
    return `${idiotRevealed} 翻牌，继续留在场上。`;
  }
  const badgeTarget = stringField(payload, "sheriff_badge_target");
  if (badgeTarget) {
    return `警徽移交给 ${badgeTarget}。`;
  }
  return "";
}

function activePlayersLine(payload: Record<string, unknown>): string {
  const activePlayers = payload.active_players;
  return Array.isArray(activePlayers)
    ? `存活玩家：${activePlayers.map(String).join("、")}`
    : "";
}

function nextLine(nextSpeakerName: string | null): string {
  return nextSpeakerName ? `下一位：${nextSpeakerName}` : "等待后续发言。";
}

function toneFromDirectorCue(cue: DirectorCue): NarrativeCueTone {
  if (cue.importance === "terminal") {
    return "terminal";
  }
  if (cue.phase === "night") {
    return "night";
  }
  if (cue.phase === "vote") {
    return "vote";
  }
  if (cue.phase === "day") {
    return "day";
  }
  return "neutral";
}

function isPublicSpeechAction(action: string | null): boolean {
  return (
    action === "debate" ||
    action === "sheriff_speech" ||
    action === "sheriff_pk_speech" ||
    action === "summarize"
  );
}

function isVoteAction(action: string | null): boolean {
  return action === "vote" || action === "sheriff_vote" || action === "sheriff_runoff_vote";
}

function payloadForEvent(event: LiveGameEvent): Record<string, unknown> {
  return isRecord(event.payload) ? event.payload : {};
}

function stringField(payload: Record<string, unknown>, field: string): string {
  const value = payload[field];
  return typeof value === "string" ? value : "";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
```

- [ ] **Step 4: Run the pure-function tests and verify they pass**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/liveNarrative.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add apps/web/src/features/games/liveNarrative.ts apps/web/src/features/games/liveNarrative.test.ts
git commit -m "feat(web): derive live narrative cues"
```

## Task 2: Narrative Center Component

**Files:**
- Create: `apps/web/src/features/games/components/LiveNarrativeCenter.test.tsx`
- Create: `apps/web/src/features/games/components/LiveNarrativeCenter.tsx`

- [ ] **Step 1: Write the failing component tests**

Create `apps/web/src/features/games/components/LiveNarrativeCenter.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LiveNarrativeCenter } from "./LiveNarrativeCenter";
import type { LiveNarrativeState } from "../liveNarrative";

function narrative(
  overrides: Partial<LiveNarrativeState> = {},
): LiveNarrativeState {
  return {
    cue: {
      eventId: 12,
      kind: "player-speaking",
      tone: "day",
      judgeLine: "请听 Sam 的发言。",
      performerLine: "Sam 正在发言。",
      detailLine: "下一位：Isaac",
      actorName: "Sam",
      action: "debate",
      speechText: "我会先盘昨晚平安夜，再解释为什么 Isaac 可疑。",
    },
    speaker: {
      name: "Sam",
      seatNumber: 8,
      role: "村民",
      camp: "好人阵营",
      appearanceId: "moonlit",
      avatarImageUrl: "",
    },
    nextSpeakerName: "Isaac",
    judgeLine: "请听 Sam 的发言。",
    performerLine: "Sam 正在发言。",
    detailLine: "下一位：Isaac",
    ...overrides,
  };
}

describe("LiveNarrativeCenter", () => {
  it("renders judge narration, speaker identity, and speech text", () => {
    render(<LiveNarrativeCenter narrative={narrative()} />);

    expect(screen.getByText("法官旁白")).toBeInTheDocument();
    expect(screen.getByText("请听 Sam 的发言。")).toBeInTheDocument();
    expect(screen.getByText("8 号")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Sam" })).toBeInTheDocument();
    expect(screen.getByText("村民")).toBeInTheDocument();
    expect(screen.getByText("好人阵营")).toBeInTheDocument();
    expect(screen.getByText("我会先盘昨晚平安夜，再解释为什么 Isaac 可疑。")).toBeInTheDocument();
    expect(screen.getByText("下一位：Isaac")).toBeInTheDocument();
  });

  it("renders performer and detail lines when no speech text exists", () => {
    render(
      <LiveNarrativeCenter
        narrative={narrative({
          cue: {
            eventId: 20,
            kind: "vote",
            tone: "vote",
            judgeLine: "投票结果公布。",
            performerLine: "票型已经更新。",
            detailLine: "当前最高票：Isaac，2 票。",
            actorName: null,
            action: "vote",
            speechText: "",
          },
          speaker: null,
          nextSpeakerName: null,
          judgeLine: "投票结果公布。",
          performerLine: "票型已经更新。",
          detailLine: "当前最高票：Isaac，2 票。",
        })}
      />,
    );

    expect(screen.getByText("投票结果公布。")).toBeInTheDocument();
    expect(screen.getByText("票型已经更新。")).toBeInTheDocument();
    expect(screen.getByText("当前最高票：Isaac，2 票。")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sam" })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the component test and verify it fails**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/components/LiveNarrativeCenter.test.tsx
```

Expected: FAIL with an import error for `./LiveNarrativeCenter`.

- [ ] **Step 3: Implement `LiveNarrativeCenter.tsx`**

Create `apps/web/src/features/games/components/LiveNarrativeCenter.tsx`:

```tsx
import { Badge } from "../../../components/ui";
import { appearanceClassName } from "../playerProfileOptions";
import type { LiveNarrativeState, NarrativeCueTone } from "../liveNarrative";

type LiveNarrativeCenterProps = {
  narrative: LiveNarrativeState;
};

const TONE_CLASS_BY_TONE: Record<NarrativeCueTone, string> = {
  neutral: "border-amber-300/25 shadow-[0_24px_68px_rgba(0,0,0,0.38)]",
  night: "border-indigo-300/35 shadow-[0_0_44px_rgba(129,140,248,0.18),0_24px_68px_rgba(0,0,0,0.38)]",
  day: "border-amber-300/30 shadow-[0_0_44px_rgba(251,191,36,0.16),0_24px_68px_rgba(0,0,0,0.38)]",
  danger: "border-red-300/35 shadow-[0_0_44px_rgba(248,113,113,0.2),0_24px_68px_rgba(0,0,0,0.38)]",
  safe: "border-teal-300/35 shadow-[0_0_44px_rgba(45,212,191,0.16),0_24px_68px_rgba(0,0,0,0.38)]",
  vote: "border-amber-200/40 shadow-[0_0_44px_rgba(251,191,36,0.2),0_24px_68px_rgba(0,0,0,0.38)]",
  terminal: "border-emerald-300/35 shadow-[0_0_44px_rgba(52,211,153,0.18),0_24px_68px_rgba(0,0,0,0.38)]",
};

export function LiveNarrativeCenter({ narrative }: LiveNarrativeCenterProps) {
  const { cue, speaker } = narrative;
  const displayText = cue.speechText || cue.performerLine;

  return (
    <div
      className={`glass-panel-subtle absolute left-1/2 top-[51%] z-30 w-[min(25rem,50vw)] -translate-x-1/2 -translate-y-1/2 rounded-lg border p-3 text-center sm:top-[55%] sm:w-[min(31rem,64vw)] sm:p-4 ${TONE_CLASS_BY_TONE[cue.tone]}`}
      data-narrative-tone={cue.tone}
      data-testid="live-narrative-center"
    >
      <div className="mb-3 flex flex-wrap justify-center gap-2 text-xs">
        <Badge color="amber" variant="surface">
          法官旁白
        </Badge>
        <Badge color="gray" variant="surface">
          {kindLabel(cue.kind)}
        </Badge>
        {cue.eventId !== null ? (
          <Badge color="gray" variant="surface">
            #{cue.eventId}
          </Badge>
        ) : null}
      </div>

      <p className="text-sm font-semibold tracking-normal text-amber-100">
        {cue.judgeLine}
      </p>

      {speaker ? (
        <div
          className="mt-3 grid grid-cols-[5rem_minmax(0,1fr)] items-center gap-3 rounded-lg border border-amber-300/25 bg-black/45 p-3 text-left sm:grid-cols-[6rem_minmax(0,1fr)]"
          data-testid="live-narrative-speaker"
        >
          <div
            className={`relative flex aspect-[3/4] items-center justify-center overflow-hidden rounded-md border-2 border-amber-300/45 bg-gradient-to-br from-[#26323b] to-[#05070a] ${appearanceClassName(speaker.appearanceId)}`}
          >
            {speaker.avatarImageUrl ? (
              <img
                alt={`${speaker.name} 当前发言形象`}
                className="h-full w-full object-cover"
                src={speaker.avatarImageUrl}
              />
            ) : (
              <span className="text-3xl font-black text-amber-50">
                {avatarText(speaker.name)}
              </span>
            )}
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold text-amber-200">
              {speaker.seatNumber === null ? "席位未定" : `${speaker.seatNumber} 号`}
            </p>
            <h2 className="truncate text-xl font-semibold text-amber-50">
              {speaker.name}
            </h2>
            <div className="mt-2 flex flex-wrap gap-2 text-xs">
              <span className="rounded border border-amber-300/30 bg-amber-400/10 px-2 py-1 text-amber-100">
                {speaker.role}
              </span>
              <span className="rounded border border-sky-300/25 bg-sky-400/10 px-2 py-1 text-sky-100">
                {speaker.camp}
              </span>
            </div>
          </div>
        </div>
      ) : null}

      <div
        className="mt-3 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-md border border-amber-300/15 p-3 text-left text-sm leading-6 text-slate-200 shadow-[inset_0_0_24px_rgba(0,0,0,0.24)] sm:max-h-48 sm:text-base"
        tabIndex={0}
      >
        {displayText}
      </div>

      {cue.detailLine ? (
        <p className="mt-3 text-xs font-semibold text-slate-300">
          {cue.detailLine}
        </p>
      ) : null}
    </div>
  );
}

function kindLabel(kind: LiveNarrativeState["cue"]["kind"]) {
  if (kind === "player-speaking") {
    return "公开发言";
  }
  if (kind === "player-thinking") {
    return "思考中";
  }
  if (kind === "player-action") {
    return "行动";
  }
  if (kind === "vote") {
    return "投票";
  }
  if (kind === "death") {
    return "结算";
  }
  if (kind === "terminal") {
    return "终局";
  }
  if (kind === "judge") {
    return "阶段";
  }
  return "事件";
}

function avatarText(name: string) {
  return Array.from(name).slice(0, 2).join("");
}
```

- [ ] **Step 4: Run the component tests and verify they pass**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/components/LiveNarrativeCenter.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add apps/web/src/features/games/components/LiveNarrativeCenter.tsx apps/web/src/features/games/components/LiveNarrativeCenter.test.tsx
git commit -m "feat(web): render live narrative center"
```

## Task 3: Integrate Narrative State Into Live and Playback Stages

**Files:**
- Modify: `apps/web/src/features/games/components/LiveStageExperience.tsx`
- Modify: `apps/web/src/features/games/components/LiveDirectorStage.tsx`
- Modify: `apps/web/src/pages/LiveGamePage.test.tsx`
- Modify: `apps/web/src/pages/GamePlaybackPage.test.tsx`

- [ ] **Step 1: Add failing page-level assertions**

In `apps/web/src/pages/LiveGamePage.test.tsx`, inside the existing `"renders live events and completed replay link"` test, after the `action_requested` / streaming events are emitted and before the existing catch-up assertions, add:

```tsx
expect(await screen.findByText("请 张三 发言。")).toBeInTheDocument();
expect(screen.getByText("张三 正在整理公开发言。")).toBeInTheDocument();
```

In the same test, after the existing “追到最新” interaction and before the existing assertion for heading `"张三 正在发言"`, add:

```tsx
expect(screen.getByText("法官旁白")).toBeInTheDocument();
expect(screen.getByText("请听 张三 的发言。")).toBeInTheDocument();
expect(screen.getByTestId("live-narrative-center")).toHaveTextContent("我不是狼");
```

In `apps/web/src/pages/GamePlaybackPage.test.tsx`, in `"renders complete playback on the live stage"`, after `expect(screen.getByText("观赛舞台")).toBeInTheDocument();`, add:

```tsx
expect(screen.getByText("法官旁白")).toBeInTheDocument();
expect(screen.getByText("对局开始")).toBeInTheDocument();
```

- [ ] **Step 2: Run page tests and verify they fail**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx src/pages/GamePlaybackPage.test.tsx
```

Expected: FAIL because the stage does not render `live-narrative-center` or the new narration text yet.

- [ ] **Step 3: Wire `deriveLiveNarrativeState()` in `LiveStageExperience`**

Modify `apps/web/src/features/games/components/LiveStageExperience.tsx`.

Add this import:

```ts
import { deriveLiveNarrativeState } from "../liveNarrative";
```

After `focusedPlayerName` is computed, add:

```ts
  const narrativeState = useMemo(
    () =>
      deriveLiveNarrativeState({
        cue: director.currentCue,
        events,
        godViewState,
        spectatorState,
      }),
    [director.currentCue, events, godViewState, spectatorState],
  );
```

Pass it into `LiveDirectorStage`:

```tsx
            narrativeState={narrativeState}
```

- [ ] **Step 4: Replace the center card contents in `LiveDirectorStage`**

Modify `apps/web/src/features/games/components/LiveDirectorStage.tsx`.

Add imports:

```ts
import type { LiveNarrativeState } from "../liveNarrative";
import { LiveNarrativeCenter } from "./LiveNarrativeCenter";
```

Add a prop:

```ts
  narrativeState: LiveNarrativeState;
```

Destructure it:

```ts
  narrativeState,
```

Remove the now-unused local variables:

```ts
  const focusedGodPlayer =
    godViewState?.players.find((player) => player.name === focusedPlayerName) ??
    null;
  const speakerGodPlayer = godViewState?.speakerFlow.current ?? focusedGodPlayer;
  const title = cue?.title ?? "等待导播事件";
  const body = cue?.body ?? "对局运行已创建，正在等待下一条实时事件。";
```

Replace the existing central absolute block that starts with:

```tsx
        <div className="glass-panel-subtle absolute left-1/2 top-[51%] z-30 ...
```

and ends immediately before:

```tsx
        {stagePlayers.length === 0 ? (
```

with:

```tsx
        <LiveNarrativeCenter narrative={narrativeState} />
```

Keep the queue/debug badges in the stage by moving them into the top pill area. Replace the existing top pill contents:

```tsx
          <div className="glass-panel-subtle mx-auto flex w-fit items-center gap-3 rounded-full border border-amber-300/35 px-4 py-2 text-sm shadow-[0_0_28px_rgba(245,158,11,0.2)]">
            <span className="text-slate-400">观赛舞台</span>
            <span className="font-semibold text-amber-200">
              {cue?.round ? `第 ${cue.round} 轮` : "等待回合"}
            </span>
            <span className="text-amber-500/40">|</span>
            <span className="font-semibold text-teal-100">
              {cue?.phase ? phaseLabel(cue.phase) : "阶段未开始"}
            </span>
          </div>
```

with:

```tsx
          <div className="glass-panel-subtle mx-auto flex w-fit flex-wrap items-center justify-center gap-2 rounded-full border border-amber-300/35 px-4 py-2 text-sm shadow-[0_0_28px_rgba(245,158,11,0.2)]">
            <span className="text-slate-400">观赛舞台</span>
            <span className="font-semibold text-amber-200">
              {cue?.round ? `第 ${cue.round} 轮` : "等待回合"}
            </span>
            <span className="text-amber-500/40">|</span>
            <span className="font-semibold text-teal-100">
              {cue?.phase ? phaseLabel(cue.phase) : "阶段未开始"}
            </span>
            {cue ? (
              <Badge color="amber" variant="surface">
                #{cue.eventId}
              </Badge>
            ) : null}
            <Badge color="gray" variant="surface">
              队列剩余：{backlogCount}
            </Badge>
            {debugTrace ? (
              <Badge color="amber" variant="surface">
                {traceEventRange(debugTrace)}
              </Badge>
            ) : null}
            {isCatchingUp ? (
              <Badge color="amber" variant="surface">
                自动追进度中
              </Badge>
            ) : null}
          </div>
```

Remove helper functions that become unused after this replacement:

```ts
function speakerTone(player: GodViewPlayer) { ... }
function importanceLabel(importance: DirectorCue["importance"]) { ... }
```

Keep `traceEventRange()` because the top pill now uses it.

- [ ] **Step 5: Run the page tests and verify they pass**

Run:

```bash
pnpm --dir apps/web exec vitest run src/pages/LiveGamePage.test.tsx src/pages/GamePlaybackPage.test.tsx
```

Expected: PASS.

- [ ] **Step 6: Commit Task 3**

```bash
git add apps/web/src/features/games/components/LiveStageExperience.tsx apps/web/src/features/games/components/LiveDirectorStage.tsx apps/web/src/pages/LiveGamePage.test.tsx apps/web/src/pages/GamePlaybackPage.test.tsx
git commit -m "feat(web): connect narrative stage to live playback"
```

## Task 4: Final Verification and Browser Check

**Files:**
- No new files expected.
- Verify: `apps/web/src/features/games/liveNarrative.ts`
- Verify: `apps/web/src/features/games/components/LiveNarrativeCenter.tsx`
- Verify: `apps/web/src/features/games/components/LiveDirectorStage.tsx`
- Verify: `apps/web/src/pages/LiveGamePage.test.tsx`
- Verify: `apps/web/src/pages/GamePlaybackPage.test.tsx`

- [ ] **Step 1: Run all targeted tests**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/liveNarrative.test.ts src/features/games/components/LiveNarrativeCenter.test.tsx src/pages/LiveGamePage.test.tsx src/pages/GamePlaybackPage.test.tsx
```

Expected: PASS.

- [ ] **Step 2: Run existing adjacent derivation tests**

Run:

```bash
pnpm --dir apps/web exec vitest run src/features/games/liveDirector.test.ts src/features/games/liveGodView.test.ts src/features/games/liveSpectator.test.ts
```

Expected: PASS.

- [ ] **Step 3: Build the frontend**

Run:

```bash
pnpm --dir apps/web build
```

Expected: PASS with Vite build output and no TypeScript errors.

- [ ] **Step 4: Start the local web app if it is not already running**

Run:

```bash
pnpm --dir apps/web dev --host 127.0.0.1 --port 5173
```

Expected: dev server starts on `http://127.0.0.1:5173`. If port `5173` is occupied by an existing Vite server, use that server and do not start a duplicate.

- [ ] **Step 5: Open a live or playback URL in the in-app browser**

Use a known existing local URL from the current dev environment, such as:

```text
http://127.0.0.1:5173/games
```

Start or open a game, navigate to `/games/live/:runId`, and verify these visible conditions:

- The central stage includes `法官旁白`.
- Phase changes display judge lines such as `天黑请闭眼。` or `天亮了`.
- A public speech event displays the speaker identity and speech text in the central narrative card.
- Player rails, right-side intelligence panel, bottom board, debug panel, and nav settings remain visible.

- [ ] **Step 6: Commit any verification-only test adjustments**

If Task 4 required no code or test changes, do not commit. If a small test selector adjustment was needed, commit only that adjustment:

```bash
git add apps/web/src/pages/LiveGamePage.test.tsx apps/web/src/pages/GamePlaybackPage.test.tsx
git commit -m "test(web): cover narrative stage verification"
```

## Self-Review

Spec coverage:

- 法官旁白: Task 1 derives phase and result lines; Task 2 renders them; Task 3 verifies them on live/playback pages.
- 玩家发言表演: Task 1 maps action requests, streaming cues, parsed speech, and debate state updates; Task 2 renders speaker identity and speech text; Task 3 wires the state into the stage.
- Existing timing and playback: Task 1 consumes `DirectorCue` rather than replacing `useLiveDirector`; Task 3 keeps existing `director.currentCue` flow.
- No backend protocol change: all tasks are in `apps/web`.
- Fallback behavior: Task 1 includes unknown-event fallback.
- Public information boundary: Task 1 only uses existing public event payloads and `DirectorCue` body.
- Existing debug/god-view controls: Task 3 preserves stage shell, rails, debug trace highlighting, top bar, left/right/bottom panels, and nav controls.

Placeholder scan:

- The plan contains no placeholder markers or undefined follow-up tasks.
- Every code-changing task includes concrete file paths, test code, implementation code, commands, and expected outcomes.

Type consistency:

- `LiveNarrativeState`, `NarrativeCue`, and `NarrativeSpeaker` are defined in Task 1 and reused by Task 2 and Task 3 with the same property names.
- `narrativeState` is the prop name used consistently from `LiveStageExperience` to `LiveDirectorStage`.
- `LiveNarrativeCenter` receives `narrative`, not `state`, in both tests and implementation.
