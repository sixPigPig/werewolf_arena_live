# Live Replay Saved Voice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Saved voice generated during live games is returned by the playback API and can be played directly in the mobile live replay page.

**Architecture:** The backend prefers persisted `live_events` for playback when they exist, then attaches completed saved voice utterances from `voice_utterances` and `voice_audio_chunks`. The frontend adds a local playback voice hook that exposes the same UI contract as `useLiveVoiceStream`, uses the existing PCM scheduler, and is wired into `LiveReplayPage`.

**Tech Stack:** FastAPI, SQLAlchemy, pytest, React 19, TanStack Query, Vitest, TypeScript, Web Audio API.

---

## File Structure

- Modify `apps/api/app/werewolf/live_store.py`: add a session-level persisted event query for playback alignment.
- Modify `apps/api/tests/test_live_store.py`: verify latest eventful persisted run selection and playback event serialization.
- Modify `apps/api/app/werewolf/voice_store.py`: add a playback voice list query with base64 chunk payloads.
- Modify `apps/api/tests/test_voice_store.py`: verify filtering, ordering, and JSON-ready chunk data.
- Modify `apps/api/app/api/routes/games.py`: add `voices` to the playback route when persisted events are available.
- Modify `apps/api/tests/test_games_api.py`: verify `/playback` includes saved voices only when event IDs are aligned.
- Modify `packages/game-client/src/types.ts`: add `PlaybackVoiceChunk`, `PlaybackVoiceUtterance`, and `GamePlayback.voices`.
- Modify `packages/game-client/src/api/getGamePlayback.ts`: normalize missing `voices` to `[]`.
- Modify `packages/game-client/src/api/endpoints.test.ts`: verify the playback endpoint and `voices` default.
- Create `packages/game-client/src/live/livePlaybackVoice.ts`: implement saved voice playback state and audio scheduling.
- Create `packages/game-client/src/live/livePlaybackVoice.test.tsx`: test hook state, unlock, event gating, scheduling, and pause/resume.
- Modify `packages/game-client/src/live/index.ts`: export the new hook.
- Modify `apps/mobile-web/src/pages/LiveReplayPage.tsx`: connect the saved voice hook to `MobileLiveTheater`.
- Modify `apps/mobile-web/src/pages/LiveReplayPage.test.tsx`: test replay voice button behavior.

## Task 1: Persisted Live Events For Playback

**Files:**
- Modify: `apps/api/app/werewolf/live_store.py`
- Test: `apps/api/tests/test_live_store.py`

- [ ] **Step 1: Write the failing latest-run playback event test**

Append this test to `apps/api/tests/test_live_store.py`:

```python
def test_live_store_returns_latest_eventful_playback_events_for_session(
    db_session: Session,
) -> None:
    first_registry = LiveRunRegistry()
    first_run = first_registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=7,
        max_rounds=8,
    )
    first_event = first_registry.publish(first_run.run_id, "phase_started", phase="night")

    empty_registry = LiveRunRegistry()
    empty_run = empty_registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=8,
        max_rounds=8,
    )

    latest_registry = LiveRunRegistry()
    latest_run = latest_registry.create_run(
        session_id="game_1200abcd",
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=9,
        max_rounds=8,
    )
    latest_event = latest_registry.publish(
        latest_run.run_id,
        "model_response_delta",
        actor="阿青",
        action="debate",
        payload={"request_id": "req-1", "visible_text": "我不是狼", "is_public": True},
    )
    store = DatabaseLiveStore(db_session)

    store.save_run(first_run)
    store.append_event(first_event)
    store.save_run(empty_run)
    store.save_run(latest_run)
    store.append_event(latest_event)

    playback_events = store.playback_events_for_session("game_1200abcd")

    assert [event["id"] for event in playback_events] == [latest_event.id]
    assert {event["run_id"] for event in playback_events} == {"playback_game_1200abcd"}
    assert playback_events[-1]["payload"]["visible_text"] == "我不是狼"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_live_store.py::test_live_store_returns_latest_eventful_playback_events_for_session -q`

Expected: FAIL with `AttributeError: 'DatabaseLiveStore' object has no attribute 'playback_events_for_session'`.

- [ ] **Step 3: Implement persisted playback event query**

Add this method to `DatabaseLiveStore` in `apps/api/app/werewolf/live_store.py`:

