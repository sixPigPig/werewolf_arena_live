import { describe, expect, it } from "vitest";

import type { LiveGameEvent } from "../types";
import {
  livePhaseLifecycleForEvent,
  livePublicStatusForEvent,
} from "./liveEventMeta";

function event(partial: Partial<LiveGameEvent>): LiveGameEvent {
  return {
    id: partial.id ?? 1,
    type: partial.type ?? "action_parsed",
    run_id: "run_1234abcd",
    session_id: "game_1200abcd",
    created_at: "2026-07-18T12:00:00Z",
    round: partial.round ?? 1,
    phase: partial.phase ?? "day",
    actor: partial.actor ?? "1号玩家",
    action: partial.action ?? "vote",
    payload: partial.payload ?? {},
    action_origin: partial.action_origin,
    public_reason_code: partial.public_reason_code,
    speech_status: partial.speech_status,
    phase_instance_id: partial.phase_instance_id,
    completion_status: partial.completion_status,
    completion_reason: partial.completion_reason,
  };
}

describe("livePublicStatusForEvent", () => {
  it("keeps not-spoken, fallback and canceled as distinct public outcomes", () => {
    expect(
      livePublicStatusForEvent(
        event({
          type: "player_did_not_speak",
          action: "debate",
          payload: {
            speech_status: "not_spoken",
            action_origin: "none",
            public_reason_code: "provider_timeout",
          },
        }),
      ),
    ).toMatchObject({ kind: "not_spoken", label: "未发言" });

    expect(
      livePublicStatusForEvent(
        event({ payload: { action_origin: "system_fallback" } }),
      ),
    ).toMatchObject({ kind: "system_fallback", label: "系统代投" });

    expect(
      livePublicStatusForEvent(
        event({
          type: "public_action_cancelled",
          action: "debate",
          payload: { public_reason_code: "self_explosion" },
        }),
      ),
    ).toMatchObject({ kind: "canceled", label: "动作取消" });
  });

  it("labels rule defaults, successful retries and legacy actions", () => {
    expect(
      livePublicStatusForEvent(
        event({
          action: "sheriff_badge",
          payload: { action_origin: "rule_default" },
        }),
      ),
    ).toMatchObject({ kind: "rule_default", label: "规则默认" });

    expect(
      livePublicStatusForEvent(
        event({
          action: "debate",
          payload: { action_origin: "model", retry_completed: true },
        }),
      ),
    ).toMatchObject({ kind: "retry_completed", label: "重试后完成" });

    expect(livePublicStatusForEvent(event({ payload: {} }))).toMatchObject({
      kind: "legacy_unknown",
      label: "来源未知 · 旧数据",
      origin: "legacy_unknown",
    });
  });

  it("does not expose a hidden non-vote fallback as system voting", () => {
    expect(
      livePublicStatusForEvent(
        event({
          phase: "night",
          action: "witch_poison",
          payload: { action_origin: "system_fallback", attempt_count: 2 },
        }),
      ),
    ).toBeNull();
  });

  it("reserves system voting for forced votes while showing non-vote rule defaults", () => {
    expect(
      livePublicStatusForEvent(
        event({
          action: "speech_order",
          payload: { action_origin: "system_fallback" },
        }),
      ),
    ).toBeNull();

    expect(
      livePublicStatusForEvent(
        event({
          action: "speech_order",
          payload: {
            action_origin: "system_fallback",
            public_reason_code: "rule_default_timeout",
          },
        }),
      ),
    ).toMatchObject({
      kind: "rule_default",
      label: "规则默认",
      origin: "system_fallback",
      reasonCode: "rule_default_timeout",
    });

    expect(
      livePublicStatusForEvent(
        event({
          action: "exile_runoff_vote",
          payload: { action_origin: "system_fallback" },
        }),
      ),
    ).toMatchObject({ kind: "system_fallback", label: "系统代投" });
  });

  it("keeps direct rule-default origins as a compatibility alias", () => {
    expect(
      livePublicStatusForEvent(
        event({
          action: "sheriff_badge",
          payload: { action_origin: "rule_default" },
        }),
      ),
    ).toMatchObject({ kind: "rule_default", label: "规则默认" });
  });
});

describe("livePhaseLifecycleForEvent", () => {
  it("reads public lifecycle fields from payload and top-level DTO aliases", () => {
    expect(
      livePhaseLifecycleForEvent(
        event({
          type: "phase_completed",
          payload: {
            phase_instance_id: "phase-day-1",
            completion_status: "completed",
            completion_reason: "self_explosion",
            next_phase: "night",
            terminal: false,
          },
        }),
      ),
    ).toEqual({
      kind: "completed",
      phaseInstanceId: "phase-day-1",
      completionStatus: "completed",
      completionReason: "self_explosion",
      nextPhase: "night",
      terminal: false,
    });

    expect(
      livePhaseLifecycleForEvent(
        event({
          type: "phase_started",
          phase_instance_id: "phase-night-2",
        }),
      )?.phaseInstanceId,
    ).toBe("phase-night-2");
  });
});
