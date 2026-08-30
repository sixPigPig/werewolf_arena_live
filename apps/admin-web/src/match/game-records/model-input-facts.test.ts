import { describe, expect, it } from "vitest";

import {
  extractV2ModelInputFactResult,
  extractV2ModelInputFacts,
} from "@/v2/game-records/model-input-facts";

describe("extractV2ModelInputFacts", () => {
  it("uses only backend-verified V13 expansion in retained source order", () => {
    const request = v13Request();

    const result = extractV2ModelInputFactResult(request);

    expect(result.status).toBe("supported");
    expect(result.modelContextSchemaVersion).toBe(13);
    expect(result.facts.map((fact) => [fact.id, fact.recordSeq])).toEqual([
      ["451", 451],
      ["472", 472],
    ]);
    expect(result.facts[1].summary).toBe("只能消费后端已验证展开的入选事件。");
    expect(extractV2ModelInputFacts(request)).toEqual(result.facts);
  });

  it("never expands Compact V7 defaults in the browser", () => {
    const request = v13Request({
      expanded_known_events: null,
      known_events_expansion_status: "unavailable",
    });

    expect(extractV2ModelInputFactResult(request)).toEqual({
      facts: [],
      modelContextSchemaVersion: 13,
      status: "unsupported_model_context_contract",
    });
  });

  it("treats V11 and V12 as unsupported current-only contracts", () => {
    for (const [schemaVersion, promptVersion, knownEventsVersion] of [
      [11, 4, 5],
      [12, 5, 6],
    ] as const) {
      const result = extractV2ModelInputFactResult(
        legacyRequest(schemaVersion, promptVersion, knownEventsVersion),
      );
      expect(result).toMatchObject({
        facts: [],
        modelContextSchemaVersion: schemaVersion,
        status: "unsupported_model_context_contract",
      });
    }
  });

  it("fails closed for hybrid outer, projection, and inner contracts", () => {
    const base = v13Request();
    const cases = [
      {
        ...base,
        model_context_schema_version: 12,
      },
      {
        ...base,
        prompt_projection: {
          ...base.prompt_projection,
          model_view_selector_version: 2,
        },
      },
      {
        ...base,
        request_payload: requestPayload({
          model_context_schema_version: 12,
          prompt_template_version: 6,
          known_events: compactKnownEvents(7),
        }),
      },
    ];

    for (const request of cases) {
      expect(extractV2ModelInputFactResult(request).status).toBe(
        "unsupported_model_context_contract",
      );
    }
  });

  it("reports unavailable when there is no persisted structured prompt", () => {
    const request = v13Request({
      request_payload: {
        input: [{ role: "user", content: "普通文本" }],
      },
    });

    expect(extractV2ModelInputFactResult(request)).toEqual({
      facts: [],
      modelContextSchemaVersion: 13,
      status: "unavailable",
    });
  });
});

function v13Request(overrides: Record<string, unknown> = {}) {
  const prompt = {
    model_context_schema_version: 13,
    prompt_template_version: 6,
    known_events: compactKnownEvents(7),
  };
  return {
    expanded_known_events: {
      schema_version: 5,
      events: [
        {
          authority: "judge_fact",
          event_ref: "451",
          kind: "vote_result",
          known_at_seq: 451,
          totals: { seat_2: 3, seat_7: 1 },
          visibility: "public",
        },
        {
          authority: "player_claim_unverified",
          event_ref: "472",
          kind: "player_statement",
          known_at_seq: 472,
          speaker_ref: "seat_6",
          speech: "只能消费后端已验证展开的入选事件。",
          visibility: "public",
        },
      ],
      questions: [],
      relations: [],
    },
    known_events_expansion_status: "verified" as const,
    prompt_schema_version: 13,
    model_context_schema_version: 13,
    model_view_selector_version: 3,
    prompt_projection: currentProjection(),
    prompt_template_version: 6,
    request_payload: requestPayload(prompt),
    ...overrides,
  };
}

function legacyRequest(
  schemaVersion: number,
  promptVersion: number,
  knownEventsVersion: number,
) {
  return {
    expanded_known_events: null,
    known_events_expansion_status: "invalid" as const,
    prompt_schema_version: schemaVersion,
    model_context_schema_version: schemaVersion,
    model_view_selector_version: 2,
    prompt_projection: {
      known_events_schema_version: knownEventsVersion,
      ledger_schema_version: 5,
      model_context_schema_version: schemaVersion,
      model_view_schema_version: 5,
      model_view_selector_version: 2,
      prompt_template_version: promptVersion,
    },
    prompt_template_version: promptVersion,
    request_payload: requestPayload({
      model_context_schema_version: schemaVersion,
      prompt_template_version: promptVersion,
      known_events: compactKnownEvents(knownEventsVersion),
    }),
  };
}

function currentProjection() {
  return {
    known_events_schema_version: 7,
    ledger_schema_version: 5,
    model_context_schema_version: 13,
    model_view_schema_version: 5,
    model_view_selector_version: 3,
    prompt_template_version: 6,
    retained_event_refs: ["451", "472"],
    selector: {
      version: 3 as const,
      source_count: 3,
      retained_count: 2,
      omitted_count: 1,
      future_filtered_count: 0,
      retained: [
        { event_ref: "451", category: "vote_result", reason: "critical_fact" },
        { event_ref: "472", category: "player_statement", reason: "recent_speech" },
      ],
      omitted: [
        { event_ref: "401", category: "player_statement", reason: "superseded" },
      ],
      future_filtered: [],
      latest_actor_memory_ref: "fact:memory-2",
      latest_actor_memory_cutoff_seq: 440,
      latest_actor_memory_hash: "a".repeat(64),
      source_type_counts: { player_statement: 2, vote_result: 1 },
      retained_type_counts: { player_statement: 1, vote_result: 1 },
      omitted_type_counts: { player_statement: 1 },
    },
  };
}

function compactKnownEvents(schemaVersion: number) {
  return {
    schema_version: schemaVersion,
    encoding: "lossless_refs_v1",
    defaults: {},
    scope_catalog: {},
    occurrence_catalog: {},
    events: [],
    annotations: [],
    questions: [],
    relations: [],
  };
}

function requestPayload(prompt: Record<string, unknown>) {
  return {
    input: [
      {
        content: [
          {
            text: `请执行这个实时动作：${JSON.stringify(prompt)}`,
            type: "input_text",
          },
        ],
        role: "user",
      },
    ],
  };
}
