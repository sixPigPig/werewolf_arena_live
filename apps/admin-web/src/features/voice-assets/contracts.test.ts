import { listAdminJudgeVoiceLines } from "@/features/voice-assets/api";
import {
  judgeVoiceListParamsFromSearch,
  setJudgeVoiceSearchValues,
} from "@/features/voice-assets/list-state";
import { parseAdminJudgeVoiceList } from "@/features/voice-assets/parsers";
import { contractJudgeVoiceList } from "@/features/voice-assets/test-fixtures";

describe("admin judge voice asset contract", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("strictly parses a safe inventory DTO", () => {
    expect(parseAdminJudgeVoiceList(contractJudgeVoiceList)).toEqual(
      contractJudgeVoiceList,
    );
  });

  it.each([
    ["filename", { filename: "private.mp3" }],
    ["public_url", { public_url: "/judge-voice/private.mp3" }],
    ["manifest_path", { manifest_path: "/private/manifest.json" }],
    ["subtitle_timings", { subtitle_timings: [] }],
    ["audio", { audio: "base64" }],
    ["audio_chunks", { audio_chunks: [] }],
    ["request_id", { request_id: "private" }],
    ["error_message", { error_message: "private" }],
  ])("rejects forbidden nested key %s", (_key, leaked) => {
    expect(() =>
      parseAdminJudgeVoiceList({
        ...contractJudgeVoiceList,
        items: [{ ...contractJudgeVoiceList.items[0], metadata: leaked }],
      }),
    ).toThrow(/不允许/);
  });

  it("enforces coverage, category and authenticated audio URL invariants", () => {
    expect(() =>
      parseAdminJudgeVoiceList({
        ...contractJudgeVoiceList,
        coverage: { ...contractJudgeVoiceList.coverage, total: 5 },
      }),
    ).toThrow(/分类之和/);
    expect(() =>
      parseAdminJudgeVoiceList({
        ...contractJudgeVoiceList,
        categories: [
          { ...contractJudgeVoiceList.categories[0], total: 2 },
          contractJudgeVoiceList.categories[1],
        ],
      }),
    ).toThrow(/覆盖率/);
    expect(() =>
      parseAdminJudgeVoiceList({
        ...contractJudgeVoiceList,
        items: [
          { ...contractJudgeVoiceList.items[0], audio_url: "/judge-voice/game_intro.mp3" },
        ],
      }),
    ).toThrow(/安全试听地址/);
    expect(() =>
      parseAdminJudgeVoiceList({
        ...contractJudgeVoiceList,
        items: [
          {
            ...contractJudgeVoiceList.items[2],
            byte_size: 10,
            audio_url: "/api/v1/admin/judge-voice-lines/night_start/audio",
          },
        ],
      }),
    ).toThrow(/缺失语音/);
  });

  it("serializes pagination, filters and signed sorting", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(contractJudgeVoiceList));
    vi.stubGlobal("fetch", fetchMock);
    await listAdminJudgeVoiceLines({
      page: 2,
      page_size: 50,
      q: "night",
      category: "夜晚",
      availability: "missing",
      sort: "byte_size",
      direction: "desc",
    });
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const parsed = new URL(url, "https://admin.test");
    expect(parsed.pathname).toBe("/api/v1/admin/judge-voice-lines");
    expect(Object.fromEntries(parsed.searchParams)).toEqual({
      page: "2",
      page_size: "50",
      sort: "-byte_size",
      q: "night",
      category: "夜晚",
      availability: "missing",
    });
    expect(options.credentials).toBe("include");
  });

  it("normalizes URL state and preserves unrelated values", () => {
    expect(
      judgeVoiceListParamsFromSearch(
        new URLSearchParams(
          "page=2&page_size=100&q=night&category=%E5%A4%9C%E6%99%9A&availability=missing&sort=id&direction=desc",
        ),
      ),
    ).toEqual({
      page: 2,
      page_size: 100,
      q: "night",
      category: "夜晚",
      availability: "missing",
      sort: "id",
      direction: "desc",
    });
    const next = setJudgeVoiceSearchValues(
      new URLSearchParams("keep=yes&q=old"),
      { q: undefined, availability: "available" },
    );
    expect(next.get("keep")).toBe("yes");
    expect(next.has("q")).toBe(false);
    expect(next.get("availability")).toBe("available");
  });
});

function jsonResponse(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
