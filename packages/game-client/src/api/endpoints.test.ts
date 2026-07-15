import { afterEach, describe, expect, it, vi } from "vitest";

import { createGameRun } from "./createGameRun";
import { getGamePlayback, getGamePlaybackVoice } from "./getGamePlayback";
import { listGames } from "./listGames";
import { listPlayerProfiles } from "./listPlayerProfiles";
import { previewGameLineup } from "./previewGameLineup";
import { clearPublicSessionCache } from "./publicSession";
import { resumeGameRun } from "./resumeGameRun";

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
    status: 200,
  });
}

describe("game API endpoints", () => {
  afterEach(() => {
    clearPublicSessionCache();
    vi.unstubAllGlobals();
  });

  it("lists games from the existing backend contract", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ sessions: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listGames()).resolves.toEqual({ sessions: [] });

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/games", undefined);
  });

  it("lists player profiles from the existing backend contract", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ profiles: [] }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listPlayerProfiles()).resolves.toEqual({ profiles: [] });

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/player-profiles", undefined);
  });

  it("creates a run with the current web request body", async () => {
    const run = {
      run_id: "run-1",
      session_id: "session-1",
      villager_model: "",
      werewolf_model: "",
      rule_set: null,
      seed: null,
      max_rounds: 8,
      winner: null,
      status: "queued",
      created_at: "2026-06-19T00:00:00Z",
      started_at: null,
      completed_at: null,
      error: null,
      event_count: 0,
    };
    const fetchMock = vi.fn(async () => jsonResponse(run));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      createGameRun({
        rule_set_id: "classic_8",
        max_rounds: 8,
        player_configs: [{ seat: 1, profile_id: "profile-1" }],
      }),
    ).resolves.toEqual(run);

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/games/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rule_set_id: "classic_8",
        max_rounds: 8,
        player_configs: [{ seat: 1, profile_id: "profile-1" }],
      }),
    });
  });

  it("previews a diverse lineup before creation", async () => {
    const preview = {
      player_configs: [{ seat: 1, profile_id: "profile-1" }],
      lineup_quality_report: {
        schema_version: 1,
        policy_mode: "repair",
        player_count: 1,
        configured_count: 1,
        is_blocked: false,
        was_repaired: true,
        style_bucket_count: 1,
        required_style_bucket_count: 1,
        violations: [],
      },
      rule_set_revision_id: "revision-1",
    } as const;
    const fetchMock = vi.fn(async () => jsonResponse(preview));
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      previewGameLineup({
        rule_set_id: "starter_6",
        seed: 21,
        player_configs: [],
        locked_seats: [],
        repair_scope: "empty_only",
      }),
    ).resolves.toEqual(preview);

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/games/lineup-preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rule_set_id: "starter_6",
        seed: 21,
        player_configs: [],
        locked_seats: [],
        repair_scope: "empty_only",
      }),
    });
  });

  it("resumes a failed session by session id", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        run_id: "run-2",
        session_id: "session-2",
        villager_model: "",
        werewolf_model: "",
        rule_set: null,
        seed: null,
        max_rounds: 8,
        winner: null,
        status: "queued",
        created_at: "2026-06-19T00:00:00Z",
        started_at: null,
        completed_at: null,
        error: null,
        event_count: 0,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await resumeGameRun("session-2");

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/games/session-2/resume", {
      method: "POST",
    });
  });

  it("loads game playback from the existing backend contract", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        session_id: "session-1",
        status: "complete",
        rule_set: null,
        resumable: false,
        events: [],
        voices: [
          {
            utterance_id: "voice-1",
            source_event_id: 4,
            last_source_event_id: 4,
            speaker_kind: "player",
            speaker_name: "阿青",
            mime_type: "audio/L16",
            audio_format: "pcm",
            sample_rate: 24000,
            duration_ms: 120,
            subtitle_timings: [],
            chunks: [{ chunk_index: 0, data: "YWJj" }],
          },
        ],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getGamePlayback("session-1")).resolves.toMatchObject({
      session_id: "session-1",
      voices: [{ utterance_id: "voice-1" }],
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/games/session-1/playback",
      undefined,
    );
  });

  it("defaults missing playback voices to an empty list", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          session_id: "session-1",
          status: "complete",
          rule_set: null,
          resumable: false,
          events: [],
        }),
      ),
    );

    await expect(getGamePlayback("session-1")).resolves.toMatchObject({
      voices: [],
    });
  });

  it("loads one saved playback voice on demand", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({
        utterance_id: "voice/1",
        source_event_id: 4,
        last_source_event_id: 4,
        speaker_kind: "player",
        speaker_name: "阿青",
        mime_type: "audio/L16",
        audio_format: "pcm",
        sample_rate: 24000,
        duration_ms: 120,
        subtitle_timings: [],
        chunks: [{ chunk_index: 0, data: "YWJj" }],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      getGamePlaybackVoice("session-1", "voice/1"),
    ).resolves.toMatchObject({ utterance_id: "voice/1" });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/games/session-1/playback/voices/voice%2F1",
      undefined,
    );
  });

  it("bootstraps a guest session before loading God View playback", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (url === "/api/v1/public/session") {
        return jsonResponse({
          viewer: { kind: "guest" },
          csrf_token: "csrf-public-session",
          session_expires_at: "2999-07-10T00:00:00.000Z",
        });
      }
      return jsonResponse({
        session_id: "session-1",
        status: "complete",
        rule_set: null,
        resumable: false,
        events: [],
        voices: [],
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      getGamePlayback("session-1", "spectator_god_view"),
    ).resolves.toMatchObject({ session_id: "session-1" });

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/v1/public/session", {
      credentials: "include",
      method: "POST",
    });
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/v1/games/session-1/god-view/playback",
      { credentials: "include" },
    );
  });
});
