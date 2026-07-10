import { AdminApiError } from "@/api/problem-details";
import type {
  AdminPlayerProfile,
  AdminPlayerProfileList,
  PlayerProfileAppearanceOption,
  PlayerProfileConstraints,
  PlayerProfileOption,
  PlayerProfileOptions,
  PlayerProfileStatus,
} from "@/features/player-profiles/types";

const PROFILE_STATUSES: PlayerProfileStatus[] = [
  "draft",
  "published",
  "archived",
];

export function parseAdminPlayerProfile(value: unknown): AdminPlayerProfile {
  const record = recordValue(value);
  if ("favorite" in record) {
    throw invalidContract("Admin 玩家 DTO 不允许包含 favorite");
  }
  const status = stringValue(record.status);
  if (!PROFILE_STATUSES.includes(status as PlayerProfileStatus)) {
    throw invalidContract("玩家状态无效");
  }

  return {
    id: requiredString(record.id, "id"),
    display_name: requiredString(record.display_name, "display_name"),
    model: requiredString(record.model, "model"),
    personality_id: requiredString(record.personality_id, "personality_id"),
    personality_text: stringValue(record.personality_text),
    appearance_id: requiredString(record.appearance_id, "appearance_id"),
    avatar_asset_id: nullableString(record.avatar_asset_id, "avatar_asset_id"),
    avatar_image_url: stringValue(record.avatar_image_url),
    avatar_image_mime: stringValue(record.avatar_image_mime),
    short_description: stringValue(record.short_description),
    background_story: stringValue(record.background_story),
    speaking_style: stringValue(record.speaking_style),
    catchphrases: stringArray(record.catchphrases, "catchphrases"),
    strategy_profile: requiredString(record.strategy_profile, "strategy_profile"),
    risk_tolerance: tendency(record.risk_tolerance, "risk_tolerance"),
    bluffing_tendency: tendency(record.bluffing_tendency, "bluffing_tendency"),
    trust_tendency: tendency(record.trust_tendency, "trust_tendency"),
    leadership_tendency: tendency(
      record.leadership_tendency,
      "leadership_tendency",
    ),
    talkativeness: tendency(record.talkativeness, "talkativeness"),
    example_messages: stringArray(record.example_messages, "example_messages"),
    display_order: nonNegativeInteger(record.display_order, "display_order"),
    featured: booleanValue(record.featured, "featured"),
    tags: stringArray(record.tags, "tags"),
    status: status as PlayerProfileStatus,
    version: positiveInteger(record.version, "version"),
    created_at: dateString(record.created_at, "created_at"),
    updated_at: dateString(record.updated_at, "updated_at"),
    published_at: nullableDateString(record.published_at, "published_at"),
    deleted_at: nullableDateString(record.deleted_at, "deleted_at"),
    published_by: nullableString(record.published_by, "published_by"),
    updated_by: nullableString(record.updated_by, "updated_by"),
  };
}

export function parseAdminPlayerProfileList(
  value: unknown,
): AdminPlayerProfileList {
  const record = recordValue(value);
  const pagination = recordValue(record.pagination);
  if (!Array.isArray(record.items)) {
    throw invalidContract("玩家列表缺少 items");
  }
  return {
    items: record.items.map(parseAdminPlayerProfile),
    pagination: {
      page: positiveInteger(pagination.page, "pagination.page"),
      page_size: positiveInteger(pagination.page_size, "pagination.page_size"),
      total: nonNegativeInteger(pagination.total, "pagination.total"),
      pages: nonNegativeInteger(pagination.pages, "pagination.pages"),
    },
  };
}

export function parsePlayerProfileOptions(value: unknown): PlayerProfileOptions {
  const record = recordValue(value);
  const constraints = recordValue(record.constraints);
  return {
    models: optionArray(record.models, false).map(({ id, label }) => ({ id, label })),
    personalities: optionArray(record.personalities),
    appearances: appearanceArray(record.appearances),
    strategies: optionArray(record.strategies),
    constraints: parseConstraints(constraints),
  };
}

