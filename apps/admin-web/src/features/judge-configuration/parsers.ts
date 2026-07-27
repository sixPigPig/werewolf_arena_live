import type {
  AdminJudgeConfiguration,
  JudgeSpeakerOption,
} from "@/features/judge-configuration/types";

export function parseAdminJudgeConfiguration(value: unknown): AdminJudgeConfiguration {
  const record = objectValue(value, "法官配置");
  const voiceMode = stringValue(record.voice_mode, "voice_mode");
  if (voiceMode !== "fixed" && voiceMode !== "random") {
    throw new Error("法官配置包含不支持的音色模式");
  }
  const source = stringValue(record.source, "source");
  if (source !== "database" && source !== "environment") {
    throw new Error("法官配置包含不支持的来源");
  }
  return {
    voice_mode: voiceMode,
    tts_speaker: stringValue(record.tts_speaker, "tts_speaker"),
    random_tts_speakers: arrayValue(
      record.random_tts_speakers,
      "random_tts_speakers",
    ).map((speaker) => stringValue(speaker, "random_tts_speakers[]")),
    version: nonNegativeInteger(record.version, "version"),
    source,
    updated_at: nullableString(record.updated_at, "updated_at"),
    speakers: arrayValue(record.speakers, "speakers").map(parseSpeaker),
    speaker_catalog_available: booleanValue(
      record.speaker_catalog_available,
      "speaker_catalog_available",
    ),
    tts_resource_id: stringValue(record.tts_resource_id, "tts_resource_id"),
  };
}

function parseSpeaker(value: unknown): JudgeSpeakerOption {
  const record = objectValue(value, "speakers[]");
  return {
    voice_type: stringValue(record.voice_type, "speakers[].voice_type"),
    name: stringValue(record.name, "speakers[].name"),
  };
}

function objectValue(value: unknown, field: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${field} 不是对象`);
  }
  return value as Record<string, unknown>;
}

function arrayValue(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${field} 不是数组`);
  }
  return value;
}

function stringValue(value: unknown, field: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${field} 不是非空字符串`);
  }
  return value;
}

function nullableString(value: unknown, field: string): string | null {
  if (value === null) return null;
  return stringValue(value, field);
}

function booleanValue(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${field} 不是布尔值`);
  }
  return value;
}

function nonNegativeInteger(value: unknown, field: string): number {
  if (!Number.isInteger(value) || (value as number) < 0) {
    throw new Error(`${field} 不是非负整数`);
  }
  return value as number;
}
