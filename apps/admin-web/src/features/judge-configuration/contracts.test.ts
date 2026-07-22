import {
  getAdminJudgeConfiguration,
  updateAdminJudgeConfiguration,
} from "@/features/judge-configuration/api";
import { parseAdminJudgeConfiguration } from "@/features/judge-configuration/parsers";
import { previewJudgeConfiguration } from "@/features/judge-configuration/preview";

describe("admin judge configuration contract", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("strictly parses the two-field configuration and options", () => {
    expect(parseAdminJudgeConfiguration(previewJudgeConfiguration)).toEqual(
      previewJudgeConfiguration,
    );
    expect(() =>
      parseAdminJudgeConfiguration({
        ...previewJudgeConfiguration,
        model_provider: "deepseek",
      }),
    ).toThrow(/模型来源/);
  });

  it("uses the bounded GET and PATCH endpoints", async () => {
    const fetchMock = vi.fn<typeof fetch>(async (_input, init) =>
      new Response(JSON.stringify(previewJudgeConfiguration), {
        status: init?.method === "PATCH" ? 200 : 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await getAdminJudgeConfiguration();
    await updateAdminJudgeConfiguration(
      {
        model_provider: "agent_plan",
        model_id: "glm-5-2-260617",
        tts_speaker: "zh_female_vv_uranus_bigtts",
        expected_version: 1,
      },
      "csrf-judge",
    );

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "/api/v1/admin/judge-configuration",
    );
    const patch = fetchMock.mock.calls[1];
    expect(String(patch?.[0])).toBe("/api/v1/admin/judge-configuration");
    expect(patch?.[1]?.method).toBe("PATCH");
    expect(new Headers(patch?.[1]?.headers).get("X-CSRF-Token")).toBe(
      "csrf-judge",
    );
    expect(JSON.parse(String(patch?.[1]?.body))).toEqual({
      model_provider: "agent_plan",
      model_id: "glm-5-2-260617",
      tts_speaker: "zh_female_vv_uranus_bigtts",
      expected_version: 1,
    });
  });
});
