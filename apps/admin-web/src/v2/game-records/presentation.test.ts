import { describe, expect, it } from "vitest";

import { actionLabel } from "@/v2/game-records/presentation";

describe("V2 game record presentation", () => {
  it("distinguishes the sheriff signup decision from the campaign speech", () => {
    expect(actionLabel("sheriff_run")).toBe("上警决定");
    expect(actionLabel("sheriff_campaign_speech")).toBe("竞选发言");
  });
});
