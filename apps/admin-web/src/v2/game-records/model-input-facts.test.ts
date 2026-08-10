import { describe, expect, it } from "vitest";

import {
  extractV2ModelInputFactResult,
  extractV2ModelInputFacts,
} from "@/v2/game-records/model-input-facts";

describe("extractV2ModelInputFacts", () => {
  it("reads only V11 canonical Known Events V5 in source order", () => {
    const request = modelRequest({
      model_context_schema_version: 11,
      prompt_template_version: 4,
      known_events: {
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
            speech: "6号上警，我先听后置位怎么说。",
            visibility: "public",
          },
        ],
        questions: [],
        relations: [],
        schema_version: 5,
      },
    });

    const result = extractV2ModelInputFactResult(request);

    expect(result.status).toBe("supported");
    expect(result.modelContextSchemaVersion).toBe(11);
    expect(result.facts.map((fact) => [fact.id, fact.recordSeq])).toEqual([
      ["451", 451],
      ["472", 472],
    ]);
    expect(result.facts[1].summary).toBe("6号上警，我先听后置位怎么说。");
    expect(extractV2ModelInputFacts(request)).toEqual(result.facts);
  });

  it("uses only backend-verified V12 expansion and never guesses Compact defaults", () => {
    const request = modelRequest(
      {
        model_context_schema_version: 12,
        prompt_template_version: 5,
        known_events: {
          schema_version: 6,
          encoding: "lossless_refs_v1",
          defaults: {
            record_seq: "known_at_seq",
            event_ref: "record_seq_string_when_equal",
            scope_ref_by_kind: {
              player_statement: "public_player_claim_unverified",
            },
          },
          scope_catalog: {
            public_player_claim_unverified: {
              authority: "player_claim_unverified",
              visibility: "public",
            },
          },
          occurrence_catalog: {},
          events: [
            {
              known_at_seq: 472,
              kind: "player_statement",
              speech: "不能由 Admin 自行补全 event_ref、record_seq 或 authority。",
            },
          ],
          annotations: [],
          questions: [],
          relations: [],
        },
      },
      {
        model_context_schema_version: 12,
        prompt_template_version: 5,
        prompt_projection: exactProjection(12, 5, 6),
      },
    );

    const result = extractV2ModelInputFactResult(request);

    expect(result).toEqual({
      facts: [],
      modelContextSchemaVersion: 12,
      status: "unsupported_model_context_contract",
    });

    const verified = extractV2ModelInputFactResult({
      ...request,
      known_events_expansion_status: "verified",
      expanded_known_events: {
        schema_version: 5,
        events: [
          {
            event_ref: "472",
            record_seq: 472,
            known_at_seq: 472,
            kind: "player_statement",
            authority: "player_claim_unverified",
            visibility: "public",
            speech: "只能消费后端已验证展开的 Canonical 事件。",
          },
        ],
        questions: [],
        relations: [],
      },
    });
    expect(verified.status).toBe("supported");
    expect(verified.facts).toMatchObject([
      {
        authority: "player_claim_unverified",
        id: "472",
        recordSeq: 472,
        summary: "只能消费后端已验证展开的 Canonical 事件。",
      },
    ]);

    for (const expansionStatus of ["unavailable", "invalid"] as const) {
      expect(
        extractV2ModelInputFactResult({
          ...request,
          known_events_expansion_status: expansionStatus,
          expanded_known_events: {
            schema_version: 5,
            events: [],
            questions: [],
            relations: [],
          },
        }).facts,
      ).toEqual([]);
    }
  });

  it("does not infer facts from historical or unknown contracts", () => {
    for (const modelContextSchemaVersion of [8, 99]) {
      const result = extractV2ModelInputFactResult(
        modelRequest(
          {
            model_context_schema_version: modelContextSchemaVersion,
            known_events: {
              schema_version: 5,
              events: [
                {
                  authority: "judge_fact",
                  event_ref: "12",
                  kind: "night_result",
                  known_at_seq: 12,
                },
              ],
            },
          },
          {
            model_context_schema_version: modelContextSchemaVersion,
            prompt_projection: null,
            prompt_template_version: null,
          },
        ),
      );
      expect(result.facts).toEqual([]);
      expect(result.status).toBe("unsupported_model_context_contract");
      expect(result.modelContextSchemaVersion).toBe(modelContextSchemaVersion);
    }
  });

  it("fails closed when an outer unknown or V12 contract contains a residual V11 prompt", () => {
    const innerV11 = {
      model_context_schema_version: 11,
      prompt_template_version: 4,
      known_events: {
        schema_version: 5,
        events: [
          {
            authority: "judge_fact",
            event_ref: "12",
            kind: "night_result",
            known_at_seq: 12,
            visibility: "public",
          },
        ],
        questions: [],
        relations: [],
      },
    };
    const outerUnknown = modelRequest(innerV11, {
      model_context_schema_version: 99,
      prompt_projection: null,
      prompt_template_version: 4,
    });
    const outerV12 = modelRequest(innerV11, {
      expanded_known_events: {
        schema_version: 5,
        events: [],
        questions: [],
        relations: [],
      },
      known_events_expansion_status: "verified",
      model_context_schema_version: 12,
      prompt_projection: exactProjection(12, 5, 6),
      prompt_template_version: 5,
    });

    expect(extractV2ModelInputFactResult(outerUnknown)).toMatchObject({
      facts: [],
      modelContextSchemaVersion: 99,
      status: "unsupported_model_context_contract",
    });
    expect(extractV2ModelInputFactResult(outerV12)).toMatchObject({
      facts: [],
      modelContextSchemaVersion: 12,
      status: "unsupported_model_context_contract",
    });
  });

  it("reports unavailable when there is no persisted structured prompt", () => {
    expect(
      extractV2ModelInputFactResult(
        modelRequest(
          {},
          {
            request_payload: {
              input: [{ role: "user", content: "普通文本" }],
            },
          },
        ),
      ),
    ).toEqual({
      facts: [],
      modelContextSchemaVersion: 11,
      status: "unavailable",
    });
  });
});

function modelRequest(
  prompt: Record<string, unknown>,
  overrides: Record<string, unknown> = {},
) {
  const promptTemplateVersion =
    typeof prompt.prompt_template_version === "number"
      ? prompt.prompt_template_version
      : 4;
  return {
    expanded_known_events: null,
    known_events_expansion_status: "not_applicable" as const,
    model_context_schema_version: 11,
    model_view_selector_version: 2,
    prompt_projection: exactProjection(11, promptTemplateVersion, 5),
    prompt_template_version: promptTemplateVersion,
    request_payload: requestPayload(prompt),
    ...overrides,
  };
}

function exactProjection(
  modelContextSchemaVersion: number,
  promptTemplateVersion: number,
  knownEventsSchemaVersion: number,
) {
  return {
    known_events_schema_version: knownEventsSchemaVersion,
    ledger_schema_version: 5,
    model_context_schema_version: modelContextSchemaVersion,
    model_view_schema_version: 5,
    model_view_selector_version: 2,
    prompt_template_version: promptTemplateVersion,
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
