import { AdminApiError } from "@/api/problem-details";
import type {
  LivenessExperienceOption,
  LivenessRolloutConfig,
} from "@/features/liveness-rollout/types";

export function parseLivenessRolloutConfig(value: unknown): LivenessRolloutConfig {
  const record = objectValue(value, "响应");
  const treatment = integer(record.treatment_percent, "treatment_percent", 0, 100);
  const control = integer(record.control_percent, "control_percent", 0, 100);
  if (treatment + control !== 100) throw invalid("灰度比例总和不是 100");
  const updatedAt = nullableString(record.updated_at, "updated_at");
  if (updatedAt !== null && !Number.isFinite(Date.parse(updatedAt))) {
    throw invalid("updated_at 不是有效时间");
  }
  if (!Array.isArray(record.available_experiences)) {
    throw invalid("available_experiences 不是数组");
  }
  return {
    revision: integer(record.revision, "revision", 0),
    experience_revision: stringValue(record.experience_revision, "experience_revision"),
    experiment_id: stringValue(record.experiment_id, "experiment_id"),
    treatment_percent: treatment,
    control_percent: control,
    source: enumValue(record.source, ["database", "environment_fallback"] as const, "source"),
    effective_scope: enumValue(record.effective_scope, ["new_sessions_only"] as const, "effective_scope"),
    updated_at: updatedAt,
    available_experiences: record.available_experiences.map(parseOption),
  };
}

function parseOption(value: unknown): LivenessExperienceOption {
  const record = objectValue(value, "available_experiences[]");
  return {
    revision: stringValue(record.revision, "option.revision"),
    label: stringValue(record.label, "option.label"),
    description: stringValue(record.description, "option.description"),
    control_summary: stringValue(record.control_summary, "option.control_summary"),
    treatment_summary: stringValue(record.treatment_summary, "option.treatment_summary"),
  };
}

function objectValue(value: unknown, field: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw invalid(`${field}不是对象`);
  }
  return value as Record<string, unknown>;
}

function stringValue(value: unknown, field: string): string {
  if (typeof value !== "string" || !value) throw invalid(`${field} 不是有效字符串`);
  return value;
}

function nullableString(value: unknown, field: string): string | null {
  return value === null ? null : stringValue(value, field);
}

function integer(value: unknown, field: string, min: number, max = Number.MAX_SAFE_INTEGER): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < min || value > max) {
    throw invalid(`${field} 不是有效整数`);
  }
  return value;
}

function enumValue<const Values extends readonly string[]>(
  value: unknown,
  values: Values,
  field: string,
): Values[number] {
  const parsed = stringValue(value, field);
  if (!values.includes(parsed)) throw invalid(`${field} 枚举值无效`);
  return parsed as Values[number];
}

function invalid(detail: string) {
  return new AdminApiError({
    problem: {
      type: "about:blank",
      title: "灰度配置接口响应无效",
      status: 502,
      detail,
      code: "admin_invalid_liveness_rollout_response",
      request_id: null,
    },
  });
}
