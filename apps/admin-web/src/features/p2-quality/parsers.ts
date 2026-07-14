import { AdminApiError } from "@/api/problem-details";
import type {
  AdminGameP2Quality,
  AdminP2ChoiceNormalization,
  AdminP2DataStatus,
  AdminP2Performance,
  AdminP2SpeechQuality,
  AdminPublicOutcome,
  AdminRunP2Diagnostics,
} from "@/features/p2-quality/types";

const DATA_STATUSES: AdminP2DataStatus[] = [
  "legacy",
  "collecting",
  "available",
  "unavailable",
];
const OUTCOME_KINDS: AdminPublicOutcome["kind"][] = [
  "night_death",
  "hunter_shot",
  "self_explosion",
  "exile",
  "idiot_reveal",
  "badge_transferred",
  "badge_lost",
];

export function parseAdminRunP2Diagnostics(
  value: unknown,
): AdminRunP2Diagnostics {
  const record = recordValue(value, "p2_diagnostics");
  return {
    schema_version: schemaVersion(record.schema_version),
    data_status: enumValue(record.data_status, DATA_STATUSES, "data_status"),
    performance: parsePerformance(record.performance),
    speech_quality: parseSpeech(record.speech_quality),
    choice_normalization: parseChoice(record.choice_normalization),
  };
}

export function parseAdminGameP2Quality(value: unknown): AdminGameP2Quality {
  const record = recordValue(value, "p2_quality");
  const base = parseAdminRunP2Diagnostics(record);
  const lineup = recordValue(record.lineup_quality, "lineup_quality");
  const violations = arrayValue(lineup.violations, "lineup_quality.violations").map(
    (value) => {
      const violation = recordValue(value, "lineup_quality.violation");
      return {
        code: requiredString(violation.code, "lineup_quality.violation.code"),
        severity: enumValue(
          violation.severity,
          ["warning", "error"] as const,
          "lineup_quality.violation.severity",
        ),
        count: nonNegativeInteger(
          violation.count,
          "lineup_quality.violation.count",
        ),
        limit: nonNegativeInteger(
          violation.limit,
          "lineup_quality.violation.limit",
        ),
        seat_numbers: arrayValue(
          violation.seat_numbers,
          "lineup_quality.violation.seat_numbers",
        ).map((seat) => positiveInteger(seat, "lineup_quality.violation.seat")),
      };
    },
  );
  const outcomes = arrayValue(record.public_outcomes, "public_outcomes").map(
    parseOutcome,
  );
  const seen = new Set<string>();
  for (const outcome of outcomes) {
    if (seen.has(outcome.event_id)) {
      throw invalidContract("public_outcomes 包含重复 event_id");
    }
    seen.add(outcome.event_id);
  }
  return {
    ...base,
    lineup_quality: {
      policy_mode:
        lineup.policy_mode === null
          ? null
          : enumValue(
              lineup.policy_mode,
              ["observe", "repair", "enforce"] as const,
              "lineup_quality.policy_mode",
            ),
      was_repaired: nullableBoolean(
        lineup.was_repaired,
        "lineup_quality.was_repaired",
      ),
      is_blocked: nullableBoolean(
        lineup.is_blocked,
        "lineup_quality.is_blocked",
      ),
      style_bucket_count: nullableNonNegativeInteger(
        lineup.style_bucket_count,
        "lineup_quality.style_bucket_count",
      ),
      required_style_bucket_count: nullableNonNegativeInteger(
        lineup.required_style_bucket_count,
        "lineup_quality.required_style_bucket_count",
      ),
      violations,
    },
    public_outcomes: outcomes,
    public_outcome_summary_mismatch_count: nonNegativeInteger(
      record.public_outcome_summary_mismatch_count,
      "public_outcome_summary_mismatch_count",
    ),
    quality_gates: arrayValue(record.quality_gates, "quality_gates").map(
      (value) => {
        const gate = recordValue(value, "quality_gate");
        return {
          gate: requiredString(gate.gate, "quality_gate.gate"),
          status: enumValue(
            gate.status,
            ["pass", "warn", "fail", "unavailable"] as const,
            "quality_gate.status",
          ),
          code: requiredString(gate.code, "quality_gate.code"),
          threshold: nullableString(gate.threshold, "quality_gate.threshold"),
          actual: nullableString(gate.actual, "quality_gate.actual"),
        };
      },
    ),
  };
}

