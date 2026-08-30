# Live Voice Streaming Design

## Context

The mobile live page currently renders a real-time werewolf match from server-sent game events. The page already has a director timeline, stage focus, player subtitles, and live replay support. Voice should be an enhancement layer over that experience: if voice is unavailable, subtitles and the live theater must continue to work normally.

Volcengine Ark Agent Plan speech models support streaming TTS and ASR. This first version only adds streaming TTS for live playback. ASR voice interaction is intentionally out of scope, but the design leaves room to add it later.

Relevant Ark speech settings:

- TTS model: Doubao speech synthesis 2.0.
- Resource ID: `seed-tts-2.0`.
- Recommended low-latency endpoint: `wss://openspeech.bytedance.com/api/v3/plan/tts/bidirection`.
- Required backend-held credentials include `X-Api-Key`, `X-Api-Resource-Id`, and a per-connection `X-Api-Connect-Id`.

References:

- https://www.volcengine.com/docs/82379/2516286?lang=zh
- https://www.volcengine.com/docs/6561/1329505

## Goals

- Add near-real-time voice playback to the mobile live page.
- Keep Volcengine credentials on the backend only.
- Stream audio through the application backend instead of exposing the vendor WebSocket to the browser.
- Use one configured player voice and one configured judge voice for the first version.
- Preserve the current subtitle-first live experience as the reliable fallback.
- Avoid changing replay behavior in this first version.

## Non-Goals

- Do not add ASR or audience voice interaction yet.
- Do not assign a distinct speaker voice per player yet.
- Do not replace the existing SSE event stream.
- Do not make audio playback control the match engine.
- Do not persist generated audio for replay in the first version.

## Recommended Architecture

Use a backend voice proxy with two live channels:

- Existing SSE channel: game events, subtitles, stage state, director timeline.
- New application WebSocket channel: voice stream messages for one live run.

Frontend route:

```text
ws://<api-host>/api/v1/games/runs/{run_id}/voice-stream
```

Backend service:

```text
Live game events
  -> LiveVoiceStreamService
  -> Volcengine bidirectional TTS WebSocket
  -> application voice WebSocket
  -> mobile live audio queue
```

The frontend never talks to Volcengine directly. The backend owns authentication, request shaping, logging, and vendor error handling.

## Backend Components

### `LiveVoiceStreamService`

`LiveVoiceStreamService` coordinates voice for a single run and browser subscriber. It reads live events from `LiveRunRegistry`, filters voice-worthy events, converts text into `VoiceUtterance` records, sends text chunks to Volcengine, and forwards audio chunks to the browser.

It should be independent from `LiveRunRegistry` storage internals. The registry remains the source of game events. Voice is a derived stream.

### `VoiceUtterance`

```python
VoiceUtterance:
    utterance_id: str
    run_id: str
    source_event_id: int
    request_id: str | None
    speaker_kind: Literal["player", "judge"]
    speaker_name: str
    action: str | None
    priority: Literal["player", "judge"]
```

The first version uses a single serial queue per run subscriber. Player speech has higher priority than judge narration. Low-priority judge narration may be dropped if it becomes stale.

### Event Selection

Player speech is generated from public speech actions:

- `debate`
- `sheriff_speech`
- `sheriff_pk_speech`

For player speech, the service should stream text from `model_response_delta` events when possible. It groups deltas by `request_id` and chunks text by punctuation or a conservative character threshold before sending to TTS.

Judge narration is generated from selected high-signal events only:

- phase starts, especially day and night transitions
- game completion
- game failure, if the wording is safe for users
- selected key state updates where a short public line already exists

Judge narration must stay short. It should not read hidden roles, private model reasoning, prompts, or internal debug traces.

### Text Chunking

Text chunks should be emitted to TTS when one of these boundaries is reached:

- Chinese or English sentence punctuation: `，。！？；,.!?;`
- enough characters have accumulated to start useful audio
- the source utterance ends

The chunker should keep punctuation with the preceding text. It should trim whitespace and skip empty chunks.

### Volcengine Session

For each active utterance, the backend opens or reuses a Volcengine bidirectional TTS session. The implementation should prefer the official protocol shape from the Ark speech documentation and keep the protocol encoding isolated in a small adapter module.

Default request settings:

```env
ARK_TTS_ENABLED=false
ARK_TTS_API_KEY=
ARK_TTS_RESOURCE_ID=seed-tts-2.0
ARK_TTS_WS_URL=wss://openspeech.bytedance.com/api/v3/plan/tts/bidirection
ARK_TTS_PLAYER_SPEAKER=zh_female_gaolengyujie_uranus_bigtts
ARK_TTS_JUDGE_SPEAKER=zh_female_vv_uranus_bigtts
ARK_TTS_AUDIO_FORMAT=mp3
ARK_TTS_SAMPLE_RATE=24000
```

