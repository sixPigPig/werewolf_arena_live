import { describe, expect, it } from "vitest";

import {
  parseAdminModelCatalog,
  parseVolcLoginChallenge,
} from "@/features/models/parsers";
import { previewModelCatalog } from "@/features/models/preview";

function catalogPayload(): Record<string, unknown> {
  return structuredClone(previewModelCatalog) as unknown as Record<string, unknown>;
}

function firstModel(payload: Record<string, unknown>): Record<string, unknown> {
  return (payload.models as Array<Record<string, unknown>>)[0];
}

describe("admin model catalog parser", () => {
  it("parses the full reasoning linkage contract", () => {
    const parsed = parseAdminModelCatalog(catalogPayload());
    const doubao = parsed.models.find(
      (model) => model.model_id === "doubao-seed-2-0-lite-260215",
    );

    expect(doubao?.parameters).toMatchObject({
      thinking: "enabled",
      reasoning_effort: "low",
      max_tokens_mode: "auto",
      max_tokens: 4_096,
    });
    expect(doubao?.reasoning_policy.max_tokens_by_effort).toEqual({
      low: 4_096,
      medium: 8_192,
      high: 16_384,
    });
  });

  it("mirrors glm-5-3 forced-thinking policy", () => {
    const parsed = parseAdminModelCatalog(catalogPayload());
    const glm53 = parsed.models.find((model) => model.model_id === "glm-5-3-flash");

    expect(glm53?.parameters).toMatchObject({
      thinking: "enabled",
      reasoning_effort: "low",
      max_tokens_mode: "auto",
      max_tokens: 4_096,
    });
    expect(glm53?.reasoning_policy).toMatchObject({
      thinking_options: ["enabled"],
      thinking_locked: true,
      reasoning_effort_options: ["low", "high", "max"],
      default_reasoning_effort: "low",
      disabled_max_tokens: null,
    });
  });

  it.each([
    "reasoning_effort",
    "temperature",
    "top_p",
    "frequency_penalty",
    "presence_penalty",
  ])("rejects a missing nullable parameter field: %s", (field) => {
    const payload = catalogPayload();
    const parameters = firstModel(payload).parameters as Record<string, unknown>;
    delete parameters[field];

    expect(() => parseAdminModelCatalog(payload)).toThrow(`Invalid ${field}`);
  });

  it("rejects legacy source enum fallbacks", () => {
    const payload = catalogPayload();
    const source = (payload.sources as Array<Record<string, unknown>>)[0];
    source.refresh_mode = "provider_default";

    expect(() => parseAdminModelCatalog(payload)).toThrow("Invalid refresh mode");
  });

  it("rejects fractional token linkage values", () => {
    const payload = catalogPayload();
    const parameters = firstModel(payload).parameters as Record<string, unknown>;
    parameters.max_tokens = 512.5;

    expect(() => parseAdminModelCatalog(payload)).toThrow("Invalid max_tokens");
  });

  it("rejects a fractional model output limit", () => {
    const payload = catalogPayload();
    firstModel(payload).max_output_tokens_limit = 8_192.5;

    expect(() => parseAdminModelCatalog(payload)).toThrow(
      "Invalid max_output_tokens_limit",
    );
  });

  it("requires the model-level sampling capability", () => {
    const payload = catalogPayload();
    const policy = firstModel(payload).reasoning_policy as Record<string, unknown>;
    delete policy.sampling_parameters_allowed_when_thinking;

    expect(() => parseAdminModelCatalog(payload)).toThrow(
      "Invalid sampling_parameters_allowed_when_thinking",
    );
  });
});

describe("volc login challenge parser", () => {
  it("parses a pending authorize URL", () => {
    expect(
      parseVolcLoginChallenge({
        authorize_url: "https://signin.volcengine.com/authorize/oauth/authorize?x=1",
        expires_in_sec: 600,
        already_authenticated: false,
      }),
    ).toEqual({
      authorize_url: "https://signin.volcengine.com/authorize/oauth/authorize?x=1",
      expires_in_sec: 600,
      already_authenticated: false,
    });
  });

  it("allows a null URL when already authenticated", () => {
    expect(
      parseVolcLoginChallenge({
        authorize_url: null,
        expires_in_sec: null,
        already_authenticated: true,
      }),
    ).toEqual({
      authorize_url: null,
      expires_in_sec: null,
      already_authenticated: true,
    });
  });
});