```python
    def playback_events_for_session(self, session_id: str) -> list[dict[str, Any]]:
        eventful_run_id = (
            self.db.query(LiveEventRecord.run_id)
            .join(LiveRunRecord, LiveRunRecord.run_id == LiveEventRecord.run_id)
            .filter(LiveRunRecord.session_id == session_id)
            .group_by(LiveEventRecord.run_id)
            .order_by(func.max(LiveEventRecord.created_at).desc())
            .scalar()
        )
        if eventful_run_id is None:
            return []

        playback_run_id = f"playback_{session_id}"
        return [
            {
                **event.to_dict(),
                "run_id": playback_run_id,
            }
            for event in self.events_after(eventful_run_id)
        ]
```

Also update imports in `live_store.py`:

```python
from typing import Any

from sqlalchemy import func
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && uv run pytest tests/test_live_store.py::test_live_store_returns_latest_eventful_playback_events_for_session -q`

Expected: PASS.

## Task 2: Playback Voice Store Query

**Files:**
- Modify: `apps/api/app/werewolf/voice_store.py`
- Test: `apps/api/tests/test_voice_store.py`

- [ ] **Step 1: Write the failing playback voice query test**

Append this test to `apps/api/tests/test_voice_store.py`:

```python
def test_voice_store_lists_playback_voices_with_base64_chunks(
    db_session: Session,
) -> None:
    store = DatabaseVoiceStore(db_session, session_id="game_1200abcd")
    first = stored_utterance(utterance_id="voice_first", source_event_id=4, text="第一句")
    second = stored_utterance(utterance_id="voice_second", source_event_id=8, text="第二句")
    failed = stored_utterance(utterance_id="voice_failed", source_event_id=9, text="失败")
    chunkless = stored_utterance(utterance_id="voice_chunkless", source_event_id=10, text="无音频")
    invalid_kind = stored_utterance(
        utterance_id="voice_invalid_kind",
        source_event_id=11,
        text="无效类型",
        speaker_kind="moderator",
    )

    store.upsert_utterance(second, audio_format="pcm", sample_rate=24000, mime_type="audio/L16")
    store.append_chunk("voice_second", chunk_index=0, audio=b"second-0")
    store.complete_utterance("voice_second", duration_ms=200)
    store.upsert_utterance(first, audio_format="pcm", sample_rate=24000, mime_type="audio/L16")
    store.append_chunk("voice_first", chunk_index=1, audio=b"first-1")
    store.append_chunk("voice_first", chunk_index=0, audio=b"first-0")
    store.complete_utterance("voice_first", duration_ms=100)
    store.upsert_utterance(failed, audio_format="pcm", sample_rate=24000, mime_type="audio/L16")
    store.append_chunk("voice_failed", chunk_index=0, audio=b"failed")
    store.fail_utterance("voice_failed", message="tts failed")
    store.upsert_utterance(chunkless, audio_format="pcm", sample_rate=24000, mime_type="audio/L16")
    store.complete_utterance("voice_chunkless", duration_ms=50)
    store.upsert_utterance(
        invalid_kind,
        audio_format="pcm",
        sample_rate=24000,
        mime_type="audio/L16",
    )
    store.append_chunk("voice_invalid_kind", chunk_index=0, audio=b"invalid")
    store.complete_utterance("voice_invalid_kind", duration_ms=50)

    voices = store.list_playback_voices()

    assert [voice["utterance_id"] for voice in voices] == ["voice_first", "voice_second"]
    assert voices[0]["source_event_id"] == 4
    assert voices[0]["duration_ms"] == 100
    assert voices[0]["chunks"] == [
        {"chunk_index": 0, "data": "Zmlyc3QtMA=="},
        {"chunk_index": 1, "data": "Zmlyc3QtMQ=="},
    ]
    assert voices[1]["chunks"] == [{"chunk_index": 0, "data": "c2Vjb25kLTA="}]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/api && uv run pytest tests/test_voice_store.py::test_voice_store_lists_playback_voices_with_base64_chunks -q`

Expected: FAIL with `AttributeError: 'DatabaseVoiceStore' object has no attribute 'list_playback_voices'`.

- [ ] **Step 3: Implement `list_playback_voices()`**

Add `import base64` to `apps/api/app/werewolf/voice_store.py`, then add this method to `DatabaseVoiceStore`:

