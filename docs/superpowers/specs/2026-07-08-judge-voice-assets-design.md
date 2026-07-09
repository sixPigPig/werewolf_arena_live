# Judge Voice Assets Design

## Goal

Add a web tool that pre-generates Werewolf judge / host voice lines and saves them as static web assets so future games can reuse audio without calling TTS at game start.

## Scope

- Provide a curated set of common Werewolf judge lines from the previously gathered host script.
- Generate audio with the existing Volcengine TTS client and configured judge speaker.
- Use a dedicated static-asset audio format setting, defaulting to MP3, so browser previews and later startup reuse work independently of the realtime voice stream's PCM default.
- Store generated files under `apps/web/public/judge-voice/`.
- Write a `manifest.json` in that folder so future runtime code can map line ids to public URLs.
- Add a web page at `/judge-voice-assets` to inspect, generate, regenerate, and preview assets.

## Architecture

The backend owns synthesis and file writes because browser code cannot reliably write static project files or access TTS credentials. A new `judge_voice_assets` service exposes the fixed script list, scans existing static files, and generates missing or selected files via the existing `VolcengineTtsClient`. A new API router exposes list and generate endpoints.

The web page calls those endpoints with React Query. It displays line id, script text, asset status, and an audio preview when a file exists. The page does not contain TTS credentials and does not synthesize audio directly.

## Static Asset Contract

- Directory: `apps/web/public/judge-voice/`
- Audio file name: `<line_id>.<asset_audio_format>`
- Manifest path: `apps/web/public/judge-voice/manifest.json`
- Public URL: `/judge-voice/<filename>`
- Manifest includes: generated timestamp, asset audio format, sample rate, mime type, and line records.

## Initial Lines

The initial catalog contains standard public host lines:

- Night start and night role prompts.
- Sheriff election prompts.
- Dawn, death, peaceful-night, last words, speaking-order, exile vote, and exile result prompts.
- Special public events: werewolf self-explosion, hunter shot, idiot reveal, badge transfer, badge destroyed.
- Endgame winner announcements.

Dynamic values use spoken placeholders such as `{玩家}` and `{阵营}`. Single-player placeholders are expanded into seat-number variants; multi-player or open-ended placeholders remain as template lines.

## Seat Number Variants

Lines with a single `{玩家}` placeholder are treated as player-seat templates instead of standalone generated audio. The generator expands each of these templates into 12 concrete static assets using `1号玩家` through `12号玩家`.

For example, `{玩家}请发言。` expands to `1号玩家请发言。` ... `12号玩家请发言。`. The page groups these 12 variants under a collapsed panel named after the template. Opening the panel shows each seat-number line and its preview.

Lines with `{玩家列表}` or `{名单}` remain template lines and are not expanded, because multi-player combinations are unbounded.

## Error Handling

- If TTS is disabled or misconfigured, the generate endpoint returns `503`.
- Unknown requested line ids return `422`.
- Vendor synthesis failures return `502`.
- Existing files are skipped unless `force` is true.

## Testing

- Backend unit tests cover line catalog listing, file status scanning, generation with a fake TTS client, manifest writing, skip behavior, and API error handling.
- Web tests cover loading the page, displaying existing audio previews, and triggering generation.
