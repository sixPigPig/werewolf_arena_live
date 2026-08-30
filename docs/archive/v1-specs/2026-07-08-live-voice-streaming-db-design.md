# Live Voice True Streaming And Database Design

## Context

The current live voice integration proxies Volcengine TTS through the backend and plays voice on the mobile live page. It is usable for single-viewer experiments, but the browser currently waits for an utterance to finish before building a Blob and playing it. That means the feature is not true audio streaming from the viewer's perspective.

The project is not open to the public and is currently single-user. Rate limiting, multi-tenant permissions, and abuse controls are intentionally out of scope for this iteration. The design should focus on lower latency, a durable live event source, resumable voice playback, and a database foundation for future voiced replay.

Existing storage:

- `game_sessions` stores completed or partial replay metadata.
- `game_replay_payloads` stores full replay state, logs, and checkpoints as JSON.
- `LiveRunRegistry` currently owns in-memory live runs and live events.

## Goals

- Change mobile live voice from completed-Blob playback to true chunk-by-chunk playback.
- Persist live runs and live events so live state is not purely in memory.
- Persist voice utterance metadata and audio chunks as derived data.
- Let a late voice connection recover the current or recent public utterance instead of only listening to future events.
- Keep subtitles and SSE event rendering as the reliable fallback.
- Keep the first production path small enough for single-user local use.

## Non-Goals

- Do not add external/public access controls or rate limiting in this iteration.
- Do not redesign the full game engine storage model.
- Do not require every historical replay to have voice immediately.
- Do not add ASR or user voice interaction.
- Do not assign distinct player voices in the first implementation, but keep the schema ready for it.

## Recommended Approach

Use two durable layers:

1. `live_runs` and `live_events` store the real-time event stream as the durable fact source.
2. `voice_utterances` and `voice_audio_chunks` store generated voice as a replayable derived product.

Use PCM for the first true-streaming playback path. The backend asks Volcengine for `pcm`, forwards each audio chunk to the browser as it arrives, and stores the same chunks with monotonic sequence numbers. The frontend unlocks an `AudioContext` during the user's "enable voice" click, then schedules each PCM chunk as soon as it reaches the correct live event.

MP3 can remain supported as a fallback format for older tests or future download/export, but the live low-latency path should prefer PCM because it avoids waiting for a complete compressed object.

## Data Model

### `live_runs`

Stores durable metadata for a live run.

Columns:

- `run_id`: string primary key, same value currently used by `LiveRunRegistry`.
- `session_id`: string, indexed, references the game session ID.
- `status`: string, one of `queued`, `running`, `completed`, `failed`.
- `villager_model`: string.
- `werewolf_model`: string.
- `seed`: integer nullable.
- `max_rounds`: integer.
- `rule_set_id`: string.
- `rule_set`: JSON nullable.
- `player_configs`: JSON, defaults to an empty list.
- `lineup_quality_warnings`: JSON, defaults to an empty list.
- `winner`: string nullable.
- `error`: text nullable.
- `created_at`: timezone-aware datetime.
- `started_at`: timezone-aware datetime nullable.
- `completed_at`: timezone-aware datetime nullable.
- `updated_at`: timezone-aware datetime.

Indexes:

- `ix_live_runs_session_id`
- `ix_live_runs_status`
- `ix_live_runs_updated_at`

### `live_events`

Stores durable SSE/live events in event ID order.

Columns:

- `run_id`: string, references `live_runs.run_id` with cascade delete.
- `event_id`: integer, event sequence inside a run.
- `session_id`: string.
- `type`: string, indexed.
- `round`: integer nullable.
- `phase`: string nullable.
- `actor`: string nullable.
- `action`: string nullable.
- `payload`: JSON, defaults to an empty object.
- `created_at`: timezone-aware datetime.

Primary key:

- `(run_id, event_id)`

Indexes:

- `ix_live_events_run_id_event_id`
- `ix_live_events_session_id`
- `ix_live_events_type`

The database event IDs must match the in-memory event IDs so existing SSE clients can keep using `Last-Event-ID` and `after_id`.

### `voice_utterances`

Stores one logical spoken unit derived from one or more live events.

Columns:

- `utterance_id`: string primary key.
- `run_id`: string, indexed.
- `session_id`: string, indexed.
- `source_event_id`: integer, first live event that produced this utterance.
- `last_source_event_id`: integer, latest live event included in this utterance.
- `request_id`: string nullable, indexed. Used to group `model_response_delta` events.
- `speaker_kind`: string, `player` or `judge`.
- `speaker_name`: string.
- `speaker`: string. This is the actual vendor speaker ID used for synthesis.
- `action`: string nullable.
- `text`: text. This is the accumulated visible text for the utterance.
- `text_hash`: string, indexed. Stable hash of speaker, format, sample rate, and text for future cache lookup.
- `audio_format`: string, normally `pcm` for live streaming.
- `sample_rate`: integer, normally `24000`.
- `mime_type`: string, normally `audio/L16`.
- `status`: string, one of `receiving_text`, `synthesizing`, `complete`, `failed`, `canceled`.
- `duration_ms`: integer nullable.
- `error_message`: text nullable, sanitized for user-facing diagnostics.
- `created_at`: timezone-aware datetime.
- `updated_at`: timezone-aware datetime.
- `completed_at`: timezone-aware datetime nullable.

Indexes:

- `ix_voice_utterances_run_source_event`
- `ix_voice_utterances_request_id`
- `ix_voice_utterances_text_hash`
- `ix_voice_utterances_status`

### `voice_audio_chunks`

Stores audio chunks for a voice utterance.

Columns:

- `utterance_id`: string, references `voice_utterances.utterance_id` with cascade delete.
- `chunk_index`: integer, ordered from zero.
- `audio`: binary bytes.
- `byte_length`: integer.
- `created_at`: timezone-aware datetime.

Primary key:

- `(utterance_id, chunk_index)`

The implementation can store PCM chunks directly in the database. This is acceptable for single-user local use and keeps replay simple. If audio grows too large later, this table can be replaced or supplemented with object storage paths without changing the live event schema.

## Backend Architecture

### Live Event Persistence

`LiveRunRegistry` should keep its current in-memory API for existing callers, but writes should also go through a persistence adapter:

```text
Game engine
  -> LiveRunRegistry.publish(...)
  -> append in memory
  -> persist live_events row
  -> notify subscribers
```

The persistence adapter should be part of the publish path, not a silent background task:

- If event persistence succeeds, subscribers receive the event normally.
- If event persistence fails, the run should publish a `game_failed` event and stop rather than silently diverging from the database.

Startup recovery can be modest in this iteration:

- Existing active live runs can still be in-memory only after process start.
- The database is introduced for new runs and for future replay queries.
- A later iteration can rehydrate active runs from `live_runs` and `live_events`.

### Voice Stream Service

The voice stream service should split into three responsibilities:

- Event-to-utterance assembly.
- Vendor TTS session management.
- Browser WebSocket forwarding and persistence.

The service should no longer wait for an utterance to complete before audio is useful. It should run two async flows per active utterance:

```text
Live event deltas -> text chunk queue -> Volcengine task_request
Volcengine audio  -> app audio_chunk -> voice_audio_chunks row
```

For player speech, deltas are grouped by `request_id`. Text chunks are flushed to TTS when:

- punctuation arrives,
- enough characters have accumulated,
- no new text arrives within a short flush window,
- the source request ends or a different request starts.

For judge narration, keep short utterances and send them as one text chunk.

### Volcengine Adapter

The adapter should support a long-lived bidirectional session per utterance first. Reusing a session across utterances is optional and can wait until the protocol is stable.

Required timeouts:

- WebSocket connect timeout.
- Connection started timeout.
- Session started timeout.
- First audio chunk timeout.
- Audio idle timeout between chunks.

On timeout or vendor error:

- Mark `voice_utterances.status = failed`.
- Store a sanitized `error_message`.
- Send `voice_error` to the browser.
- Continue processing later utterances.

### Application WebSocket Protocol

Keep the existing JSON message protocol and add PCM metadata.

`voice_start`:

```json
{
  "type": "voice_start",
  "utterance_id": "voice_abc",
  "source_event_id": 42,
  "speaker_kind": "player",
  "speaker_name": "阿青",
  "mime_type": "audio/L16",
  "audio_format": "pcm",
  "sample_rate": 24000
}
```

`audio_chunk`:

```json
{
  "type": "audio_chunk",
  "utterance_id": "voice_abc",
  "chunk_index": 0,
  "mime_type": "audio/L16",
  "audio_format": "pcm",
  "sample_rate": 24000,
  "data": "<base64>"
}
```

`voice_end`:

```json
{
  "type": "voice_end",
  "utterance_id": "voice_abc",
  "duration_ms": 3200
}
```

`voice_error` remains sanitized and should not include raw vendor payloads.

## Frontend Architecture

### Audio Unlock