```python
    def list_playback_voices(self) -> list[dict[str, Any]]:
        rows = (
            self.db.query(VoiceUtteranceRecord, VoiceAudioChunkRecord)
            .join(
                VoiceAudioChunkRecord,
                VoiceAudioChunkRecord.utterance_id == VoiceUtteranceRecord.utterance_id,
            )
            .filter(
                VoiceUtteranceRecord.session_id == self.session_id,
                VoiceUtteranceRecord.status == "complete",
                VoiceUtteranceRecord.speaker_kind.in_(("player", "judge")),
                VoiceUtteranceRecord.sample_rate > 0,
            )
            .order_by(
                VoiceUtteranceRecord.source_event_id.asc(),
                VoiceUtteranceRecord.utterance_id.asc(),
                VoiceAudioChunkRecord.chunk_index.asc(),
            )
            .all()
        )

        voices_by_id: dict[str, dict[str, Any]] = {}
        for utterance, chunk in rows:
            voice = voices_by_id.setdefault(
                utterance.utterance_id,
                {
                    "utterance_id": utterance.utterance_id,
                    "source_event_id": utterance.source_event_id,
                    "last_source_event_id": utterance.last_source_event_id,
                    "speaker_kind": utterance.speaker_kind,
                    "speaker_name": utterance.speaker_name,
                    "mime_type": utterance.mime_type,
                    "audio_format": utterance.audio_format,
                    "sample_rate": utterance.sample_rate,
                    "duration_ms": utterance.duration_ms,
                    "chunks": [],
                },
            )
            voice["chunks"].append(
                {
                    "chunk_index": chunk.chunk_index,
                    "data": base64.b64encode(chunk.audio).decode("ascii"),
                }
            )
        return list(voices_by_id.values())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/api && uv run pytest tests/test_voice_store.py::test_voice_store_lists_playback_voices_with_base64_chunks -q`

Expected: PASS.

## Task 3: Playback API Combines Persisted Events And Saved Voices

**Files:**
- Modify: `apps/api/app/api/routes/games.py`
- Test: `apps/api/tests/test_games_api.py`

- [ ] **Step 1: Write failing API integration tests**

Add `VoiceAudioChunkRecord` and `VoiceUtteranceRecord` to the model import in `apps/api/tests/test_games_api.py`:

```python
from app.models.live import (
    LiveEventRecord,
    LiveRunRecord,
    VoiceAudioChunkRecord,
    VoiceUtteranceRecord,
)
```

Add these rows to both cleanup blocks inside `isolated_db` before deleting `LiveRunRecord`:

```python
        session.query(VoiceAudioChunkRecord).delete()
        session.query(VoiceUtteranceRecord).delete()
```

Append these tests:

```python
def test_get_game_playback_returns_persisted_events_and_saved_voices() -> None:
    session_id = "game_voiceabcd"
    store_game_session(session_id)
    registry = LiveRunRegistry(live_store=RecordingSessionLiveStore())
    run = registry.create_run(
        session_id=session_id,
        villager_model="deepseek-chat",
        werewolf_model="deepseek-chat",
        seed=21,
        max_rounds=8,
    )
    event = registry.publish(
        run.run_id,
        "model_response_delta",
        actor="阿青",
        action="debate",
        payload={"request_id": "req-voice", "visible_text": "我不是狼", "is_public": True},
    )
    with TestingSessionLocal() as session:
        voice_store = DatabaseVoiceStore(session, session_id=session_id)
        voice_store.upsert_utterance(
            VoiceUtterance(
                utterance_id="voice_api_1",
                run_id=run.run_id,
                source_event_id=event.id,
                request_id="req-voice",
                speaker_kind="player",
                speaker_name="阿青",
                speaker="player",
                text="我不是狼",
                action="debate",
            ),
            audio_format="pcm",
            sample_rate=24000,
            mime_type="audio/L16",
        )
        voice_store.append_chunk("voice_api_1", chunk_index=0, audio=b"abc")
        voice_store.complete_utterance("voice_api_1", duration_ms=123)

    response = client.get(f"/api/v1/games/{session_id}/playback")

    assert response.status_code == 200
    payload = response.json()
    assert [event["id"] for event in payload["events"]] == [1, event.id]
    assert {event["run_id"] for event in payload["events"]} == {f"playback_{session_id}"}
    assert payload["voices"] == [
        {
            "utterance_id": "voice_api_1",
            "source_event_id": event.id,
            "last_source_event_id": event.id,
            "speaker_kind": "player",
            "speaker_name": "阿青",
            "mime_type": "audio/L16",
            "audio_format": "pcm",
            "sample_rate": 24000,
            "duration_ms": 123,
            "chunks": [{"chunk_index": 0, "data": "YWJj"}],
        }
    ]


def test_get_game_playback_omits_saved_voices_without_persisted_live_events() -> None:
    session_id = "game_synthvoice"
    store_game_session(session_id)
    with TestingSessionLocal() as session:
        voice_store = DatabaseVoiceStore(session, session_id=session_id)
        voice_store.upsert_utterance(
            VoiceUtterance(
                utterance_id="voice_unaligned",
                run_id="run_missing",
                source_event_id=99,
                request_id="req-missing",
                speaker_kind="player",
                speaker_name="阿青",
                speaker="player",
                text="不要错位播放",
                action="debate",
            ),
            audio_format="pcm",
            sample_rate=24000,
            mime_type="audio/L16",
        )
        voice_store.append_chunk("voice_unaligned", chunk_index=0, audio=b"abc")
        voice_store.complete_utterance("voice_unaligned", duration_ms=123)

    response = client.get(f"/api/v1/games/{session_id}/playback")

    assert response.status_code == 200
    payload = response.json()
    assert payload["events"][0]["run_id"] == f"playback_{session_id}"
    assert payload["voices"] == []
```