function parseConstraints(record: Record<string, unknown>): PlayerProfileConstraints {
  return {
    tags_max_items: positiveInteger(record.tags_max_items, "tags_max_items"),
    tag_max_length: positiveInteger(record.tag_max_length, "tag_max_length"),
    catchphrases_max_items: positiveInteger(
      record.catchphrases_max_items,
      "catchphrases_max_items",
    ),
    catchphrase_max_length: positiveInteger(
      record.catchphrase_max_length,
      "catchphrase_max_length",
    ),
    example_messages_max_items: positiveInteger(
      record.example_messages_max_items,
      "example_messages_max_items",
    ),
    example_message_max_length: positiveInteger(
      record.example_message_max_length,
      "example_message_max_length",
    ),
  };
}

function optionArray(value: unknown, requireDescription = true): PlayerProfileOption[] {
  if (!Array.isArray(value)) {
    throw invalidContract("选项列表格式无效");
  }
  return value.map((item) => {
    const record = recordValue(item);
    return {
      id: requiredString(record.id, "option.id"),
      label: requiredString(record.label, "option.label"),
      description: requireDescription ? stringValue(record.description) : "",
    };
  });
}

function appearanceArray(value: unknown): PlayerProfileAppearanceOption[] {
  if (!Array.isArray(value)) {
    throw invalidContract("形象选项格式无效");
  }
  return value.map((item) => {
    const record = recordValue(item);
    return {
      id: requiredString(record.id, "appearance.id"),
      label: requiredString(record.label, "appearance.label"),
      description: stringValue(record.description),
      avatar_asset_id: nullableString(
        record.avatar_asset_id,
        "appearance.avatar_asset_id",
      ),
      avatar_image_url: stringValue(record.avatar_image_url),
    };
  });
}

function recordValue(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw invalidContract("响应不是对象");
  }
  return value as Record<string, unknown>;
}

function stringValue(value: unknown) {
  if (typeof value !== "string") {
    throw invalidContract("响应字符串字段无效");
  }
  return value;
}

function requiredString(value: unknown, field: string) {
  const parsed = stringValue(value);
  if (!parsed) {
    throw invalidContract(`${field} 不能为空`);
  }
  return parsed;
}

function nullableString(value: unknown, field: string): string | null {
  if (value === null) {
    return null;
  }
  return requiredString(value, field);
}

function stringArray(value: unknown, field: string) {
  if (!Array.isArray(value) || !value.every((item) => typeof item === "string")) {
    throw invalidContract(`${field} 不是字符串数组`);
  }
  return [...value];
}

function positiveInteger(value: unknown, field: string) {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 1) {
    throw invalidContract(`${field} 不是正整数`);
  }
  return value;
}

function nonNegativeInteger(value: unknown, field: string) {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw invalidContract(`${field} 不是非负整数`);
  }
  return value;
}

function tendency(value: unknown, field: string) {
  const parsed = positiveInteger(value, field);
  if (parsed > 5) {
    throw invalidContract(`${field} 超出范围`);
  }
  return parsed;
}

function booleanValue(value: unknown, field: string) {
  if (typeof value !== "boolean") {
    throw invalidContract(`${field} 不是布尔值`);
  }
  return value;
}

function dateString(value: unknown, field: string) {
  const parsed = requiredString(value, field);
  if (!Number.isFinite(Date.parse(parsed))) {
    throw invalidContract(`${field} 不是有效时间`);
  }
  return parsed;
}

function nullableDateString(value: unknown, field: string): string | null {
  return value === null ? null : dateString(value, field);
}

function invalidContract(detail: string) {
  return new AdminApiError({
    problem: {
      type: "about:blank",
      title: "玩家接口响应无效",
      status: 502,
      detail,
      code: "admin_invalid_player_profile_response",
      request_id: null,
    },
  });
}
