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

  it("strictly parses the voice-only configuration and options", () => {
    expect(parseAdminJudgeConfiguration(previewJudgeConfiguration)).toEqual(
      previewJudgeConfiguration,
    );
    expect(() =>
      parseAdminJudgeConfiguration({
        ...previewJudgeConfiguration,
        voice_mode: "per_sentence",
      }),
    ).toThrow(/音色模式/);
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
        voice_mode: "random",
        tts_speaker: null,
        random_tts_speakers: [
          "zh_female_vv_uranus_bigtts",
          "zh_male_yangguangqingnian_uranus_bigtts",
        ],
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
      voice_mode: "random",
      tts_speaker: null,
      random_tts_speakers: [
        "zh_female_vv_uranus_bigtts",
        "zh_male_yangguangqingnian_uranus_bigtts",
      ],
      expected_version: 1,
    });
  });
});