Also add this import:

```python
from app.werewolf.voice import VoiceUtterance
from app.werewolf.voice_store import DatabaseVoiceStore
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/api && uv run pytest tests/test_games_api.py::test_get_game_playback_returns_persisted_events_and_saved_voices tests/test_games_api.py::test_get_game_playback_omits_saved_voices_without_persisted_live_events -q`

Expected: first test FAILS because `voices` is missing or events are synthetic; second test FAILS because `voices` is missing.

- [ ] **Step 3: Implement route merge**

Change `get_game_playback()` in `apps/api/app/api/routes/games.py` to accept `db` and merge playback data:

```python
@router.get("/{session_id}/playback")
def get_game_playback(
    session_id: Annotated[
        str,
        Path(pattern=SESSION_ID_RE),
    ],
    store: Annotated[GameRecordStore, Depends(get_replay_store)],
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    try:
        playback = build_replay_playback(store.load_session(session_id))
    except ReplayNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Game session not found") from exc

    try:
        persisted_events = DatabaseLiveStore(db).playback_events_for_session(session_id)
    except RecoverableDatabaseError:
        persisted_events = []

    if not persisted_events:
        playback["voices"] = []
        return playback

    playback["events"] = persisted_events
    try:
        playback["voices"] = DatabaseVoiceStore(db, session_id=session_id).list_playback_voices()
    except RecoverableDatabaseError:
        playback["voices"] = []
    return playback
```

- [ ] **Step 4: Run API tests to verify they pass**

Run: `cd apps/api && uv run pytest tests/test_games_api.py::test_get_game_playback_returns_persisted_events_and_saved_voices tests/test_games_api.py::test_get_game_playback_omits_saved_voices_without_persisted_live_events -q`

Expected: PASS.

## Task 4: Shared Game Client Types And Playback API Normalization

**Files:**
- Modify: `packages/game-client/src/types.ts`
- Modify: `packages/game-client/src/api/getGamePlayback.ts`
- Test: `packages/game-client/src/api/endpoints.test.ts`

- [ ] **Step 1: Write failing endpoint tests**

Add `getGamePlayback` to the imports in `packages/game-client/src/api/endpoints.test.ts`:

```ts
import { getGamePlayback } from "./getGamePlayback";
```

Append these tests:

```ts
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
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/games/session-1/playback", undefined);
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
```

- [ ] **Step 2: Run tests to verify default test fails**

Run: `pnpm --dir packages/game-client test -- --run src/api/endpoints.test.ts`

Expected: FAIL because `getGamePlayback()` returns a payload without `voices`.

- [ ] **Step 3: Add types and normalization**

In `packages/game-client/src/types.ts`, add before `GamePlayback`:

```ts
export type PlaybackVoiceChunk = {
  chunk_index: number;
  data: string;
};

export type PlaybackVoiceUtterance = {
  utterance_id: string;
  source_event_id: number;
  last_source_event_id: number;
  speaker_kind: "player" | "judge";
  speaker_name: string;
  mime_type: string;
  audio_format: string;
  sample_rate: number;
  duration_ms: number | null;
  chunks: PlaybackVoiceChunk[];
};
```

Update `GamePlayback`:

```ts
export type GamePlayback = {
  session_id: string;
  status: GameStatus;
  rule_set?: RuleSetSummary | null;
  resumable?: boolean;
  events: LiveGameEvent[];
  voices: PlaybackVoiceUtterance[];
};
```

Update `packages/game-client/src/api/getGamePlayback.ts`:

