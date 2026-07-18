import type {
  LiveGameEvent,
  PublicActionOrigin,
  PublicPhaseCompletionStatus,
  PublicSpeechStatus,
} from "../types";

export type LivePublicStatusKind =
  | "not_spoken"
  | "system_fallback"
  | "rule_default"
  | "canceled"
  | "retry_completed"
  | "legacy_unknown";

export type LivePublicStatus = {
  kind: LivePublicStatusKind;
  label: string;
  origin: PublicActionOrigin | null;
  reasonCode: string | null;
};

export type LivePhaseLifecycle = {
  kind: "started" | "completed";
  phaseInstanceId: string | null;
  completionStatus: PublicPhaseCompletionStatus | null;
  completionReason: string | null;
  nextPhase: string | null;
  terminal: boolean;
};

const PUBLIC_VOTE_ACTIONS = new Set([
  "vote",
  "sheriff_vote",
  "sheriff_runoff_vote",
  "exile_runoff_vote",
]);

const NOT_SPOKEN_STATUSES = new Set([
  "not_spoken",
  "did_not_speak",
  "speech_failed",
]);

const RETRY_ORIGINS = new Set([
  "model_retry",
  "model_retry_success",
  "model_after_retry",
  "retry_completed",
]);

const RETRY_REASON_CODES = new Set([
  "retry_succeeded",
  "retry_completed",
  "model_retry_succeeded",
]);

export function livePublicStatusForEvent(
  event: LiveGameEvent,
): LivePublicStatus | null {
  const origin = publicActionOrigin(event);
  const reasonCode = publicReasonCode(event);
  const speechStatus = publicSpeechStatus(event);

  if (
    event.type === "player_did_not_speak" ||
    (speechStatus !== null && NOT_SPOKEN_STATUSES.has(speechStatus))
  ) {
    return status("not_spoken", "未发言", origin, reasonCode);
  }

  if (
    event.type === "public_action_cancelled" ||
    origin === "canceled" ||
    origin === "cancelled"
  ) {
    return status("canceled", "动作取消", origin, reasonCode);
  }

  if (
    origin === "rule_default" ||
    origin === "rule" ||
    ((origin === "system_fallback" || origin === "system") &&
      reasonCode?.startsWith("rule_default"))
  ) {
    return status("rule_default", "规则默认", origin, reasonCode);
  }

  if (
    PUBLIC_VOTE_ACTIONS.has(event.action ?? "") &&
    (origin === "system_fallback" ||
      origin === "system" ||
      origin === "timeout_fallback")
  ) {
    return status("system_fallback", "系统代投", origin, reasonCode);
  }

  if (
    event.type === "action_parsed" &&
    (origin === null || origin === "model" || RETRY_ORIGINS.has(origin)) &&
    (RETRY_ORIGINS.has(origin ?? "") ||
      RETRY_REASON_CODES.has(reasonCode ?? "") ||
      hasRetryEvidence(event))
  ) {
    return status("retry_completed", "重试后完成", origin, reasonCode);
  }

  if (event.type === "action_parsed" && origin === null) {
    return status(
      "legacy_unknown",
      "来源未知 · 旧数据",
      "legacy_unknown",
      reasonCode,
    );
  }

  return null;
}

export function livePhaseLifecycleForEvent(
  event: LiveGameEvent,
): LivePhaseLifecycle | null {
  if (event.type !== "phase_started" && event.type !== "phase_completed") {
    return null;
  }

  const completionStatus = stringMeta(
    event,
    "completion_status",
  ) as PublicPhaseCompletionStatus | null;

  return {
    kind: event.type === "phase_started" ? "started" : "completed",
    phaseInstanceId: stringMeta(event, "phase_instance_id"),
    completionStatus,
    completionReason: stringMeta(event, "completion_reason"),
    nextPhase: stringMeta(event, "next_phase"),
    terminal: booleanMeta(event, "terminal") ?? false,
  };
}

export function publicReasonLabel(reasonCode: string | null): string {
  if (!reasonCode) {
    return "";
  }
  const labels: Record<string, string> = {
    action_deadline: "行动超时",
    action_deadline_exceeded: "行动超时",
    action_timeout: "行动超时",
    batch_deadline: "行动超时",
    collective_no_result: "集体行动未形成结果",
    deadline_exceeded: "行动超时",
    invalid_action: "行动无效",
    invalid_exhausted: "行动无效",
    provider_timeout: "发言超时",
    speech_timeout: "发言超时",
    format_retry_exhausted: "未取得有效发言",
    invalid_output_exhausted: "未取得有效发言",
    empty_speech: "未取得有效发言",
    no_valid_say: "未取得有效发言",
    quality_retry_exhausted: "未取得有效发言",
    quality_exhausted: "未取得有效发言",
    quality_rewrite_exhausted: "未取得有效发言",
    self_explosion: "狼人自爆",
    self_explosion_cancelled: "狼人自爆",
    werewolf_self_explosion: "狼人自爆",
    player_eliminated: "玩家已出局",
    phase_closed: "阶段已结束",
    phase_advanced: "阶段已推进",
    rule_default: "按规则执行",
    system_vote_timeout: "投票超时",
    timeout: "请求超时",
    retry_succeeded: "重试后取得有效结果",
    retry_completed: "重试后取得有效结果",
  };
  return labels[reasonCode] ?? "";
}

export function publicActionOrigin(
  event: LiveGameEvent,
): PublicActionOrigin | null {
  return stringMeta(event, "action_origin") as PublicActionOrigin | null;
}

export function publicReasonCode(event: LiveGameEvent): string | null {
  return (
    stringMeta(event, "public_reason_code") ??
    stringMeta(event, "reason_code")
  );
}

export function publicSpeechStatus(
  event: LiveGameEvent,
): PublicSpeechStatus | null {
  return stringMeta(event, "speech_status") as PublicSpeechStatus | null;
}

function status(
  kind: LivePublicStatusKind,
  label: string,
  origin: PublicActionOrigin | null,
  reasonCode: string | null,
): LivePublicStatus {
  return { kind, label, origin, reasonCode };
}

function hasRetryEvidence(event: LiveGameEvent): boolean {
  return (
    booleanMeta(event, "retry_completed") === true ||
    numberMeta(event, "attempt_count") > 1 ||
    numberMeta(event, "attempt") > 1 ||
    numberMeta(event, "retry_count") > 0 ||
    numberMeta(event, "quality_attempt_count") > 1
  );
}

function stringMeta(event: LiveGameEvent, field: string): string | null {
  const direct = (event as unknown as Record<string, unknown>)[field];
  if (typeof direct === "string" && direct.trim()) {
    return direct;
  }
  const payload = isRecord(event.payload) ? event.payload : {};
  const nested = payload[field];
  return typeof nested === "string" && nested.trim() ? nested : null;
}

function numberMeta(event: LiveGameEvent, field: string): number {
  const direct = (event as unknown as Record<string, unknown>)[field];
  if (typeof direct === "number" && Number.isFinite(direct)) {
    return direct;
  }
  const payload = isRecord(event.payload) ? event.payload : {};
  const nested = payload[field];
  return typeof nested === "number" && Number.isFinite(nested) ? nested : 0;
}

function booleanMeta(event: LiveGameEvent, field: string): boolean | null {
  const direct = (event as unknown as Record<string, unknown>)[field];
  if (typeof direct === "boolean") {
    return direct;
  }
  const payload = isRecord(event.payload) ? event.payload : {};
  const nested = payload[field];
  return typeof nested === "boolean" ? nested : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}
