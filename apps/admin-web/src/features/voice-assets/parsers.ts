import { AdminApiError } from "@/api/problem-details";
import type {
  AdminJudgeVoiceCategory,
  AdminJudgeVoiceLine,
  AdminJudgeVoiceList,
} from "@/features/voice-assets/types";

const FORBIDDEN_KEYS = new Set([
  "filename",
  "public_url",
  "manifest_path",
  "subtitle_timings",
  "audio",
  "audio_chunks",
  "chunks",
  "request_id",
  "speaker",
  "speaker_name",
  "error",
  "error_message",
]);

export function parseAdminJudgeVoiceList(value: unknown): AdminJudgeVoiceList {
  rejectForbiddenFields(value);
  const record = recordValue(value);
  const coverageRecord = recordValue(record.coverage);
  const paginationRecord = recordValue(record.pagination);
  const coverage = {
    total: nonNegativeInteger(coverageRecord.total, "coverage.total"),
    available: nonNegativeInteger(
      coverageRecord.available,
      "coverage.available",
    ),
    missing: nonNegativeInteger(coverageRecord.missing, "coverage.missing"),
    byte_total: nonNegativeInteger(
      coverageRecord.byte_total,
      "coverage.byte_total",
    ),
  };
  if (coverage.available + coverage.missing !== coverage.total) {
    throw invalidContract("语音覆盖率分类之和与总数不一致");
  }
  const categories = arrayValue(record.categories, "categories").map(
    parseCategory,
  );
  categories.forEach((category) => {
    if (category.available + category.missing !== category.total) {
      throw invalidContract(`语音分类 ${category.name} 的覆盖率不一致`);
    }
  });
  const items = arrayValue(record.items, "items").map(parseLine);
  const categoryNames = new Set(categories.map((category) => category.name));
  if (items.some((item) => !categoryNames.has(item.category))) {
    throw invalidContract("语音条目引用了未知分类");
  }
  const storageMode = requiredString(record.storage_mode, "storage_mode");
  if (storageMode !== "database" && storageMode !== "legacy_static_directory") {
    throw invalidContract("未知的语音存储模式");
  }
  return {
    audio_format: requiredString(record.audio_format, "audio_format"),
    sample_rate: positiveInteger(record.sample_rate, "sample_rate"),
    storage_mode: storageMode,
    coverage,
    categories,
    items,
    pagination: {
      page: positiveInteger(paginationRecord.page, "pagination.page"),
      page_size: positiveInteger(
        paginationRecord.page_size,
        "pagination.page_size",
      ),
      total: nonNegativeInteger(
        paginationRecord.total,
        "pagination.total",
      ),
      pages: nonNegativeInteger(
        paginationRecord.pages,
        "pagination.pages",
      ),
    },
  };
}

function parseCategory(value: unknown): AdminJudgeVoiceCategory {
  const record = recordValue(value);
  return {
    name: requiredString(record.name, "category.name"),
    total: nonNegativeInteger(record.total, "category.total"),
    available: nonNegativeInteger(record.available, "category.available"),
    missing: nonNegativeInteger(record.missing, "category.missing"),
  };
}

function parseLine(value: unknown): AdminJudgeVoiceLine {
  const record = recordValue(value);
  const id = requiredString(record.id, "line.id");
  const available = booleanValue(record.available, "line.available");
  const byteSize = nullableNonNegativeInteger(record.byte_size, "line.byte_size");
  const audioUrl = nullableString(record.audio_url, "line.audio_url");
  const expectedAudioUrl = `/api/v1/admin/judge-voice-lines/${encodeURIComponent(id)}/audio`;
  if (available && (byteSize === null || audioUrl !== expectedAudioUrl)) {
    throw invalidContract("已生成语音缺少安全试听地址或文件大小");
  }
  if (!available && (byteSize !== null || audioUrl !== null)) {
    throw invalidContract("缺失语音不得返回试听地址或文件大小");
  }
  return {
    id,
    text: requiredString(record.text, "line.text"),
    category: requiredString(record.category, "line.category"),
    available,
    byte_size: byteSize,
    template_id: nullableString(record.template_id, "line.template_id"),
    seat_number: nullablePositiveInteger(record.seat_number, "line.seat_number"),
    subtitle_cue_count: nonNegativeInteger(
      record.subtitle_cue_count,
      "line.subtitle_cue_count",
    ),
    audio_url: audioUrl,
  };
}

function rejectForbiddenFields(value: unknown, path = "response") {
  if (Array.isArray(value)) {
    value.forEach((item, index) => rejectForbiddenFields(item, `${path}[${index}]`));
    return;
  }
  if (typeof value !== "object" || value === null) return;
  Object.entries(value as Record<string, unknown>).forEach(([key, child]) => {
    if (FORBIDDEN_KEYS.has(key.toLowerCase())) {
      throw invalidContract(`${path}.${key} 不允许出现在语音资产响应中`);
    }
    rejectForbiddenFields(child, `${path}.${key}`);
  });
}

function recordValue(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw invalidContract("响应不是对象");
  }
  return value as Record<string, unknown>;
}

function arrayValue(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) throw invalidContract(`${field} 不是数组`);
  return value;
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw invalidContract(`${field} 不是有效字符串`);
  }
  return value;
}

function nullableString(value: unknown, field: string): string | null {
  if (value === null) return null;
  return requiredString(value, field);
}

function booleanValue(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") throw invalidContract(`${field} 不是布尔值`);
  return value;
}

function positiveInteger(value: unknown, field: string): number {
  if (!Number.isInteger(value) || Number(value) <= 0) {
    throw invalidContract(`${field} 不是正整数`);
  }
  return Number(value);
}

function nonNegativeInteger(value: unknown, field: string): number {
  if (!Number.isInteger(value) || Number(value) < 0) {
    throw invalidContract(`${field} 不是非负整数`);
  }
  return Number(value);
}

function nullableNonNegativeInteger(value: unknown, field: string) {
  return value === null ? null : nonNegativeInteger(value, field);
}

function nullablePositiveInteger(value: unknown, field: string) {
  return value === null ? null : positiveInteger(value, field);
}

function invalidContract(detail: string) {
  return new AdminApiError({
    problem: {
      type: "about:blank",
      title: "后台语音资产响应无效",
      status: 502,
      detail,
      code: "admin_voice_assets_invalid_response",
      request_id: null,
    },
  });
}
