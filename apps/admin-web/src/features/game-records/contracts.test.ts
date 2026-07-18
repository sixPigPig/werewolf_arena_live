import {
  deleteAdminGame,
  getAdminGame,
  getAdminGameDebug,
  getAdminGameModelRequest,
  getAdminGameQualityIssues,
  listAdminGameModelRequests,
  listAdminGames,
  retryAdminGameQualityEvaluation,
} from "@/features/game-records/api";
import { gameListParamsFromSearch } from "@/features/game-records/list-state";
import {
  parseAdminGameDebug,
  parseAdminGameDetail,
  parseAdminGameList,
  parseAdminGameModelRequestDetail,
  parseAdminGameModelRequestList,
  parseAdminGameQualityIssues,
} from "@/features/game-records/parsers";
import {
  contractGameDebug,
  contractGameDetail,
  contractGameItem,
  contractGameModelRequestDetail,
  contractGameModelRequests,
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
    expect(parseAdminGameModelRequestList(contractGameModelRequests)).toEqual(
      contractGameModelRequests,
    );
    expect(
      parseAdminGameModelRequestDetail(contractGameModelRequestDetail),
    ).toEqual(contractGameModelRequestDetail);
  });

  it("keeps review-task metadata optional while validating present fields", () => {
    const legacyEvaluation = { ...contractGameDetail.quality_evaluation };
    delete legacyEvaluation.source_revision;
    delete legacyEvaluation.created_at;
    delete legacyEvaluation.started_at;
    delete legacyEvaluation.completed_at;
    delete legacyEvaluation.attempt_count;
    delete legacyEvaluation.failure_reason;
    delete legacyEvaluation.can_retry;
    delete legacyEvaluation.latest_successful_result;
    const parsedLegacy = parseAdminGameDetail({
      ...contractGameDetail,
      quality_evaluation: legacyEvaluation,
    }).quality_evaluation;

    expect("source_revision" in parsedLegacy).toBe(false);
    expect("latest_successful_result" in parsedLegacy).toBe(false);
    expect(
      parseAdminGameDetail({
        ...contractGameDetail,
        quality_evaluation: {
          ...contractGameDetail.quality_evaluation,
          evaluation_status: "queued",
          started_at: null,
          completed_at: null,
          latest_successful_result: null,
        },
      }).quality_evaluation,
    ).toMatchObject({
      evaluation_status: "queued",
      started_at: null,
      completed_at: null,
      latest_successful_result: null,
    });
    expect(() =>
      parseAdminGameDetail({
        ...contractGameDetail,
        quality_evaluation: {
          ...contractGameDetail.quality_evaluation,
          attempt_count: -1,
        },
      }),
    ).toThrow(/attempt_count/);
    expect(() =>
      parseAdminGameDetail({
        ...contractGameDetail,
        quality_evaluation: {
          ...contractGameDetail.quality_evaluation,
          latest_successful_result: {
            ...contractGameDetail.quality_evaluation.latest_successful_result!,
            completed_at: "not-a-date",
          },
        },
      }),
    ).toThrow(/completed_at/);
  });

  it("strictly bounds and allowlists safe critical-decision cards", () => {
    expect(
      parseAdminGameDetail(contractGameDetail).quality_evaluation.critical_actions,
    ).toEqual(contractGameDetail.quality_evaluation.critical_actions);
    expect(() =>
      parseAdminGameDetail({
        ...contractGameDetail,
        quality_evaluation: {
          ...contractGameDetail.quality_evaluation,
          critical_actions: [
            {
              ...contractGameDetail.quality_evaluation.critical_actions[0],
              reasoning: "private reasoning must never cross the contract",
            },
          ],
        },
      }),
    ).toThrow(/reasoning/);
    expect(() =>
      parseAdminGameDetail({
        ...contractGameDetail,
        quality_evaluation: {
          ...contractGameDetail.quality_evaluation,
          critical_actions: Array.from({ length: 65 }, (_, index) => ({
            ...contractGameDetail.quality_evaluation.critical_actions[0],
            action_id: `action_contract_${index}`,
          })),
        },
      }),
    ).toThrow(/超过 64 条/);
    expect(() =>
      parseAdminGameDetail({
        ...contractGameDetail,
        quality_evaluation: {
          ...contractGameDetail.quality_evaluation,
          critical_actions: [
            {
              ...contractGameDetail.quality_evaluation.critical_actions[0],
              action_origin: "private_model_choice",
            },
          ],
        },
      }),
    ).toThrow(/action_origin/);
  });

  it("keeps model request summaries metadata-only and strictly parses details", () => {
    expect(() =>
      parseAdminGameModelRequestList({
        ...contractGameModelRequests,
        items: [
          {
            ...contractGameModelRequests.items[0],
            prompt: "private prompt",
          },
        ],
      }),
    ).toThrow(/prompt/);
    expect(() =>
      parseAdminGameModelRequestDetail({
        ...contractGameModelRequestDetail,
        api_key: "private key",
      }),
    ).toThrow(/api_key/);
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
        },
        rule_set: { ...contractGameDetail.rule_set, player_count: null },
        players: [
          { ...contractGameDetail.players[0], role: null },
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
        })),
      }),
    ).toMatchObject({
      status: "partial",
      winner: null,
      resumable: true,
      rule_set: { player_count: null },
      players: [{ role: null, model: "deepseek-v4-flash" }],
      latest_run: {
        villager_model: "deepseek-v4-flash",
        werewolf_model: "doubao-seed-1-6-flash",
      },
      rounds: [{ night_deaths: [{ cause: null, source: null }] }],
      runs: [
        {
          villager_model: "deepseek-v4-flash",
          werewolf_model: "doubao-seed-1-6-flash",
        },
      ],
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
    expect(
      parseAdminGameList({
        items: [{ ...contractGameItem, status: "partial", winner: null }],
        pagination: { page: 1, page_size: 20, total: 1, pages: 1 },
      }).items[0].latest_run?.villager_model,
    ).toBe("deepseek-v4-flash");
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
    expect(() =>
      parseAdminGameDetail({
        ...contractGameDetail,
        quality_evaluation: {
          ...contractGameDetail.quality_evaluation,
          prompt: "private quality sentinel",
        },
      }),
    ).toThrow(/prompt/);
    expect(() =>
      parseAdminGameQualityIssues({
        session_id: contractGameDetail.session_id,
        evaluation_id: "quality_contract",
        items: [
          {
            issue_id: "quality_issue_contract",
            code: "private_voice_materialized",
            severity: "P0",
            channel: "voice",
            round_number: 1,
            event_id: 5,
            utterance_id: "utterance_contract",
            first_detected_at: "2026-07-10T01:04:00Z",
            text: "private quality sentinel",
          },
        ],
      }),
    ).toThrow(/text/);
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
      },
      players: [
        { ...contractGameDetail.players[0], role: null },
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
      })),
    };
    expect(() =>
      parseAdminGameDetail({
        ...redacted,
        players: [{ ...redacted.players[0], role: "预言家" }],
      }),
    ).toThrow(/角色/);
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

  it("uses independent encoded detail, debug and model request endpoints", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(contractGameDetail))
      .mockResolvedValueOnce(jsonResponse(contractGameDebug))
      .mockResolvedValueOnce(jsonResponse(contractGameModelRequests))
      .mockResolvedValueOnce(jsonResponse(contractGameModelRequestDetail));
    vi.stubGlobal("fetch", fetchMock);

    await getAdminGame("game/unsafe");
    await getAdminGameDebug("game/unsafe");
    await listAdminGameModelRequests("game/unsafe");
    await getAdminGameModelRequest("game/unsafe", "req/unsafe");

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "/api/v1/admin/games/game%2Funsafe",
    );
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe(
      "/api/v1/admin/games/game%2Funsafe/debug",
    );
    expect(String(fetchMock.mock.calls[2]?.[0])).toBe(
      "/api/v1/admin/games/game%2Funsafe/model-requests",
    );
    expect(String(fetchMock.mock.calls[3]?.[0])).toBe(
      "/api/v1/admin/games/game%2Funsafe/model-requests/req%2Funsafe",
    );
  });

  it("uses independent quality issues and CSRF retry endpoints", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          session_id: "game/unsafe",
          evaluation_id: "quality_contract",
          items: [],
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          session_id: "game/unsafe",
          evaluation_id: "quality_contract",
          status: "pending",
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await getAdminGameQualityIssues("game/unsafe");
    await retryAdminGameQualityEvaluation("game/unsafe", "csrf-quality");

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "/api/v1/admin/games/game%2Funsafe/quality-evaluation/issues",
    );
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe(
      "/api/v1/admin/games/game%2Funsafe/quality-evaluation/retry",
    );
    const options = fetchMock.mock.calls[1]?.[1] as RequestInit;
    expect(options.method).toBe("POST");
    expect(new Headers(options.headers).get("X-CSRF-Token")).toBe(
      "csrf-quality",
    );
  });

  it("uses the encoded game endpoint and CSRF token for deletion", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(null, { status: 204 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await deleteAdminGame("game/unsafe", "csrf-delete");

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      "/api/v1/admin/games/game%2Funsafe",
    );
    const options = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(options.method).toBe("DELETE");
    expect(new Headers(options.headers).get("X-CSRF-Token")).toBe(
      "csrf-delete",
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
