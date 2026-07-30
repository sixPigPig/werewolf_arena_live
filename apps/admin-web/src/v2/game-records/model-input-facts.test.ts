import { describe, expect, it } from "vitest";

import { extractV2ModelInputFacts } from "@/v2/game-records/model-input-facts";

describe("extractV2ModelInputFacts", () => {
  it("lists every persisted public timeline fact in source order", () => {
    const facts = extractV2ModelInputFacts(
      requestPayload({
        history: {
          timeline: [
            {
              record_seq: 448,
              source_event_id: "448",
              speaker_ref: "seat_6",
              speech: "这段完整发言仅保留在模型请求中。",
              statement_id: "statement_448",
            },
          ],
        },
        public_timeline: {
          events: [
            {
              authority: "player_claim_unverified",
              kind: "player_statement",
              occurred_in: { period: "day", round_no: 1 },
              record_seq: 448,
              source_event_id: "448",
              speaker_ref: "seat_6",
              statement_ref: "448",
            },
            {
              action_type: "sheriff_vote",
              authority: "judge_fact",
              kind: "day_vote",
              record_seq: 562,
              source_event_id: "562",
              target_ref: "seat_7",
              voter_ref: "seat_2",
              weight: 1,
            },
            {
              action_type: "sheriff_vote",
              authority: "judge_fact",
              kind: "day_vote",
              record_seq: 564,
              source_event_id: "564",
              target_ref: "seat_7",
              voter_ref: "seat_5",
              weight: 1,
            },
          ],
        },
      }),
    );

    expect(facts).toHaveLength(3);
    expect(facts.map((fact) => fact.recordSeq)).toEqual([448, 562, 564]);
    expect(facts[0].summary).toBeNull();
    expect(JSON.stringify(facts)).not.toContain(
      "这段完整发言仅保留在模型请求中。",
    );
    expect(facts[1].summary).toBe("2号投给7号 · 警长投票");
    expect(facts[2].summary).toBe("5号投给7号 · 警长投票");
  });

  it("falls back to the complete history timeline for older prompts", () => {
    const facts = extractV2ModelInputFacts(
      requestPayload({
        history: {
          timeline: [
            {
              record_seq: 12,
              source_event_id: "12",
              speaker_ref: "seat_3",
              speech: "旧版请求中的完整发言。",
            },
            {
              record_seq: 18,
              source_event_id: "18",
              speaker_ref: "seat_4",
              speech: "第二条旧版完整发言。",
            },
          ],
        },
      }),
    );

    expect(facts).toHaveLength(2);
    expect(facts[0].summary).toBeNull();
    expect(facts[1].summary).toBeNull();
    expect(JSON.stringify(facts)).not.toContain("旧版请求中的完整发言");
  });

  it("does not infer facts when the persisted request has no structured prompt", () => {
    expect(
      extractV2ModelInputFacts({
        input: [{ role: "user", content: "普通文本" }],
      }),
    ).toEqual([]);
  });
});

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
