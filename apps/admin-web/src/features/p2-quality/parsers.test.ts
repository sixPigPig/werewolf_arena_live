import { describe, expect, it } from "vitest";

import { contractLiveRunDetail } from "@/features/live-runs/test-fixtures";
import { parseAdminRunP2Diagnostics } from "@/features/p2-quality/parsers";

describe("P2 quality parsers", () => {
  it("keeps newly added outcome distributions absent for schema v1 legacy payloads", () => {
    const legacyPayload: Record<string, unknown> = {
      ...contractLiveRunDetail.p2_diagnostics,
    };
    delete legacyPayload.provider_attempt_outcomes;
    delete legacyPayload.logical_action_outcomes;

    const parsed = parseAdminRunP2Diagnostics(legacyPayload);

    expect(parsed.provider_attempt_outcomes).toBeNull();
    expect(parsed.logical_action_outcomes).toBeNull();
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
          ...contractLiveRunDetail.p2_diagnostics.provider_attempt_outcomes!,
          attempt_count: 99,
        },
      }),
    ).toThrow(/各 attempt 终态之和/);

    expect(() =>
      parseAdminRunP2Diagnostics({
        ...contractLiveRunDetail.p2_diagnostics,
        logical_action_outcomes: {
          ...contractLiveRunDetail.p2_diagnostics.logical_action_outcomes!,
          action_count: 99,
        },
      }),
    ).toThrow(/各 logical action 终态之和/);

    expect(() =>
      parseAdminRunP2Diagnostics({
        ...contractLiveRunDetail.p2_diagnostics,
        provider_attempt_outcomes: {
          ...contractLiveRunDetail.p2_diagnostics.provider_attempt_outcomes!,
          canceled_count: -1,
        },
      }),
    ).toThrow(/不是非负整数/);
  });
});