When the viewer clicks the voice button:

- Create one `AudioContext`.
- Call `audioContext.resume()` inside that click handler.
- Keep the context in the voice hook while voice is enabled.
- Close the context when voice is disabled or the route changes.

This makes later async chunk playback much more reliable on mobile browsers.

### PCM Streaming Playback

Replace Blob playback for the live PCM path with a small scheduler:

1. Decode each base64 `audio_chunk` into PCM bytes.
2. Convert signed 16-bit little-endian PCM into a mono `AudioBuffer`.
3. Schedule the buffer with `AudioBufferSourceNode.start(startTime)`.
4. Maintain `nextPlaybackTime` so chunks play continuously.
5. If playback is paused, suspend the `AudioContext`.
6. If playback resumes, resume the `AudioContext` without rebuilding completed chunks.

The hook should still align audio with `source_event_id`. It can buffer early chunks, but it should start playback as soon as:

- voice is enabled,
- the director has reached `source_event_id`,
- the first playable PCM chunk exists.

### MP3 Fallback

Keep the existing Blob playback code path for non-PCM formats so existing tests and future file-based replay still have a fallback. The live path should choose PCM by default.

### Late Connect Recovery

The voice WebSocket URL should include the director event position:

```text
/api/v1/games/runs/{run_id}/voice-stream?current_event_id=42
```

On connect, the backend should:

- Load recent live events for the run from memory or database.
- If the current event is part of an active public `request_id`, create or resume the corresponding utterance.
- If completed audio chunks already exist for that utterance, replay stored chunks to the browser in order.
- Then subscribe to future events.

This avoids the current behavior where enabling voice mid-speech misses the beginning of the sentence.

## URL And Configuration

`resolveVoiceStreamUrl` should match the normal API client semantics:

- Empty `VITE_API_BASE_URL` means same-origin `/api/v1/...`.
- Absolute `VITE_API_BASE_URL=http://host:port` means `ws://host:port/api/v1/...`.
- Relative `VITE_API_BASE_URL=/api` should not produce `/api/api/v1/...`.

The API docs and `.env.example` should clarify that `ARK_TTS_API_KEY` must have speech/TTS resource permission. It should not be assumed to be interchangeable with a normal chat model key.

## Remaining Optimization Plan

### Player Voices

Keep global `ARK_TTS_PLAYER_SPEAKER` and `ARK_TTS_JUDGE_SPEAKER` for this implementation. Store `speaker` on each `voice_utterance`. Later, add an optional `voice_speaker` field to player profiles and select by actor name.

### Vendor Session Reuse

Do not reuse one vendor session across the whole run in the first implementation. True streaming within an utterance is enough to fix the main latency problem. Session reuse can be added later if connection setup becomes a noticeable delay.

### Replay With Voice

The first database implementation should make voice replay possible but does not need to build the replay UI immediately. Once `voice_audio_chunks` are stored, replay can request chunks for each source event and feed the same PCM scheduler.

### Backfill

No historical backfill is required. Existing completed games can remain text-only unless the user explicitly requests voice generation for a replay.

## Testing

Backend tests:

- Alembic migration creates and drops live and voice tables.
- Live event persistence writes events with stable `(run_id, event_id)`.
- `events_after` can read from the durable store for reconnect paths.
- Voice utterance store creates, updates, completes, and fails utterances.
- Audio chunk store preserves chunk order and bytes.
- Voice stream sends `audio_chunk` before `voice_end`.
- Voice stream resumes a recent utterance on late connect.
- Vendor timeout emits `voice_error`, marks the utterance failed, and continues later utterances.

Frontend tests:

- Voice click creates and resumes `AudioContext`.
- PCM chunks are scheduled before `voice_end`.
- Playback waits for `source_event_id`.
- Pausing suspends audio; resuming resumes audio.
- Route change or disabling voice closes audio resources.
- MP3 fallback still builds a Blob only for non-PCM formats.
- WebSocket URL resolution handles empty, absolute, and `/api` base URLs.

## Rollout

1. Add database models and migrations.
2. Add live event and voice stores with unit tests.
3. Persist new live run events while preserving current in-memory subscribers.
4. Change backend TTS to PCM and forward audio chunks immediately.
5. Change frontend voice hook to use `AudioContext` for PCM.
6. Add late-connect recovery from recent events and stored voice chunks.
7. Update docs and `.env.example`.

Each step should preserve subtitle-only live viewing. If voice fails, the user should still be able to watch the match with text subtitles and director playback.