function parsePerformance(value: unknown): AdminP2Performance {
  const record = recordValue(value, "performance");
  return {
    request_count: nonNegativeInteger(record.request_count, "request_count"),
    discrete_action_sample_count: nonNegativeInteger(
      record.discrete_action_sample_count,
      "discrete_action_sample_count",
    ),
    discrete_action_p50_ms: nullableNonNegativeInteger(
      record.discrete_action_p50_ms,
      "discrete_action_p50_ms",
    ),
    discrete_action_p95_ms: nullableNonNegativeInteger(
      record.discrete_action_p95_ms,
      "discrete_action_p95_ms",
    ),
    discrete_action_max_ms: nullableNonNegativeInteger(
      record.discrete_action_max_ms,
      "discrete_action_max_ms",
    ),
    speech_first_token_sample_count: nonNegativeInteger(
      record.speech_first_token_sample_count,
      "speech_first_token_sample_count",
    ),
    speech_first_token_p95_ms: nullableNonNegativeInteger(
      record.speech_first_token_p95_ms,
      "speech_first_token_p95_ms",
    ),
    speech_first_token_max_ms: nullableNonNegativeInteger(
      record.speech_first_token_max_ms,
      "speech_first_token_max_ms",
    ),
    timeout_count: nonNegativeInteger(record.timeout_count, "timeout_count"),
    fallback_count: nonNegativeInteger(record.fallback_count, "fallback_count"),
    active_request_count: nonNegativeInteger(
      record.active_request_count,
      "active_request_count",
    ),
    game_duration_ms: nullableNonNegativeInteger(
      record.game_duration_ms,
      "game_duration_ms",
    ),
  };
}

function parseSpeech(value: unknown): AdminP2SpeechQuality {
  const record = recordValue(value, "speech_quality");
  return {
    checked_count: nonNegativeInteger(record.checked_count, "checked_count"),
    retry_count: nonNegativeInteger(record.retry_count, "retry_count"),
    exhausted_count: nonNegativeInteger(record.exhausted_count, "exhausted_count"),
    low_novelty_window_count: nonNegativeInteger(
      record.low_novelty_window_count,
      "low_novelty_window_count",
    ),
  };
}

function parseChoice(value: unknown): AdminP2ChoiceNormalization {
  const record = recordValue(value, "choice_normalization");
  return {
    exact_count: nonNegativeInteger(record.exact_count, "exact_count"),
    seat_alias_count: nonNegativeInteger(record.seat_alias_count, "seat_alias_count"),
    public_label_count: nonNegativeInteger(
      record.public_label_count,
      "public_label_count",
    ),
    invalid_count: nonNegativeInteger(record.invalid_count, "invalid_count"),
    other_count: nonNegativeInteger(record.other_count, "other_count"),
  };
}

function parseOutcome(value: unknown): AdminPublicOutcome {
  const record = recordValue(value, "public_outcome");
  return {
    schema_version: schemaVersion(record.schema_version),
    round_number: nonNegativeInteger(record.round_number, "round_number"),
    event_id: requiredString(record.event_id, "event_id"),
    sequence: positiveInteger(record.sequence, "sequence"),
    kind: enumValue(record.kind, OUTCOME_KINDS, "kind"),
    actor_player_id: nullableString(record.actor_player_id, "actor_player_id"),
    target_player_id: nullableString(record.target_player_id, "target_player_id"),
    outcome: requiredString(record.outcome, "outcome"),
    caused_by_event_id: nullableString(
      record.caused_by_event_id,
      "caused_by_event_id",
    ),
    occurred_phase: requiredString(record.occurred_phase, "occurred_phase"),
  };
}

function recordValue(value: unknown, field: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw invalidContract(`${field} 不是对象`);
  }
  return value as Record<string, unknown>;
}

function arrayValue(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) {
    throw invalidContract(`${field} 不是数组`);
  }
  return value;
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw invalidContract(`${field} 不是非空字符串`);
  }
  return value;
}

function nullableString(value: unknown, field: string): string | null {
  return value === null ? null : requiredString(value, field);
}

function nonNegativeInteger(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw invalidContract(`${field} 不是非负整数`);
  }
  return value;
}

function positiveInteger(value: unknown, field: string): number {
  const parsed = nonNegativeInteger(value, field);
  if (parsed < 1) {
    throw invalidContract(`${field} 不是正整数`);
  }
  return parsed;
}

function nullableNonNegativeInteger(
  value: unknown,
  field: string,
): number | null {
  return value === null ? null : nonNegativeInteger(value, field);
}

function nullableBoolean(value: unknown, field: string): boolean | null {
  if (value === null) {
    return null;
  }
  if (typeof value !== "boolean") {
    throw invalidContract(`${field} 不是布尔值`);
  }
  return value;
}

function enumValue<Value extends string>(
  value: unknown,
  allowed: readonly Value[],
  field: string,
): Value {
  const parsed = requiredString(value, field);
  if (!allowed.includes(parsed as Value)) {
    throw invalidContract(`${field} 枚举值无效`);
  }
  return parsed as Value;
}

function schemaVersion(value: unknown): 1 {
  if (value !== 1) {
    throw invalidContract("schema_version 必须为 1");
  }
  return 1;
}

function invalidContract(detail: string) {
  return new AdminApiError({
    problem: {
      type: "about:blank",
      title: "P2 质量响应无效",
      status: 502,
      detail,
      code: "admin_invalid_p2_quality_response",
      request_id: null,
    },
  });
}
