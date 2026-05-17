# Avatar Upload Seat Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let virtual players use uploaded portrait images and replace seat assignment dropdowns with a portrait-card selection flow.

**Architecture:** Store avatar images as local files under the configured werewolf logs directory and persist only image metadata on player profiles. Keep database storage and the existing local-file fallback aligned by adding the same avatar fields to both paths. The lobby UI renders uploaded portraits in the player library, seat cards, and selectable profile cards.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy/Alembic, React, TanStack Query, Vitest, pytest.

---

### Task 1: Backend Avatar Upload And Profile Fields

**Files:**
- Create: `apps/api/app/werewolf/player_avatar_assets.py`
- Create: `apps/api/alembic/versions/20260517_01_add_virtual_player_avatar_image.py`
- Modify: `apps/api/app/api/routes/player_profiles.py`
- Modify: `apps/api/app/models/virtual_player_profile.py`
- Modify: `apps/api/app/werewolf/player_profile_store.py`
- Modify: `apps/api/tests/test_player_profiles_api.py`
- Modify: `apps/api/tests/test_models.py`

- [ ] Add failing pytest coverage for avatar upload, invalid MIME rejection, and profile create/list returning `avatar_image_url`.
- [ ] Implement local avatar asset storage with MIME and size validation.
- [ ] Add profile avatar fields to DB model, migration, API schemas, and local file store.
- [ ] Verify focused API tests pass.

### Task 2: Runtime Player Snapshot Avatar Propagation

**Files:**
- Modify: `apps/api/app/werewolf/player_configs.py`
- Modify: `apps/api/app/werewolf/models.py`
- Modify: `apps/api/app/werewolf/engine.py`
- Modify: `apps/api/app/werewolf/checkpoint.py`
- Modify: `apps/api/tests/test_games_api.py`
- Modify: `apps/api/tests/test_werewolf_runner.py`

- [ ] Add failing tests proving selected profiles carry `avatar_image_url` into game run player configs and player snapshots.
- [ ] Add `avatar_image_url` to serialized player configs and player state.
- [ ] Verify focused backend tests pass.

### Task 3: Frontend Avatar Upload Flow

**Files:**
- Create: `apps/web/src/features/games/api/uploadPlayerAvatar.ts`
- Create: `apps/web/src/features/games/api/uploadPlayerAvatar.test.ts`
- Modify: `apps/web/src/features/games/types.ts`
- Modify: `apps/web/src/pages/components/GamesWorkspace.tsx`
- Modify: `apps/web/src/features/games/components/VirtualPlayerLibrary.tsx`
- Modify: `apps/web/src/pages/GamesPage.test.tsx`

- [ ] Add failing Vitest coverage for upload API and player editor save payload.
- [ ] Replace the appearance selector with an image upload and preview control.
- [ ] Render uploaded images in virtual player cards with a fallback portrait placeholder.
- [ ] Verify focused frontend tests pass.

### Task 4: Reference-Style Seat Selection

**Files:**
- Modify: `apps/web/src/features/games/components/PlayerConfigPanel.tsx`
- Modify: `apps/web/src/features/games/components/CreateGameRunForm.tsx`
- Modify: `apps/web/src/pages/GamesPage.test.tsx`
- Modify: `apps/web/src/styles/index.css`

- [ ] Add failing UI test for selecting a seat and assigning a profile via portrait cards.
- [ ] Replace seat dropdowns with seat cards plus a selectable profile gallery.
- [ ] Keep model override inputs available per occupied seat.
- [ ] Verify focused frontend tests pass.

### Task 5: Full Verification

**Files:**
- No code files.

- [ ] Run `PYTHONPATH=. .venv/bin/python -m pytest` in `apps/api`.
- [ ] Run `pnpm exec vitest run` in `apps/web`.
- [ ] Run `pnpm build:web`.
- [ ] Run `pnpm lint:web`.
- [ ] Run `cd apps/api && .venv/bin/ruff check .`.
- [ ] Use the browser to verify `/games`: upload image, save virtual player, choose that player into a seat, and confirm no visual overlap.
