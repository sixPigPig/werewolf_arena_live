import { describe, expect, it } from "vitest";

import { contractLiveRunDetail } from "@/features/live-runs/test-fixtures";
import { parseAdminRunP2Diagnostics } from "@/features/p2-quality/parsers";

describe("P2 quality parsers", () => {
  it("defaults newly added outcome distributions for schema v1 legacy payloads", () => {
    const legacyPayload: Record<string, unknown> = {
      ...contractLiveRunDetail.p2_diagnostics,
    };
    delete legacyPayload.provider_attempt_outcomes;
    delete legacyPayload.logical_action_outcomes;

    const parsed = parseAdminRunP2Diagnostics(legacyPayload);

    expect(parsed.provider_attempt_outcomes).toEqual({
      attempt_count: 0,
      valid_response_count: 0,
      invalid_response_count: 0,
      timed_out_count: 0,
      canceled_count: 0,
      transport_failed_count: 0,
    });
    expect(parsed.logical_action_outcomes).toEqual({
      action_count: 0,
      completed_count: 0,
      fallback_count: 0,
      canceled_count: 0,
      failed_count: 0,
    });
  });

  it("parses bounded provider attempt and logical action outcomes separately", () => {
    const parsed = parseAdminRunP2Diagnostics(
      contractLiveRunDetail.p2_diagnostics,
    );

    expect(parsed.provider_attempt_outcomes).toEqual(
      contractLiveRunDetail.p2_diagnostics.provider_attempt_outcomes,
    );
    expect(parsed.logical_action_outcomes).toEqual(
      contractLiveRunDetail.p2_diagnostics.logical_action_outcomes,
    );
  });

  it("rejects negative counts and independently broken conservation equations", () => {
    expect(() =>
      parseAdminRunP2Diagnostics({
        ...contractLiveRunDetail.p2_diagnostics,
        provider_attempt_outcomes: {
          ...contractLiveRunDetail.p2_diagnostics.provider_attempt_outcomes,
          attempt_count: 99,
        },
      }),
    ).toThrow(/各 attempt 终态之和/);

    expect(() =>
      parseAdminRunP2Diagnostics({
        ...contractLiveRunDetail.p2_diagnostics,
        logical_action_outcomes: {
          ...contractLiveRunDetail.p2_diagnostics.logical_action_outcomes,
          action_count: 99,
        },
      }),
    ).toThrow(/各 logical action 终态之和/);

    expect(() =>
      parseAdminRunP2Diagnostics({
        ...contractLiveRunDetail.p2_diagnostics,
        provider_attempt_outcomes: {
          ...contractLiveRunDetail.p2_diagnostics.provider_attempt_outcomes,
          canceled_count: -1,
        },
      }),
    ).toThrow(/不是非负整数/);
  });
});
