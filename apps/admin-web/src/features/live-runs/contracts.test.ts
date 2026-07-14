import {
  getAdminLiveRun,
  getAdminLiveRunDebug,
  listAdminLiveRuns,
} from "@/features/live-runs/api";
import { liveRunListParamsFromSearch } from "@/features/live-runs/list-state";
import {
  parseAdminLiveRunDebug,
  parseAdminLiveRunDetail,
  parseAdminLiveRunList,
} from "@/features/live-runs/parsers";
import {
  liveRunDetailRefreshInterval,
  liveRunListRefreshInterval,
} from "@/features/live-runs/presentation";
import {
  contractActiveLiveRunDetail,
  contractActiveLiveRunItem,
  contractLiveRunDebug,
  contractLiveRunDetail,
  contractLiveRunItem,
} from "@/features/live-runs/test-fixtures";

describe("admin live runs contract", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("strictly parses list, detail and independent debug DTOs", () => {
    expect(
      parseAdminLiveRunList({
        items: [contractLiveRunItem],
        pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
      }),
    ).toEqual({
      items: [contractLiveRunItem],
      pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
    });
    expect(parseAdminLiveRunDetail(contractLiveRunDetail)).toEqual(
      contractLiveRunDetail,
    );
    expect(parseAdminLiveRunDebug(contractLiveRunDebug)).toEqual(
      contractLiveRunDebug,
    );
    expect(parseAdminLiveRunDetail(contractActiveLiveRunDetail)).toEqual(
      contractActiveLiveRunDetail,
    );
  });

  it.each([
    ["payload", { payload: {} }],
    ["player_configs", { player_configs: [] }],
    ["lineup_quality_warnings", { lineup_quality_warnings: [] }],
    ["raw_error", { raw_error: "private" }],
    ["prompt", { prompt: "private" }],
    ["token", { token: "private" }],
    ["api_key", { api_key: "private" }],
    ["authorization", { authorization: "Bearer private" }],
    ["request_id", { request_id: "private-request" }],
    ["text", { text: "private voice content" }],
    ["subtitle_timings", { subtitle_timings: [] }],
    ["audio_chunks", { audio_chunks: [] }],
  ])("rejects nested sensitive key %s", (_name, leaked) => {
    expect(() =>
      parseAdminLiveRunDetail({
        ...contractLiveRunDetail,
        recent_events: [
          { ...contractLiveRunDetail.recent_events[0], metadata: leaked },
        ],
      }),
    ).toThrow(/不允许/);
  });

  it("rejects inline debug, unsafe active events and terminal-only fields", () => {
    expect(() =>
      parseAdminLiveRunDetail({
        ...contractLiveRunDetail,
        run_error: "private",
      }),
    ).toThrow(/run_error/);
    expect(() =>
      parseAdminLiveRunDetail({
        ...contractActiveLiveRunDetail,
        recent_events: [
          { ...contractActiveLiveRunDetail.recent_events[0], actor: "狼人" },
        ],
      }),
    ).toThrow(/actor\/action/);
    expect(() =>
      parseAdminLiveRunDetail({
        ...contractActiveLiveRunDetail,
        recent_events: [
          { ...contractActiveLiveRunDetail.recent_events[0], type: "werewolf_kill" },
        ],
      }),
    ).toThrow(/未归类/);
    expect(() =>
      parseAdminLiveRunList({
        items: [{ ...contractActiveLiveRunItem, winner: "狼人阵营" }],
        pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
      }),
    ).toThrow(/胜方/);
    expect(() =>
      parseAdminLiveRunList({
        items: [
          { ...contractActiveLiveRunItem, villager_model: "private-model" },
        ],
        pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
      }),
    ).toThrow(/模型/);
  });

  it("accepts explicit P2 empty states and rejects private diagnostic fields", () => {
    for (const dataStatus of ["legacy", "unavailable"] as const) {
      expect(
        parseAdminLiveRunDetail({
          ...contractLiveRunDetail,
          p2_diagnostics: {
            ...contractLiveRunDetail.p2_diagnostics,
            data_status: dataStatus,
          },
        }).p2_diagnostics.data_status,
      ).toBe(dataStatus);
    }
    expect(() =>
      parseAdminLiveRunDetail({
        ...contractLiveRunDetail,
        p2_diagnostics: {
          ...contractLiveRunDetail.p2_diagnostics,
          raw_choice: "private-seat-sentinel",
        },
      }),
    ).toThrow(/不允许/);
  });

  it("enforces stale, voice totals, event caps and debug truncation invariants", () => {
    expect(() =>
      parseAdminLiveRunList({
        items: [{ ...contractLiveRunItem, is_stale: true }],
        pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
      }),
    ).toThrow(/失联/);
    expect(() =>
      parseAdminLiveRunList({
        items: [
          {
            ...contractLiveRunItem,
            voice_counts: { ...contractLiveRunItem.voice_counts, total: 99 },
          },
        ],
        pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
      }),
    ).toThrow(/分类之和/);
    expect(() =>
      parseAdminLiveRunDetail({
        ...contractLiveRunDetail,
        recent_events: Array.from({ length: 51 }, (_, index) => ({
          ...contractLiveRunDetail.recent_events[0],
          event_id: index + 1,
        })),
      }),
    ).toThrow(/50/);
    expect(() =>
      parseAdminLiveRunDebug({ ...contractLiveRunDebug, truncated: true }),
    ).toThrow(/truncated/);
  });

  it("serializes signed sorting, local-day UTC bounds and list filters", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        items: [contractLiveRunItem],
        pagination: { page: 2, page_size: 10, total: 11, pages: 2 },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await listAdminLiveRuns({
      page: 2,
      page_size: 10,
      q: "run_1234",
      status: "failed",
      rule_set_id: "classic_8",
      created_from: "2026-07-01",
      created_to: "2026-07-10",
      sort: "updated_at",
      direction: "desc",
    });

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const parsed = new URL(url, "https://admin.test");
    expect(parsed.pathname).toBe("/api/v1/admin/live-runs");
    expect(Object.fromEntries(parsed.searchParams)).toEqual({
      page: "2",
      page_size: "10",
      sort: "-updated_at",
      q: "run_1234",
      status: "failed",
      rule_set_id: "classic_8",
      created_from: new Date(2026, 6, 1, 0, 0, 0, 0).toISOString(),
      created_to: new Date(2026, 6, 10, 23, 59, 59, 999).toISOString(),
    });
    expect(options.credentials).toBe("include");
  });

  it("uses encoded detail/debug endpoints and active-only refresh intervals", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(contractLiveRunDetail))
      .mockResolvedValueOnce(jsonResponse(contractLiveRunDebug));
    vi.stubGlobal("fetch", fetchMock);

    await getAdminLiveRun("run/unsafe");
    await getAdminLiveRunDebug("run/unsafe");

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "/api/v1/admin/live-runs/run%2Funsafe",
    );
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe(
      "/api/v1/admin/live-runs/run%2Funsafe/debug",
    );
    expect(
      liveRunListRefreshInterval({
        items: [contractActiveLiveRunItem],
        pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
      }),
    ).toBe(5_000);
    expect(
      liveRunListRefreshInterval(
        {
          items: [contractActiveLiveRunItem],
          pagination: { page: 2, page_size: 20, total: 21, pages: 2 },
        },
        2,
      ),
    ).toBe(false);
    expect(
      liveRunListRefreshInterval({
        items: [contractLiveRunItem],
        pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
      }),
    ).toBe(30_000);
    expect(
      liveRunListRefreshInterval({
        items: [],
        pagination: { page: 1, page_size: 20, total: 0, pages: 0 },
      }),
    ).toBe(30_000);
    expect(liveRunDetailRefreshInterval("running")).toBe(5_000);
    expect(liveRunDetailRefreshInterval("failed")).toBe(false);
  });

  it("normalizes invalid URL state and defaults to updated time descending", () => {
    expect(
      liveRunListParamsFromSearch(
        new URLSearchParams(
          "page=-1&page_size=100&status=stopped&sort=secret&created_from=2026-02-30&created_to=2026-07-10",
        ),
      ),
    ).toEqual({
      page: 1,
      page_size: 20,
      q: undefined,
      status: undefined,
      rule_set_id: undefined,
      created_from: undefined,
      created_to: "2026-07-10",
      sort: "updated_at",
      direction: "desc",
    });
  });
});

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
    status: 200,
  });
}