```ts
export async function getGamePlayback(sessionId: string): Promise<GamePlayback> {
  const playback = await apiFetch<GamePlayback & { voices?: GamePlayback["voices"] }>(
    `/api/v1/games/${sessionId}/playback`,
  );
  return { ...playback, voices: playback.voices ?? [] };
}
```

- [ ] **Step 4: Run endpoint tests to verify they pass**

Run: `pnpm --dir packages/game-client test -- --run src/api/endpoints.test.ts`

Expected: PASS.

## Task 5: Saved Voice Playback Hook

**Files:**
- Create: `packages/game-client/src/live/livePlaybackVoice.ts`
- Create: `packages/game-client/src/live/livePlaybackVoice.test.tsx`
- Modify: `packages/game-client/src/live/index.ts`

- [ ] **Step 1: Write failing hook tests**

Create `packages/game-client/src/live/livePlaybackVoice.test.tsx` with tests that use a fake `AudioContext` and assert:

```ts
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { usePlaybackVoice } from "./livePlaybackVoice";
import type { PlaybackVoiceUtterance } from "../types";

const scheduleMock = vi.fn(async () => ({ endTime: 1 }));
const resumeMock = vi.fn(async () => undefined);
const suspendMock = vi.fn(async () => undefined);
const closeMock = vi.fn(async () => undefined);

vi.mock("./livePcmPlayer", () => ({
  createPcmAudioScheduler: () => ({
    schedule: scheduleMock,
    resume: resumeMock,
    suspend: suspendMock,
    close: closeMock,
  }),
}));

class FakeAudioContext {
  currentTime = 0;
  state = "running";
  resume = vi.fn(async () => undefined);
  close = vi.fn(async () => undefined);
}

function voice(overrides: Partial<PlaybackVoiceUtterance> = {}): PlaybackVoiceUtterance {
  return {
    utterance_id: "voice-1",
    source_event_id: 4,
    last_source_event_id: 4,
    speaker_kind: "player",
    speaker_name: "阿青",
    mime_type: "audio/L16",
    audio_format: "pcm",
    sample_rate: 24000,
    duration_ms: 100,
    chunks: [{ chunk_index: 0, data: "YWJj" }],
    ...overrides,
  };
}

describe("playback voice", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    scheduleMock.mockClear();
    resumeMock.mockClear();
    suspendMock.mockClear();
    closeMock.mockClear();
    vi.stubGlobal("AudioContext", FakeAudioContext);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("reports unavailable when enabled with no saved voices", async () => {
    const { result } = renderHook(() =>
      usePlaybackVoice([], { currentEventId: 1, enabled: true, isPaused: false }),
    );

    expect(result.current.connectionState).toBe("unavailable");
    expect(result.current.errors.at(-1)).toBe("这局回放没有保存的语音。");
  });

  it("unlocks audio before scheduling saved PCM", async () => {
    const { result } = renderHook(() =>
      usePlaybackVoice([voice()], { currentEventId: 4, enabled: false, isPaused: false }),
    );

    await act(async () => {
      await expect(result.current.unlockAudio()).resolves.toBe(true);
    });
  });

  it("schedules saved PCM chunks after reaching the source event", async () => {
    const { rerender } = renderHook(
      ({ currentEventId, enabled }) =>
        usePlaybackVoice([voice()], { currentEventId, enabled, isPaused: false }),
      { initialProps: { currentEventId: 3, enabled: true } },
    );

    expect(scheduleMock).not.toHaveBeenCalled();

    rerender({ currentEventId: 4, enabled: true });
    await act(async () => {
      await Promise.resolve();
    });

    expect(scheduleMock).toHaveBeenCalledWith("YWJj", 24000);
  });

  it("suspends and resumes with replay pause state", async () => {
    const { rerender } = renderHook(
      ({ isPaused }) =>
        usePlaybackVoice([voice()], { currentEventId: 4, enabled: true, isPaused }),
      { initialProps: { isPaused: false } },
    );
    await act(async () => {
      await Promise.resolve();
    });

    rerender({ isPaused: true });
    await act(async () => {
      await Promise.resolve();
    });
    expect(suspendMock).toHaveBeenCalled();

    rerender({ isPaused: false });
    await act(async () => {
      await Promise.resolve();
    });
    expect(resumeMock).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run hook tests to verify they fail**

Run: `pnpm --dir packages/game-client test -- --run src/live/livePlaybackVoice.test.tsx`

Expected: FAIL because `./livePlaybackVoice` does not exist.

- [ ] **Step 3: Implement `usePlaybackVoice()`**

Create `packages/game-client/src/live/livePlaybackVoice.ts` with:

```ts
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { createPcmAudioScheduler, type PcmAudioScheduler } from "./livePcmPlayer";
import type {
  LiveVoiceConnectionState,
  LiveVoiceQueueItem,
} from "./liveVoiceStream";
import type { PlaybackVoiceUtterance } from "../types";

