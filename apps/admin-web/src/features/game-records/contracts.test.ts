import {
  getAdminGame,
  getAdminGameDebug,
  listAdminGames,
} from "@/features/game-records/api";
import { gameListParamsFromSearch } from "@/features/game-records/list-state";
import {
  parseAdminGameDebug,
  parseAdminGameDetail,
  parseAdminGameList,
} from "@/features/game-records/parsers";
import {
  contractGameDebug,
  contractGameDetail,
  contractGameItem,
} from "@/features/game-records/test-fixtures";

describe("admin game records contract", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("strictly parses list, detail and separate debug DTOs", () => {
    expect(
      parseAdminGameList({
        items: [contractGameItem],
        pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
      }),
    ).toEqual({
      items: [contractGameItem],
      pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
    });
    expect(parseAdminGameDetail(contractGameDetail)).toEqual(contractGameDetail);
    expect(parseAdminGameDebug(contractGameDebug)).toEqual(contractGameDebug);
  });

  it("accepts the redacted partial/resumable detail contract", () => {
    expect(
      parseAdminGameDetail({
        ...contractGameDetail,
        status: "partial",
        winner: null,
        resumable: true,
        latest_run: {
          ...contractGameDetail.latest_run,
          villager_model: null,
          werewolf_model: null,
        },
        rule_set: { ...contractGameDetail.rule_set, player_count: null },
        players: [
          { ...contractGameDetail.players[0], role: null, model: null },
        ],
        rounds: contractGameDetail.rounds.map((round) => ({
          ...round,
          night_deaths: round.night_deaths.map((death) => ({
            ...death,
            cause: null,
            source: null,
          })),
          day_deaths: round.day_deaths.map((death) => ({
            ...death,
            cause: null,
            source: null,
          })),
        })),
        recent_events: [],
        diagnostics: { ...contractGameDetail.diagnostics, last_event: null },
        runs: contractGameDetail.runs.map((run) => ({
          ...run,
          villager_model: null,
          werewolf_model: null,
        })),
      }),
    ).toMatchObject({
      status: "partial",
      winner: null,
      resumable: true,
      rule_set: { player_count: null },
      players: [{ role: null, model: null }],
      latest_run: { villager_model: null, werewolf_model: null },
      rounds: [{ night_deaths: [{ cause: null, source: null }] }],
      runs: [{ villager_model: null, werewolf_model: null }],
      recent_events: [],
      diagnostics: { last_event: null },
    });
  });

  it("rejects sensitive replay fields, inline debug and invalid statuses", () => {
    expect(() =>
      parseAdminGameDetail({ ...contractGameDetail, state: {} }),
    ).toThrow(/state/);
    expect(() =>
      parseAdminGameDetail({
        ...contractGameDetail,
        recent_events: [
          { ...contractGameDetail.recent_events[0], payload: { secret: true } },
        ],
      }),
    ).toThrow(/payload/);
    expect(() =>
      parseAdminGameDetail({ ...contractGameDetail, debug: null }),
    ).toThrow(/独立/);
    expect(() =>
      parseAdminGameList({
        items: [{ ...contractGameItem, status: "deleted" }],
        pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
      }),
    ).toThrow(/状态/);
    expect(() =>
      parseAdminGameList({
        items: [{ ...contractGameItem, status: "partial", winner: null }],
        pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
      }),
    ).toThrow(/最新运行模型/);
    expect(() =>
      parseAdminGameList({
        items: [
          {
            ...contractGameItem,
            status: "partial",
            latest_run: {
              ...contractGameItem.latest_run,
              villager_model: null,
              werewolf_model: null,
            },
          },
        ],
        pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
      }),
    ).toThrow(/胜方/);
  });

  it("validates P2 empty states, privacy and public outcome uniqueness", () => {
    for (const dataStatus of ["legacy", "unavailable"] as const) {
      expect(
        parseAdminGameDetail({
          ...contractGameDetail,
          p2_quality: {
            ...contractGameDetail.p2_quality,
            data_status: dataStatus,
          },
        }).p2_quality.data_status,
      ).toBe(dataStatus);
    }
    expect(() =>
      parseAdminGameDetail({
        ...contractGameDetail,
        p2_quality: {
          ...contractGameDetail.p2_quality,
          rejected_draft: "private-speech-sentinel",
        },
      }),
    ).toThrow(/不允许/);
    expect(() =>
      parseAdminGameDetail({
        ...contractGameDetail,
        p2_quality: {
          ...contractGameDetail.p2_quality,
          public_outcomes: [
            contractGameDetail.p2_quality.public_outcomes[0],
            contractGameDetail.p2_quality.public_outcomes[0],
          ],
        },
      }),
    ).toThrow(/重复 event_id/);
  });

  it("rejects sensitive partial detail fields if the server regresses", () => {
    const redacted = {
      ...contractGameDetail,
      status: "partial",
      winner: null,
      latest_run: {
        ...contractGameDetail.latest_run,
        villager_model: null,
        werewolf_model: null,
      },
      players: [
        { ...contractGameDetail.players[0], role: null, model: null },
      ],
      rounds: contractGameDetail.rounds.map((round) => ({
        ...round,
        night_deaths: round.night_deaths.map((death) => ({
          ...death,
          cause: null,
          source: null,
        })),
      })),
      recent_events: [],
      diagnostics: { ...contractGameDetail.diagnostics, last_event: null },
      runs: contractGameDetail.runs.map((run) => ({
        ...run,
        villager_model: null,
        werewolf_model: null,
      })),
    };
    expect(() =>
      parseAdminGameDetail({
        ...redacted,
        players: [{ ...redacted.players[0], model: "private-model" }],
      }),
    ).toThrow(/角色或模型/);
    expect(() =>
      parseAdminGameDetail({
        ...redacted,
        rounds: contractGameDetail.rounds.map((round) => ({
          ...round,
          night_deaths: round.night_deaths.map((death) => ({
            ...death,
            cause: "werewolf_attack",
          })),
        })),
      }),
    ).toThrow(/死亡原因/);
    expect(() =>
      parseAdminGameDetail({
        ...redacted,
        recent_events: contractGameDetail.recent_events,
      }),
    ).toThrow(/事件元数据/);
    expect(() =>
      parseAdminGameDetail({
        ...redacted,
        runs: contractGameDetail.runs,
      }),
    ).toThrow(/运行模型/);
    expect(() =>
      parseAdminGameDetail({
        ...redacted,
        rounds: [{ ...redacted.rounds[0], success: false }],
      }),
    ).toThrow(/未完成轮次/);
  });

  it("serializes signed sorting, local-day UTC bounds and all filters", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        items: [contractGameItem],
        pagination: { page: 2, page_size: 10, total: 11, pages: 2 },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await listAdminGames({
      page: 2,
      page_size: 10,
      q: "run_1234",
      status: "partial",
      run_status: "failed",
      winner: "狼人阵营",
      rule_set_id: "classic_8",
      created_from: "2026-07-01",
      created_to: "2026-07-10",
      sort: "updated_at",
      direction: "desc",
    });

    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    const parsed = new URL(url, "https://admin.test");
    expect(parsed.pathname).toBe("/api/v1/admin/games");
    expect(Object.fromEntries(parsed.searchParams)).toEqual({
      page: "2",
      page_size: "10",
      sort: "-updated_at",
      q: "run_1234",
      status: "partial",
      winner: "狼人阵营",
      rule_set_id: "classic_8",
      run_status: "failed",
      created_from: new Date(2026, 6, 1, 0, 0, 0, 0).toISOString(),
      created_to: new Date(2026, 6, 10, 23, 59, 59, 999).toISOString(),
    });
    expect(options.credentials).toBe("include");
  });

  it("uses independent encoded detail and debug endpoints", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(contractGameDetail))
      .mockResolvedValueOnce(jsonResponse(contractGameDebug));
    vi.stubGlobal("fetch", fetchMock);

    await getAdminGame("game/unsafe");
    await getAdminGameDebug("game/unsafe");

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "/api/v1/admin/games/game%2Funsafe",
    );
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe(
      "/api/v1/admin/games/game%2Funsafe/debug",
    );
  });

  it("normalizes invalid URL state without widening filters", () => {
    expect(
      gameListParamsFromSearch(
        new URLSearchParams(
          "page=-1&page_size=100&status=deleted&run_status=stopped&created_from=2026-02-30&created_to=2026-07-10",
        ),
      ),
    ).toEqual({
      page: 1,
      page_size: 20,
      q: undefined,
      status: undefined,
      run_status: undefined,
      winner: undefined,
      rule_set_id: undefined,
      created_from: undefined,
      created_to: "2026-07-10",
      sort: "created_at",
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