Every vendor connection must generate a unique `X-Api-Connect-Id`. Logs should include the run ID, utterance ID, source event ID, connection ID, and vendor log ID when available.

## Application Voice WebSocket Protocol

The backend sends JSON control messages and base64 audio chunks over the application WebSocket.

```json
{
  "type": "voice_start",
  "utterance_id": "voice_abc",
  "source_event_id": 42,
  "speaker_kind": "player",
  "speaker_name": "3号玩家",
  "mime_type": "audio/mpeg"
}
```

```json
{
  "type": "audio_chunk",
  "utterance_id": "voice_abc",
  "mime_type": "audio/mpeg",
  "data": "<base64>"
}
```

```json
{
  "type": "voice_end",
  "utterance_id": "voice_abc",
  "duration_ms": 3200
}
```

```json
{
  "type": "voice_error",
  "utterance_id": "voice_abc",
  "source_event_id": 42,
  "message": "Voice synthesis failed"
}
```

The protocol is intentionally small. It does not expose vendor credentials, raw vendor errors that may contain sensitive data, prompts, hidden roles, or internal model logs.

## Frontend Components

### `useLiveVoiceStream`

The mobile live app adds a hook:

```ts
useLiveVoiceStream(runId, {
  currentEventId,
  isPaused,
  enabled,
})
```

Responsibilities:

- connect to `/api/v1/games/runs/{run_id}/voice-stream` only after user enables voice
- track connection state
- group incoming chunks by `utterance_id`
- create playable browser audio from completed or sufficiently buffered chunks
- align playback with `source_event_id`
- pause audio when the director is paused
- discard stale audio when the director has moved far beyond the source event
- expose current speaker and failure state to the theater controls

### Playback Policy

The first version should require an explicit user click to enable voice. This avoids mobile autoplay restrictions and gives users control.

Playback ordering:

- do not play audio before the director reaches `source_event_id`
- play one utterance at a time
- keep player speech before judge narration
- discard stale judge narration first
- do not alter audio playback rate when the director speed changes

The current subtitle UI remains the authoritative live text. Voice is additive.

### UI

Add one compact voice button to the existing live controls. It should show:

- unavailable, when backend config disables TTS
- off, before the user opts in
- connecting
- playing, with current speaker label
- error, with retry behavior

No new explanatory panel is needed. The control should be understandable from icon, state, and short label.

## Error Handling

- If `ARK_TTS_ENABLED=false` or `ARK_TTS_API_KEY` is empty, the voice endpoint reports unavailable and the frontend keeps the control disabled.
- If Volcengine connection fails, the backend emits `voice_error`, logs connection context, and continues watching later utterances.
- If one utterance fails, skip that utterance and continue the queue.
- If the application WebSocket disconnects, the frontend retries once for the active run.
- If retry fails, the page stays in subtitle mode.
- If audio chunks accumulate too far behind the director, stale judge narration is dropped before player speech.
- If the user pauses the live director, frontend audio pauses too.
- If the run completes, the voice stream drains the current utterance and then closes.

## Testing

Backend tests:

- settings parsing and disabled-state behavior
- event filtering for public speech actions
- judge narration selection avoids hidden/private data
- text chunking by punctuation and length
- queue priority and stale judge narration dropping
- application WebSocket emits the expected protocol messages
- fake Volcengine WebSocket can produce chunk, end, and error paths

Frontend tests:

- hook does not connect until voice is enabled
- hook groups chunks by `utterance_id`
- hook aligns playback with `source_event_id`
- stale audio is discarded
- pause and resume call the audio element correctly
- voice failure leaves subtitles and director state untouched
- theater control renders unavailable, off, connecting, playing, and error states

Regression tests:

- existing mobile live subtitles still pass
- existing live director behavior still passes
- replay pages remain unchanged

Manual verification:

- no API key
- invalid API key
- successful TTS connection
- mobile browser first-click enablement
- pause/resume while audio is playing
- fast event backlog with player speech and judge narration

## Rollout

Ship behind `ARK_TTS_ENABLED=false` by default. The feature becomes visible only when backend config enables it. The first implementation should focus on mobile live page only.

Follow-up work can add per-player speaker mapping, persisted replay audio, ASR audience interaction, or lower-level streaming playback optimizations if the first version proves stable.