const PLAYBACK_VOICE_EMPTY_MESSAGE = "这局回放没有保存的语音。";
const PLAYBACK_VOICE_ERROR_MESSAGE = "Unable to play saved replay voice audio.";
const PCM_COMPLETION_POLL_INTERVAL_MS = 25;

export function usePlaybackVoice(
  voices: PlaybackVoiceUtterance[],
  {
    currentEventId,
    enabled,
    isPaused,
  }: {
    currentEventId: number | null;
    enabled: boolean;
    isPaused: boolean;
  },
) {
  const sortedVoices = useMemo(
    () =>
      voices
        .filter(isPlayablePlaybackVoice)
        .slice()
        .sort((left, right) => left.source_event_id - right.source_event_id),
    [voices],
  );
  const [errors, setErrors] = useState<string[]>([]);
  const [currentItem, setCurrentItem] = useState<LiveVoiceQueueItem | null>(null);
  const consumedUtteranceIdsRef = useRef<Set<string>>(new Set());
  const audioContextRef = useRef<AudioContext | null>(null);
  const schedulerRef = useRef<PcmAudioScheduler | null>(null);

  const connectionState: LiveVoiceConnectionState = !enabled
    ? "idle"
    : sortedVoices.length === 0
      ? "unavailable"
      : errors.some((error) => error === PLAYBACK_VOICE_ERROR_MESSAGE)
        ? "error"
        : "open";

  const ensureScheduler = useCallback(() => {
    if (audioContextRef.current && schedulerRef.current) {
      return { context: audioContextRef.current, scheduler: schedulerRef.current };
    }
    const AudioContextConstructor =
      globalThis.AudioContext ??
      (globalThis as typeof globalThis & { webkitAudioContext?: typeof AudioContext })
        .webkitAudioContext;
    if (typeof AudioContextConstructor !== "function") {
      return null;
    }
    const context = new AudioContextConstructor();
    const scheduler = createPcmAudioScheduler(context);
    audioContextRef.current = context;
    schedulerRef.current = scheduler;
    return { context, scheduler };
  }, []);

  const unlockAudio = useCallback(async () => {
    if (sortedVoices.length === 0) {
      setErrors((current) =>
        current.includes(PLAYBACK_VOICE_EMPTY_MESSAGE)
          ? current
          : [...current, PLAYBACK_VOICE_EMPTY_MESSAGE],
      );
      return false;
    }
    const audio = ensureScheduler();
    if (!audio) {
      setErrors((current) => [...current, "当前浏览器不支持语音播放。"]);
      return false;
    }
    await audio.context.resume();
    await audio.scheduler.resume();
    return true;
  }, [ensureScheduler, sortedVoices.length]);

  useEffect(() => {
    consumedUtteranceIdsRef.current.clear();
    setCurrentItem(null);
    setErrors([]);
  }, [sortedVoices]);

  useEffect(() => {
    if (!enabled || sortedVoices.length > 0) {
      return;
    }
    setErrors((current) =>
      current.includes(PLAYBACK_VOICE_EMPTY_MESSAGE)
        ? current
        : [...current, PLAYBACK_VOICE_EMPTY_MESSAGE],
    );
  }, [enabled, sortedVoices.length]);

  useEffect(() => {
    if (!enabled || isPaused || currentEventId === null) {
      return;
    }
    const nextVoice = sortedVoices.find(
      (voice) =>
        voice.source_event_id <= currentEventId &&
        !consumedUtteranceIdsRef.current.has(voice.utterance_id),
    );
    if (!nextVoice) {
      return;
    }
    const audio = ensureScheduler();
    if (!audio) {
      setErrors((current) => [...current, PLAYBACK_VOICE_ERROR_MESSAGE]);
      consumedUtteranceIdsRef.current.add(nextVoice.utterance_id);
      return;
    }
    let isActive = true;
    void (async () => {
      try {
        if (audio.context.state !== "running") {
          await audio.context.resume();
        }
        await audio.scheduler.resume();
        for (const chunk of nextVoice.chunks.slice().sort(byChunkIndex)) {
          if (!isActive) {
            return;
          }
          await audio.scheduler.schedule(chunk.data, nextVoice.sample_rate);
        }
        setCurrentItem(toQueueItem(nextVoice));
        globalThis.setTimeout(() => {
          consumedUtteranceIdsRef.current.add(nextVoice.utterance_id);
          setCurrentItem((current) =>
            current?.utteranceId === nextVoice.utterance_id ? null : current,
          );
        }, PCM_COMPLETION_POLL_INTERVAL_MS);
      } catch {
        consumedUtteranceIdsRef.current.add(nextVoice.utterance_id);
        setCurrentItem(null);
        setErrors((current) => [...current, PLAYBACK_VOICE_ERROR_MESSAGE]);
      }
    })();
    return () => {
      isActive = false;
    };
  }, [currentEventId, enabled, ensureScheduler, isPaused, sortedVoices]);

  useEffect(() => {
    const scheduler = schedulerRef.current;
    if (!enabled || !scheduler) {
      return;
    }
    if (isPaused) {
      void scheduler.suspend().catch(() => {
        setErrors((current) => [...current, PLAYBACK_VOICE_ERROR_MESSAGE]);
      });
    } else {
      void scheduler.resume().catch(() => {
        setErrors((current) => [...current, PLAYBACK_VOICE_ERROR_MESSAGE]);
      });
    }
  }, [enabled, isPaused]);

  useEffect(() => {
    if (enabled) {
      return;
    }
    const scheduler = schedulerRef.current;
    audioContextRef.current = null;
    schedulerRef.current = null;
    void scheduler?.close().catch(() => undefined);
  }, [enabled]);

  return {
    connectionState,
    currentItem,
    currentSpeakerName: isPaused ? null : currentItem?.speakerName ?? null,
    errors,
    unlockAudio,
  };
}

