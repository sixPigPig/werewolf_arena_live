# Judge Voice Assets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a static judge voice asset generator page backed by the existing Volcengine TTS client.

**Architecture:** Add a backend service for the fixed judge line catalog, static asset scanning, TTS generation, and manifest writing. Add a FastAPI router for list/generate endpoints using a dedicated MP3-by-default static asset format, then add a React Query page at `/judge-voice-assets` for inspecting and generating assets.

**Tech Stack:** FastAPI, pytest, Volcengine websocket TTS client, React 19, React Router, React Query, Vitest.

---

### Task 1: Backend Catalog And Generator

**Files:**
- Create: `apps/api/app/werewolf/judge_voice_assets.py`
- Create: `apps/api/tests/test_judge_voice_assets.py`

- [ ] Write failing pytest coverage for catalog listing and generation with a fake async TTS client.
- [ ] Run `cd apps/api && uv run pytest tests/test_judge_voice_assets.py -q` and confirm failures reference the missing module.
- [ ] Implement `JudgeVoiceLine`, fixed `JUDGE_VOICE_LINES`, asset listing, async generation, and manifest writing.
- [ ] Re-run the test and confirm it passes.

### Task 2: Backend API

**Files:**
- Create: `apps/api/app/api/routes/judge_voice_assets.py`
- Modify: `apps/api/app/api/router.py`
- Create: `apps/api/tests/test_judge_voice_assets_api.py`

- [ ] Write failing API tests for `GET /api/v1/judge-voice-lines`, `POST /api/v1/judge-voice-lines/generate`, disabled TTS, and unknown ids.
- [ ] Run `cd apps/api && uv run pytest tests/test_judge_voice_assets_api.py -q` and confirm failures.
- [ ] Implement request/response models and route dependency wiring.
- [ ] Re-run API tests and confirm they pass.

### Task 3: Web API And Page

**Files:**
- Create: `apps/web/src/features/judgeVoice/api.ts`
- Create: `apps/web/src/pages/JudgeVoiceAssetsPage.tsx`
- Create: `apps/web/src/pages/JudgeVoiceAssetsPage.test.tsx`
- Modify: `apps/web/src/routes/definitions.tsx`

- [ ] Write failing Vitest coverage for rendering listed lines, audio previews, and generation.
- [ ] Run `pnpm --dir apps/web test -- --run src/pages/JudgeVoiceAssetsPage.test.tsx` and confirm failures.
- [ ] Implement web API helpers, the page UI, and the route.
- [ ] Re-run the page test and confirm it passes.

### Task 4: Verification

**Files:**
- Existing backend and web files touched above.

- [ ] Run `cd apps/api && uv run pytest tests/test_judge_voice_assets.py tests/test_judge_voice_assets_api.py tests/test_volcengine_tts.py -q`.
- [ ] Run `pnpm --dir apps/web test -- --run src/pages/JudgeVoiceAssetsPage.test.tsx`.
- [ ] Run `pnpm --dir apps/web build`.
- [ ] Report any external TTS generation limitation if local `.env` has TTS disabled.

### Task 5: Seat Number Variants

**Files:**
- Modify: `apps/api/app/werewolf/judge_voice_assets.py`
- Modify: `apps/api/tests/test_judge_voice_assets.py`
- Modify: `apps/web/src/pages/JudgeVoiceAssetsPage.tsx`
- Modify: `apps/web/src/pages/JudgeVoiceAssetsPage.test.tsx`
- Regenerate: `apps/web/public/judge-voice/*`

- [ ] Write failing backend tests for expanding a `{玩家}` template into 12 seat-number assets.
- [ ] Write failing web tests for collapsed `{玩家}` template panels and expanding to reveal `10号玩家请发言。`.
- [ ] Implement backend expansion metadata with `template_id` and `seat_number`.
- [ ] Implement grouped UI with collapsible template panels.
- [ ] Regenerate MP3 assets and manifest.
- [ ] Run backend, frontend, and build verification.
