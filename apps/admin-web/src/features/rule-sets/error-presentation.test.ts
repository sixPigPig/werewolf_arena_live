import { describe, expect, it } from "vitest";
import { AdminApiError } from "@/api/problem-details";
import { presentRuleSetError, type RuleSetErrorContext } from "./error-presentation";

describe("rule-set bounded errors", () => {
  it.each(["options", "list", "duplicate", "load", "save", "validate", "reload", "transition"] satisfies RuleSetErrorContext[])("never exposes raw server text in %s", (context) => {
    const error = new AdminApiError({ problem: { type: "about:blank", title: "driver failure", status: 500, detail: "SELECT * FROM players WHERE secret='raw-player'", code: "driver_raw", request_id: null } });
    const result = presentRuleSetError(error, context); expect(result).not.toMatch(/SELECT|players|raw-player|driver/i); expect(result.length).toBeGreaterThan(0);
  });
});