function isPlayablePlaybackVoice(voice: PlaybackVoiceUtterance) {
  return (
    (voice.speaker_kind === "player" || voice.speaker_kind === "judge") &&
    voice.audio_format.toLowerCase() === "pcm" &&
    voice.sample_rate > 0 &&
    voice.chunks.length > 0
  );
}

function byChunkIndex(
  left: PlaybackVoiceUtterance["chunks"][number],
  right: PlaybackVoiceUtterance["chunks"][number],
) {
  return left.chunk_index - right.chunk_index;
}

function toQueueItem(voice: PlaybackVoiceUtterance): LiveVoiceQueueItem {
  const chunkMetadata = voice.chunks.slice().sort(byChunkIndex).map((chunk) => ({
    audioFormat: voice.audio_format,
    chunkIndex: chunk.chunk_index,
    data: chunk.data,
    sampleRate: voice.sample_rate,
  }));
  return {
    utteranceId: voice.utterance_id,
    sourceEventId: voice.source_event_id,
    speakerKind: voice.speaker_kind,
    speakerName: voice.speaker_name,
    mimeType: voice.mime_type,
    audioFormat: voice.audio_format,
    sampleRate: voice.sample_rate,
    chunks: chunkMetadata.map((chunk) => chunk.data),
    chunkMetadata,
    isEnded: true,
    status: "playing",
  };
}
```

Add this export to `packages/game-client/src/live/index.ts`:

```ts
export * from "./livePlaybackVoice";
```

- [ ] **Step 4: Run hook tests to verify they pass**

Run: `pnpm --dir packages/game-client test -- --run src/live/livePlaybackVoice.test.tsx`

Expected: PASS.

## Task 6: Mobile Live Replay Voice Integration

**Files:**
- Modify: `apps/mobile-web/src/pages/LiveReplayPage.tsx`
- Test: `apps/mobile-web/src/pages/LiveReplayPage.test.tsx`

- [ ] **Step 1: Write failing page tests**

In `apps/mobile-web/src/pages/LiveReplayPage.test.tsx`, add `usePlaybackVoice` to `gameClientMocks`, export it from the mock, and append:

```ts
  it("enables saved replay voice after unlocking audio", async () => {
    const unlockAudio = vi.fn(async () => true);
    gameClientMocks.usePlaybackVoice.mockReturnValue({
      connectionState: "idle",
      currentSpeakerName: null,
      errors: [],
      unlockAudio,
    });
    gameClientMocks.getGamePlayback.mockResolvedValue(
      buildPlayback({
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
            duration_ms: 100,
            chunks: [{ chunk_index: 0, data: "YWJj" }],
          },
        ],
      }),
    );
    const user = userEvent.setup();

    renderLiveReplayRoute();

    await user.click(await screen.findByRole("button", { name: "开启语音" }));

    expect(unlockAudio).toHaveBeenCalled();
    expect(gameClientMocks.usePlaybackVoice).toHaveBeenLastCalledWith(
      expect.arrayContaining([expect.objectContaining({ utterance_id: "voice-1" })]),
      expect.objectContaining({ enabled: true, isPaused: false }),
    );
  });

  it("shows unavailable replay voice when the playback has no saved voice", async () => {
    gameClientMocks.usePlaybackVoice.mockReturnValue({
      connectionState: "unavailable",
      currentSpeakerName: null,
      errors: ["这局回放没有保存的语音。"],
      unlockAudio: vi.fn(async () => false),
    });

    renderLiveReplayRoute();

    expect(await screen.findByRole("button", { name: "语音不可用" })).toBeDisabled();
    expect(screen.getByText("这局回放没有保存的语音。")).toBeVisible();
  });
```

Update `buildPlayback()` to include `voices: []`.

- [ ] **Step 2: Run page tests to verify they fail**

Run: `pnpm --dir apps/mobile-web test -- --run src/pages/LiveReplayPage.test.tsx`

Expected: FAIL because `LiveReplayPage` does not call `usePlaybackVoice` or render the voice button.

- [ ] **Step 3: Connect replay voice hook**

Update imports in `apps/mobile-web/src/pages/LiveReplayPage.tsx`:

```ts
import { useMemo, useState } from "react";
```

and add `usePlaybackVoice` to the game client imports.

Add after `currentEventId`:

```ts
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const voice = usePlaybackVoice(playback?.voices ?? [], {
    currentEventId,
    enabled: voiceEnabled,
    isPaused: director.isPaused,
  });
  const handleToggleVoice = async () => {
    if (voiceEnabled && voice.connectionState === "error") {
      setVoiceEnabled(false);
      window.setTimeout(() => setVoiceEnabled(true), 0);
      return;
    }
    if (voiceEnabled) {
      setVoiceEnabled(false);
      return;
    }
    const audioUnlocked = await voice.unlockAudio();
    if (audioUnlocked) {
      setVoiceEnabled(true);
    }
  };
```

Pass these props to `MobileLiveTheater`:

```tsx
          onToggleVoice={handleToggleVoice}
          voiceEnabled={voiceEnabled}
          voiceState={voice}
```

- [ ] **Step 4: Run page tests to verify they pass**

Run: `pnpm --dir apps/mobile-web test -- --run src/pages/LiveReplayPage.test.tsx`

Expected: PASS.

## Task 7: Full Verification

**Files:**
- Verify only.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
cd apps/api && uv run pytest \
  tests/test_live_store.py \
  tests/test_voice_store.py \
  tests/test_games_api.py::test_get_game_playback_returns_complete_playback_events \
  tests/test_games_api.py::test_get_game_playback_returns_persisted_events_and_saved_voices \
  tests/test_games_api.py::test_get_game_playback_omits_saved_voices_without_persisted_live_events
```

Expected: PASS.

- [ ] **Step 2: Run focused game client tests**

Run:

```bash
pnpm --dir packages/game-client test -- --run \
  src/api/endpoints.test.ts \
  src/live/livePlaybackVoice.test.tsx \
  src/live/liveVoiceStream.test.tsx
```

Expected: PASS.

- [ ] **Step 3: Run focused mobile tests**

Run:

```bash
pnpm --dir apps/mobile-web test -- --run \
  src/pages/LiveReplayPage.test.tsx \
  src/pages/LivePage.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Check git diff for unrelated user changes**

Run: `git status --short`

Expected: implementation files are changed; pre-existing user edits in `apps/mobile-web/src/components/MobileLiveTheater.tsx`, `apps/mobile-web/src/pages/LivePage.test.tsx`, and `apps/mobile-web/src/styles/index.css` remain unmodified by this work unless the user changed them separately.

## Self-Review Notes

- Spec coverage: Tasks 1 and 3 cover persisted event alignment; Tasks 2 and 3 cover saved voice payloads; Tasks 4 and 5 cover frontend types and local playback; Task 6 covers mobile replay UI integration; Task 7 covers verification.
- Placeholder scan: no unresolved placeholders are intended in this plan.
- Type consistency: backend uses snake_case payload fields matching existing API style; frontend `PlaybackVoiceUtterance` preserves backend field names; `usePlaybackVoice()` returns the same shape consumed by `MobileLiveTheater`.
