# Mobile Web Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an independent `apps/mobile-web` React application that shares the existing FastAPI API and core game logic with `apps/web`, while using px2rem mobile adaptation based on a 375px design width.

**Architecture:** Extract API functions, game types, lineup helpers, replay adapters, and live-event derivation into `packages/game-client`. Keep `apps/web` behavior stable through compatibility re-export files, then build `apps/mobile-web` with its own routes, CSS, layout shell, mobile pages, and tests.

**Tech Stack:** pnpm workspace, React 19, TypeScript 6, Vite 8, TanStack Query 5, React Router 7, Vitest 4, Testing Library, Tailwind 4, `postcss-pxtorem`, FastAPI `/api/v1/...`.

---

## File Structure

- Create: `packages/game-client/package.json` for the shared frontend logic package.
- Create: `packages/game-client/tsconfig.json` for package type checking.
- Create: `packages/game-client/src/index.ts` as the shared public barrel.
- Create: `packages/game-client/src/api/client.ts` and `packages/game-client/src/api/*.ts` for shared API calls.
- Create: `packages/game-client/src/types.ts` from the current game types.
- Create: `packages/game-client/src/lineup/lineupUtils.ts` for lineup helpers.
- Create: `packages/game-client/src/live/*.ts` for live director, labels, status, debug, spectator, god view, and narrative helpers.
- Create: `packages/game-client/src/replay/adapters.ts` for replay normalization.
- Create: `packages/game-client/src/profile/*.ts` for non-UI player profile helpers.
- Modify: `apps/web/package.json` to depend on `@werewolf-arena/game-client`.
- Modify: `apps/web/src/api/client.ts` and selected `apps/web/src/features/games/**/*.ts` pure-logic files into compatibility re-export shims.
- Create: `apps/mobile-web/**` for the independent mobile Vite app.
- Modify: `package.json`, `Makefile`, `README.md`, and `docs/architecture.md` for mobile scripts and runtime docs.

## Task 1: Shared Package Scaffold And API Client

**Files:**
- Create: `packages/game-client/package.json`
- Create: `packages/game-client/tsconfig.json`
- Create: `packages/game-client/src/index.ts`
- Create: `packages/game-client/src/api/client.ts`
- Create: `packages/game-client/src/api/client.test.ts`

- [ ] **Step 1: Write the failing API client test**

```ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "./client";

describe("apiFetch", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("prefixes requests with the configured base URL and parses JSON", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ status: "ok" }), {
        headers: { "content-type": "application/json" },
        status: 200,
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      apiFetch<{ status: string }>("/api/v1/health", undefined, {
        baseUrl: "http://api.test",
      }),
    ).resolves.toEqual({ status: "ok" });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://api.test/api/v1/health",
      undefined,
    );
  });

  it("throws a useful error when the response is not ok", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("nope", { status: 503 })),
    );

    await expect(apiFetch("/api/v1/player-profiles")).rejects.toThrow(
      "Request failed with status 503",
    );
  });

  it("returns undefined for empty 204 responses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 204 })),
    );

    await expect(apiFetch<void>("/api/v1/empty")).resolves.toBeUndefined();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pnpm --dir packages/game-client test -- --run src/api/client.test.ts`

Expected: FAIL because `packages/game-client/package.json` and `src/api/client.ts` do not exist yet.

- [ ] **Step 3: Create the package scaffold**

Create `packages/game-client/package.json`:

```json
{
  "name": "@werewolf-arena/game-client",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "exports": {
    ".": "./src/index.ts",
    "./api": "./src/api/index.ts",
    "./lineup": "./src/lineup/index.ts",
    "./live": "./src/live/index.ts",
    "./profile": "./src/profile/index.ts",
    "./replay": "./src/replay/index.ts"
  },
  "scripts": {
    "test": "vitest",
    "typecheck": "tsc -p tsconfig.json --noEmit"
  },
  "peerDependencies": {
    "react": "^19.2.5"
  },
  "devDependencies": {
    "@types/node": "^24.12.2",
    "typescript": "~6.0.2",
    "vite": "^8.0.9",
    "vitest": "^4.1.5"
  }
}
```

Create `packages/game-client/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "es2023",
    "lib": ["ES2023", "DOM"],
    "module": "esnext",
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "verbatimModuleSyntax": true,
    "moduleDetection": "force",
    "noEmit": true,
    "jsx": "react-jsx",
    "types": ["vite/client", "vitest/globals"],
    "skipLibCheck": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "erasableSyntaxOnly": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"]
}
```

Create `packages/game-client/src/api/client.ts`:

```ts
export type ApiFetchOptions = {
  baseUrl?: string;
};

function defaultApiBaseUrl() {
  const meta = import.meta as ImportMeta & {
    env?: { VITE_API_BASE_URL?: string };
  };

  return meta.env?.VITE_API_BASE_URL ?? "";
}

export async function apiFetch<T>(
  path: string,
  init?: RequestInit,
  options: ApiFetchOptions = {},
): Promise<T> {
  const baseUrl = options.baseUrl ?? defaultApiBaseUrl();
  const response = await fetch(`${baseUrl}${path}`, init);

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }

  if (response.status === 204 || response.status === 205) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
  const body = await response.text();

  if (!body) {
    return undefined as T;
  }

  if (contentType.includes("application/json")) {
    return JSON.parse(body) as T;
  }

  return body as T;
}
```

Create `packages/game-client/src/api/index.ts`:

```ts
export * from "./client";
```

Create `packages/game-client/src/index.ts`:

```ts
export * from "./api";
```

- [ ] **Step 4: Run the package test to verify it passes**

Run: `pnpm --dir packages/game-client test -- --run src/api/client.test.ts`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/game-client
git commit -m "feat: add shared game client package"
```

## Task 2: Move API Types And Endpoint Functions Into Shared Package

**Files:**
- Create: `packages/game-client/src/types.ts`
- Create: `packages/game-client/src/api/createGameRun.ts`
- Create: `packages/game-client/src/api/createPlayerProfile.ts`
- Create: `packages/game-client/src/api/deletePlayerProfile.ts`
- Create: `packages/game-client/src/api/generatePlayerProfileAiDraft.ts`
- Create: `packages/game-client/src/api/getGameDetail.ts`
- Create: `packages/game-client/src/api/getGamePlayback.ts`
- Create: `packages/game-client/src/api/getGameRun.ts`
- Create: `packages/game-client/src/api/listGames.ts`
- Create: `packages/game-client/src/api/listModelOptions.ts`
- Create: `packages/game-client/src/api/listPlayerProfiles.ts`
- Create: `packages/game-client/src/api/listRuleSets.ts`
- Create: `packages/game-client/src/api/resumeGameRun.ts`
- Create: `packages/game-client/src/api/updatePlayerProfile.ts`
- Create: `packages/game-client/src/api/uploadPlayerAvatar.ts`
- Create: `packages/game-client/src/api/endpoints.test.ts`
- Modify: `packages/game-client/src/api/index.ts`
- Modify: `packages/game-client/src/index.ts`

- [ ] **Step 1: Write failing endpoint tests**

```ts
import { afterEach, describe, expect, it, vi } from "vitest";

import { createGameRun } from "./createGameRun";
import { listGames } from "./listGames";
import { listPlayerProfiles } from "./listPlayerProfiles";
import { resumeGameRun } from "./resumeGameRun";

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    headers: { "content-type": "application/json" },
    status: 200,
  });
}

describe("game API endpoints", () => {
  afterEach(() => {
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
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm --dir packages/game-client test -- --run src/api/endpoints.test.ts`

Expected: FAIL because the endpoint modules do not exist.

- [ ] **Step 3: Copy the current type contract into the package**

Run:

```bash
mkdir -p packages/game-client/src/api
cp apps/web/src/features/games/types.ts packages/game-client/src/types.ts
```

Then ensure `packages/game-client/src/types.ts` contains the full current content of `apps/web/src/features/games/types.ts`, including `DEFAULT_PLAYER_PROFILE_DRAFT`, `CreateGameRunRequest`, `GameRun`, `LiveGameEvent`, and replay types.

- [ ] **Step 4: Create endpoint modules**

Use the existing endpoint bodies from `apps/web/src/features/games/api/*.ts`, changing imports to package-local paths. The small endpoint files should follow this pattern:

```ts
import { apiFetch } from "./client";
import type { GameSessionsResponse } from "../types";

export function listGames() {
  return apiFetch<GameSessionsResponse>("/api/v1/games");
}
```

Create `packages/game-client/src/api/createGameRun.ts`:

```ts
import { apiFetch } from "./client";
import type { CreateGameRunRequest, GameRun } from "../types";

export function createGameRun(request: CreateGameRunRequest): Promise<GameRun> {
  return apiFetch<GameRun>("/api/v1/games/runs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}
```

Create `packages/game-client/src/api/resumeGameRun.ts`:

```ts
import { apiFetch } from "./client";
import type { GameRun } from "../types";

export function resumeGameRun(sessionId: string): Promise<GameRun> {
  return apiFetch<GameRun>(`/api/v1/games/${sessionId}/resume`, {
    method: "POST",
  });
}
```

Create the other API files by copying their current request paths and request bodies exactly from `apps/web/src/features/games/api/`, replacing `../../../api/client` with `./client` and `../types` with `../types`.

Update `packages/game-client/src/api/index.ts`:

```ts
export * from "./client";
export * from "./createGameRun";
export * from "./createPlayerProfile";
export * from "./deletePlayerProfile";
export * from "./generatePlayerProfileAiDraft";
export * from "./getGameDetail";
export * from "./getGamePlayback";
export * from "./getGameRun";
export * from "./listGames";
export * from "./listModelOptions";
export * from "./listPlayerProfiles";
export * from "./listRuleSets";
export * from "./resumeGameRun";
export * from "./updatePlayerProfile";
export * from "./uploadPlayerAvatar";
```

Update `packages/game-client/src/index.ts`:

```ts
export * from "./api";
export * from "./types";
```

- [ ] **Step 5: Run endpoint tests to verify they pass**

Run: `pnpm --dir packages/game-client test -- --run src/api/client.test.ts src/api/endpoints.test.ts`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add packages/game-client
git commit -m "feat: share game api client"
```

## Task 3: Move Pure Game Logic Into Shared Package

**Files:**
- Create: `packages/game-client/src/lineup/index.ts`
- Create: `packages/game-client/src/lineup/lineupUtils.ts`
- Create: `packages/game-client/src/live/index.ts`
- Create: `packages/game-client/src/live/liveDebugTrace.ts`
- Create: `packages/game-client/src/live/liveDirector.ts`
- Create: `packages/game-client/src/live/liveGodView.ts`
- Create: `packages/game-client/src/live/liveLabels.ts`
- Create: `packages/game-client/src/live/liveNarrative.ts`
- Create: `packages/game-client/src/live/liveNavStatus.ts`
- Create: `packages/game-client/src/live/liveSpectator.ts`
- Create: `packages/game-client/src/profile/index.ts`
- Create: `packages/game-client/src/profile/playerProfileCreation.ts`
- Create: `packages/game-client/src/profile/playerProfileOptions.ts`
- Create: `packages/game-client/src/profile/playerStrategyOptions.ts`
- Create: `packages/game-client/src/profile/profilePromptPreview.ts`
- Create: `packages/game-client/src/profile/systemPlayerAvatars.ts`
- Create: `packages/game-client/src/replay/index.ts`
- Create: `packages/game-client/src/replay/adapters.ts`
- Modify: `packages/game-client/src/index.ts`

- [ ] **Step 1: Copy existing tests into package paths first**

Run:

```bash
mkdir -p packages/game-client/src/lineup packages/game-client/src/live packages/game-client/src/profile packages/game-client/src/replay
cp apps/web/src/features/games/lineupUtils.test.ts packages/game-client/src/lineup/lineupUtils.test.ts
cp apps/web/src/features/games/liveDirector.test.ts packages/game-client/src/live/liveDirector.test.ts
cp apps/web/src/features/games/liveSpectator.test.ts packages/game-client/src/live/liveSpectator.test.ts
cp apps/web/src/features/games/liveGodView.test.ts packages/game-client/src/live/liveGodView.test.ts
cp apps/web/src/features/games/liveDebugTrace.test.ts packages/game-client/src/live/liveDebugTrace.test.ts
cp apps/web/src/features/games/liveNavStatus.test.ts packages/game-client/src/live/liveNavStatus.test.ts
cp apps/web/src/features/games/liveNarrative.test.ts packages/game-client/src/live/liveNarrative.test.ts
cp apps/web/src/features/games/playerProfileCreation.test.ts packages/game-client/src/profile/playerProfileCreation.test.ts
cp apps/web/src/features/games/api/adapters.test.ts packages/game-client/src/replay/adapters.test.ts
```

- [ ] **Step 2: Run copied tests to verify they fail**

Run:

```bash
pnpm --dir packages/game-client test -- --run \
  src/lineup/lineupUtils.test.ts \
  src/live/liveDirector.test.ts \
  src/live/liveSpectator.test.ts \
  src/live/liveGodView.test.ts \
  src/live/liveDebugTrace.test.ts \
  src/live/liveNavStatus.test.ts \
  src/live/liveNarrative.test.ts \
  src/profile/playerProfileCreation.test.ts \
  src/replay/adapters.test.ts
```

Expected: FAIL because the copied implementation modules do not exist at the new paths.

- [ ] **Step 3: Copy implementation modules**

Run:

```bash
cp apps/web/src/features/games/lineupUtils.ts packages/game-client/src/lineup/lineupUtils.ts
cp apps/web/src/features/games/liveDebugTrace.ts packages/game-client/src/live/liveDebugTrace.ts
cp apps/web/src/features/games/liveDirector.ts packages/game-client/src/live/liveDirector.ts
cp apps/web/src/features/games/liveGodView.ts packages/game-client/src/live/liveGodView.ts
cp apps/web/src/features/games/liveLabels.ts packages/game-client/src/live/liveLabels.ts
cp apps/web/src/features/games/liveNarrative.ts packages/game-client/src/live/liveNarrative.ts
cp apps/web/src/features/games/liveNavStatus.ts packages/game-client/src/live/liveNavStatus.ts
cp apps/web/src/features/games/liveSpectator.ts packages/game-client/src/live/liveSpectator.ts
cp apps/web/src/features/games/playerProfileCreation.ts packages/game-client/src/profile/playerProfileCreation.ts
cp apps/web/src/features/games/playerProfileOptions.ts packages/game-client/src/profile/playerProfileOptions.ts
cp apps/web/src/features/games/playerStrategyOptions.ts packages/game-client/src/profile/playerStrategyOptions.ts
cp apps/web/src/features/games/profilePromptPreview.ts packages/game-client/src/profile/profilePromptPreview.ts
cp apps/web/src/features/games/systemPlayerAvatars.ts packages/game-client/src/profile/systemPlayerAvatars.ts
cp apps/web/src/features/games/api/adapters.ts packages/game-client/src/replay/adapters.ts
cp apps/web/src/features/games/rulePresentation.ts packages/game-client/src/replay/rulePresentation.ts
cp apps/web/src/features/games/sheriffBadgeDisplay.ts packages/game-client/src/replay/sheriffBadgeDisplay.ts
```

Then adjust imports in copied package files:

- Replace `./types` with `../types` in files under `src/lineup`, `src/live`, `src/profile`, and `src/replay`.
- Replace `../types` with `../types` only where the file is now one directory below `src`.
- In `packages/game-client/src/replay/adapters.ts`, replace `../sheriffBadgeDisplay` with `./sheriffBadgeDisplay`.
- In `packages/game-client/src/replay/adapters.ts`, replace `../types` with `../types`.

Create `packages/game-client/src/lineup/index.ts`:

```ts
export * from "./lineupUtils";
```

Create `packages/game-client/src/live/index.ts`:

```ts
export * from "./liveDebugTrace";
export * from "./liveDirector";
export * from "./liveGodView";
export * from "./liveLabels";
export * from "./liveNarrative";
export * from "./liveNavStatus";
export * from "./liveSpectator";
```

Create `packages/game-client/src/profile/index.ts`:

```ts
export * from "./playerProfileCreation";
export * from "./playerProfileOptions";
export * from "./playerStrategyOptions";
export * from "./profilePromptPreview";
export * from "./systemPlayerAvatars";
```

Create `packages/game-client/src/replay/index.ts`:

```ts
export * from "./adapters";
export * from "./rulePresentation";
export * from "./sheriffBadgeDisplay";
```

Update `packages/game-client/src/index.ts`:

```ts
export * from "./api";
export * from "./lineup";
export * from "./live";
export * from "./profile";
export * from "./replay";
export * from "./types";
```

- [ ] **Step 4: Run shared logic tests**

Run:

```bash
pnpm --dir packages/game-client test -- --run \
  src/api/client.test.ts \
  src/api/endpoints.test.ts \
  src/lineup/lineupUtils.test.ts \
  src/live/liveDirector.test.ts \
  src/live/liveSpectator.test.ts \
  src/live/liveGodView.test.ts \
  src/live/liveDebugTrace.test.ts \
  src/live/liveNavStatus.test.ts \
  src/live/liveNarrative.test.ts \
  src/profile/playerProfileCreation.test.ts \
  src/replay/adapters.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/game-client
git commit -m "feat: share game state logic"
```

## Task 4: Wire Existing Web To Shared Package Without Behavior Changes

**Files:**
- Modify: `apps/web/package.json`
- Modify: `apps/web/src/api/client.ts`
- Modify: `apps/web/src/features/games/types.ts`
- Modify: `apps/web/src/features/games/api/*.ts`
- Modify: `apps/web/src/features/games/lineupUtils.ts`
- Modify: `apps/web/src/features/games/liveDebugTrace.ts`
- Modify: `apps/web/src/features/games/liveDirector.ts`
- Modify: `apps/web/src/features/games/liveGodView.ts`
- Modify: `apps/web/src/features/games/liveLabels.ts`
- Modify: `apps/web/src/features/games/liveNarrative.ts`
- Modify: `apps/web/src/features/games/liveNavStatus.ts`
- Modify: `apps/web/src/features/games/liveSpectator.ts`
- Modify: `apps/web/src/features/games/playerProfileCreation.ts`
- Modify: `apps/web/src/features/games/playerProfileOptions.ts`
- Modify: `apps/web/src/features/games/playerStrategyOptions.ts`
- Modify: `apps/web/src/features/games/profilePromptPreview.ts`
- Modify: `apps/web/src/features/games/rulePresentation.ts`
- Modify: `apps/web/src/features/games/sheriffBadgeDisplay.ts`
- Modify: `apps/web/src/features/games/systemPlayerAvatars.ts`
- Modify: `apps/web/src/features/games/api/adapters.ts`

- [ ] **Step 1: Add the workspace dependency**

In `apps/web/package.json`, add:

```json
"@werewolf-arena/game-client": "workspace:*"
```

Run: `pnpm install`

Expected: lockfile updates and `apps/web` can resolve the shared package.

- [ ] **Step 2: Replace old pure-logic files with compatibility re-exports**

Use this exact pattern for `apps/web/src/features/games/types.ts`:

```ts
export * from "@werewolf-arena/game-client";
```

Use this exact pattern for each old API module such as `apps/web/src/features/games/api/listGames.ts`:

```ts
export { listGames } from "@werewolf-arena/game-client";
```

Use this exact pattern for old pure helpers such as `apps/web/src/features/games/lineupUtils.ts`:

```ts
export * from "@werewolf-arena/game-client/lineup";
```

Use this exact pattern for old live helpers such as `apps/web/src/features/games/liveDirector.ts`:

```ts
export * from "@werewolf-arena/game-client/live";
```

Use this exact pattern for old profile helpers such as `apps/web/src/features/games/playerProfileCreation.ts`:

```ts
export * from "@werewolf-arena/game-client/profile";
```

Use this exact pattern for old replay helpers such as `apps/web/src/features/games/api/adapters.ts`:

```ts
export * from "@werewolf-arena/game-client/replay";
```

For `apps/web/src/api/client.ts`, use:

```ts
export { apiFetch } from "@werewolf-arena/game-client/api";
export type { ApiFetchOptions } from "@werewolf-arena/game-client/api";
```

- [ ] **Step 3: Run web tests as migration proof**

Run: `pnpm --dir apps/web test -- --run`

Expected: PASS. Failures mean a re-export missed a named export or the copied package imports are wrong.

- [ ] **Step 4: Run web build**

Run: `pnpm --dir apps/web build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/web package.json pnpm-lock.yaml packages/game-client
git commit -m "refactor: use shared game client in web"
```

## Task 5: Mobile App Scaffold, px2rem, And Routes

**Files:**
- Create: `apps/mobile-web/package.json`
- Create: `apps/mobile-web/index.html`
- Create: `apps/mobile-web/vite.config.ts`
- Create: `apps/mobile-web/postcss.config.cjs`
- Create: `apps/mobile-web/eslint.config.js`
- Create: `apps/mobile-web/tsconfig.json`
- Create: `apps/mobile-web/tsconfig.app.json`
- Create: `apps/mobile-web/tsconfig.node.json`
- Create: `apps/mobile-web/src/main.tsx`
- Create: `apps/mobile-web/src/app/App.tsx`
- Create: `apps/mobile-web/src/lib/query-client.ts`
- Create: `apps/mobile-web/src/routes/definitions.tsx`
- Create: `apps/mobile-web/src/routes/index.tsx`
- Create: `apps/mobile-web/src/styles/rem.ts`
- Create: `apps/mobile-web/src/styles/index.css`
- Create: `apps/mobile-web/src/tests/setup.ts`
- Create: `apps/mobile-web/src/app/App.test.tsx`

- [ ] **Step 1: Write failing scaffold tests**

```tsx
import { render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { RouterProvider, createMemoryRouter } from "react-router-dom";

import { routes } from "../routes/definitions";
import { updateRootFontSize } from "../styles/rem";

describe("mobile app scaffold", () => {
  it("redirects the mobile root route to games", async () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/"] });

    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("heading", { name: "移动大厅" })).toBeInTheDocument();
  });

  it("uses px2rem with the approved 375px baseline", () => {
    const config = readFileSync("postcss.config.cjs", "utf8");

    expect(config).toContain("postcss-pxtorem");
    expect(config).toContain("rootValue: 37.5");
  });

  it("sets 37.5px root font size at a 375px viewport", () => {
    const html = document.documentElement;

    updateRootFontSize(375);

    expect(html.style.fontSize).toBe("37.5px");
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm --dir apps/mobile-web test -- --run src/app/App.test.tsx`

Expected: FAIL because the app does not exist.

- [ ] **Step 3: Create package and install mobile dependencies**

Create `apps/mobile-web/package.json`:

```json
{
  "name": "mobile-web",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite --host 127.0.0.1 --port 5174",
    "build": "tsc -b && vite build",
    "lint": "eslint .",
    "preview": "vite preview",
    "test": "vitest"
  },
  "dependencies": {
    "@tanstack/react-query": "^5.99.2",
    "@werewolf-arena/game-client": "workspace:*",
    "react": "^19.2.5",
    "react-dom": "^19.2.5",
    "react-router-dom": "^7.14.2"
  },
  "devDependencies": {
    "@eslint/js": "^9.39.4",
    "@tailwindcss/vite": "^4.2.4",
    "@testing-library/jest-dom": "^6.9.1",
    "@testing-library/react": "^16.3.2",
    "@testing-library/user-event": "^14.6.1",
    "@types/node": "^24.12.2",
    "@types/react": "^19.2.14",
    "@types/react-dom": "^19.2.3",
    "@vitejs/plugin-react": "^6.0.1",
    "eslint": "^9.39.4",
    "eslint-plugin-react-hooks": "^7.1.1",
    "eslint-plugin-react-refresh": "^0.5.2",
    "globals": "^17.5.0",
    "jsdom": "^29.0.2",
    "postcss-pxtorem": "^6.1.0",
    "tailwindcss": "^4.2.4",
    "typescript": "~6.0.2",
    "typescript-eslint": "^8.58.2",
    "vite": "^8.0.9",
    "vitest": "^4.1.5"
  }
}
```

Run: `pnpm install`

Expected: `postcss-pxtorem` is added to `pnpm-lock.yaml`.

- [ ] **Step 4: Create Vite, PostCSS, TypeScript, and ESLint config**

Create `apps/mobile-web/vite.config.ts`:

```ts
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [tailwindcss(), react()],
  server: {
    port: 5174,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/tests/setup.ts",
  },
});
```

Create `apps/mobile-web/postcss.config.cjs`:

```js
module.exports = {
  plugins: {
    "postcss-pxtorem": {
      rootValue: 37.5,
      propList: ["*"],
      minPixelValue: 2,
      selectorBlackList: ["html"],
      exclude: /node_modules/i,
    },
  },
};
```

Copy `apps/web/eslint.config.js`, `apps/web/tsconfig.json`, `apps/web/tsconfig.app.json`, and `apps/web/tsconfig.node.json` into `apps/mobile-web/`. Keep `include: ["src"]` in `tsconfig.app.json`.

- [ ] **Step 5: Create mobile root and route files**

Create `apps/mobile-web/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
    <title>狼人杀移动竞技场</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Create `apps/mobile-web/src/styles/rem.ts`:

```ts
const MAX_LAYOUT_WIDTH = 480;

export function updateRootFontSize(width = window.innerWidth) {
  const clampedWidth = Math.min(Math.max(width, 320), MAX_LAYOUT_WIDTH);
  document.documentElement.style.fontSize = `${clampedWidth / 10}px`;
}

export function installRootFontSize() {
  updateRootFontSize();
  const handleResize = () => updateRootFontSize();
  window.addEventListener("resize", handleResize);
  window.addEventListener("orientationchange", handleResize);

  return () => {
    window.removeEventListener("resize", handleResize);
    window.removeEventListener("orientationchange", handleResize);
  };
}
```

Create `apps/mobile-web/src/pages/GamesPage.tsx` for the scaffold:

```tsx
export function GamesPage() {
  return (
    <main className="mobile-page" data-testid="mobile-games-page">
      <h1>移动大厅</h1>
      <p>规则、席位和开局操作将在这里呈现。</p>
    </main>
  );
}
```

Create `apps/mobile-web/src/pages/PlayersPage.tsx`:

```tsx
export function PlayersPage() {
  return (
    <main className="mobile-page">
      <h1>玩家图鉴</h1>
    </main>
  );
}
```

Create `apps/mobile-web/src/pages/HistoryPage.tsx`:

```tsx
export function HistoryPage() {
  return (
    <main className="mobile-page">
      <h1>对局历史</h1>
    </main>
  );
}
```

Create `apps/mobile-web/src/pages/LivePage.tsx`:

```tsx
export function LivePage() {
  return (
    <main className="mobile-page">
      <h1>实时观战</h1>
    </main>
  );
}
```

Create `apps/mobile-web/src/pages/PlaybackPage.tsx`:

```tsx
export function PlaybackPage() {
  return (
    <main className="mobile-page">
      <h1>移动复盘</h1>
    </main>
  );
}
```

Create `apps/mobile-web/src/pages/GameDetailPage.tsx`:

```tsx
export function GameDetailPage() {
  return (
    <main className="mobile-page">
      <h1>对局详情</h1>
    </main>
  );
}
```

Create `apps/mobile-web/src/routes/definitions.tsx`:

```tsx
import { Navigate, type RouteObject } from "react-router-dom";

import { GameDetailPage } from "../pages/GameDetailPage";
import { GamesPage } from "../pages/GamesPage";
import { HistoryPage } from "../pages/HistoryPage";
import { LivePage } from "../pages/LivePage";
import { PlaybackPage } from "../pages/PlaybackPage";
import { PlayersPage } from "../pages/PlayersPage";

export const routes: RouteObject[] = [
  { path: "/", element: <Navigate to="/games" replace /> },
  { path: "/games", element: <GamesPage /> },
  { path: "/players", element: <PlayersPage /> },
  { path: "/games/history", element: <HistoryPage /> },
  { path: "/games/live/:runId", element: <LivePage /> },
  { path: "/games/playback/:sessionId", element: <PlaybackPage /> },
  { path: "/games/:sessionId", element: <GameDetailPage /> },
];
```

Create `apps/mobile-web/src/routes/index.tsx`:

```tsx
import { createBrowserRouter } from "react-router-dom";

import { routes } from "./definitions";

export { routes } from "./definitions";

export function createMobileRouter() {
  return createBrowserRouter(routes);
}
```

Create `apps/mobile-web/src/app/App.tsx`:

```tsx
import { RouterProvider } from "react-router-dom";

import { createMobileRouter } from "../routes";

export function App() {
  return <RouterProvider router={createMobileRouter()} />;
}
```

Create `apps/mobile-web/src/lib/query-client.ts`:

```ts
import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 15_000,
    },
  },
});
```

Create `apps/mobile-web/src/main.tsx`:

```tsx
import { QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import ReactDOM from "react-dom/client";

import { App } from "./app/App";
import { queryClient } from "./lib/query-client";
import { installRootFontSize } from "./styles/rem";
import "./styles/index.css";

installRootFontSize();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
```

Create `apps/mobile-web/src/styles/index.css`:

```css
@import "tailwindcss";

:root {
  color: #f4e8d2;
  background: #070a0f;
  font-family: Inter, "Segoe UI", sans-serif;
}

html,
body,
#root {
  min-width: 320px;
  min-height: 100svh;
  margin: 0;
}

body {
  overflow: hidden;
  background: linear-gradient(180deg, #101722 0%, #05070b 100%);
}

button,
input,
select,
textarea {
  font: inherit;
}

.mobile-page {
  min-height: 100svh;
  box-sizing: border-box;
  padding: 24px 16px;
}
```

Create `apps/mobile-web/src/tests/setup.ts` using the same DOM shims as `apps/web/src/tests/setup.ts`.

- [ ] **Step 6: Run scaffold tests**

Run: `pnpm --dir apps/mobile-web test -- --run src/app/App.test.tsx`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add apps/mobile-web package.json pnpm-lock.yaml
git commit -m "feat: scaffold mobile web app"
```

## Task 6: Mobile Shell And Navigation

**Files:**
- Create: `apps/mobile-web/src/layout/MobileAppShell.tsx`
- Create: `apps/mobile-web/src/layout/MobileTabBar.tsx`
- Create: `apps/mobile-web/src/layout/MobileAppShell.test.tsx`
- Modify: `apps/mobile-web/src/routes/definitions.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Write failing shell test**

```tsx
import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { routes } from "../routes/definitions";

describe("MobileAppShell", () => {
  it("renders stable mobile navigation around child pages", async () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/players"] });

    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("heading", { name: "玩家图鉴" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "移动端主导航" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "大厅" })).toHaveAttribute("href", "/games");
    expect(screen.getByRole("link", { name: "玩家" })).toHaveAttribute("href", "/players");
    expect(screen.getByRole("link", { name: "历史" })).toHaveAttribute("href", "/games/history");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir apps/mobile-web test -- --run src/layout/MobileAppShell.test.tsx`

Expected: FAIL because `MobileAppShell` is not used.

- [ ] **Step 3: Implement shell and tab bar**

Create `apps/mobile-web/src/layout/MobileTabBar.tsx`:

```tsx
import { NavLink } from "react-router-dom";

const items = [
  { label: "大厅", to: "/games" },
  { label: "玩家", to: "/players" },
  { label: "历史", to: "/games/history" },
];

export function MobileTabBar() {
  return (
    <nav aria-label="移动端主导航" className="mobile-tab-bar">
      {items.map((item) => (
        <NavLink
          className={({ isActive }) =>
            isActive ? "mobile-tab-link mobile-tab-link-active" : "mobile-tab-link"
          }
          key={item.to}
          to={item.to}
        >
          <span aria-hidden="true" className="mobile-tab-mark" />
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}
```

Create `apps/mobile-web/src/layout/MobileAppShell.tsx`:

```tsx
import { Outlet } from "react-router-dom";

import { MobileTabBar } from "./MobileTabBar";

export function MobileAppShell() {
  return (
    <div className="mobile-app-frame">
      <div className="mobile-app-shell">
        <div className="mobile-content-region">
          <Outlet />
        </div>
        <MobileTabBar />
      </div>
    </div>
  );
}
```

Update `apps/mobile-web/src/routes/definitions.tsx`:

```tsx
import { Navigate, type RouteObject } from "react-router-dom";

import { MobileAppShell } from "../layout/MobileAppShell";
import { GameDetailPage } from "../pages/GameDetailPage";
import { GamesPage } from "../pages/GamesPage";
import { HistoryPage } from "../pages/HistoryPage";
import { LivePage } from "../pages/LivePage";
import { PlaybackPage } from "../pages/PlaybackPage";
import { PlayersPage } from "../pages/PlayersPage";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <MobileAppShell />,
    children: [
      { index: true, element: <Navigate to="/games" replace /> },
      { path: "games", element: <GamesPage /> },
      { path: "players", element: <PlayersPage /> },
      { path: "games/history", element: <HistoryPage /> },
      { path: "games/live/:runId", element: <LivePage /> },
      { path: "games/playback/:sessionId", element: <PlaybackPage /> },
      { path: "games/:sessionId", element: <GameDetailPage /> },
    ],
  },
];
```

Append shell CSS to `apps/mobile-web/src/styles/index.css`:

```css
.mobile-app-frame {
  display: flex;
  height: 100svh;
  min-height: 100svh;
  justify-content: center;
  overflow: hidden;
}

.mobile-app-shell {
  display: flex;
  flex-direction: column;
  width: min(100%, 480px);
  height: 100svh;
  min-height: 100svh;
  background:
    radial-gradient(circle at 50% 0%, rgb(185 147 92 / 16%), transparent 260px),
    linear-gradient(180deg, rgb(11 16 22 / 96%), rgb(5 7 10 / 99%));
  box-shadow: 0 0 80px rgb(0 0 0 / 42%);
}

.mobile-content-region {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  padding: 16px 14px calc(76px + env(safe-area-inset-bottom));
}

.mobile-tab-bar {
  position: fixed;
  right: max(0px, calc((100vw - 480px) / 2));
  bottom: 0;
  left: max(0px, calc((100vw - 480px) / 2));
  z-index: 20;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  width: min(100vw, 480px);
  box-sizing: border-box;
  padding: 8px 8px calc(8px + env(safe-area-inset-bottom));
  border-top: 1px solid rgb(185 147 92 / 32%);
  background: rgb(5 7 10 / 94%);
  backdrop-filter: blur(12px) saturate(130%);
}

.mobile-tab-link {
  display: inline-flex;
  min-width: 0;
  min-height: 44px;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border-radius: 8px;
  color: #aeb9c3;
  font-size: 14px;
  text-decoration: none;
}

.mobile-tab-link-active {
  color: #f3dfbf;
  background: rgb(185 147 92 / 14%);
}

.mobile-tab-mark {
  width: 7px;
  height: 7px;
  border: 1px solid currentColor;
  transform: rotate(45deg);
}
```

- [ ] **Step 4: Run shell and scaffold tests**

Run: `pnpm --dir apps/mobile-web test -- --run src/app/App.test.tsx src/layout/MobileAppShell.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/mobile-web
git commit -m "feat: add mobile app shell"
```

## Task 7: Mobile Games Page And Create Run Flow

**Files:**
- Create: `apps/mobile-web/src/pages/GamesPage.test.tsx`
- Modify: `apps/mobile-web/src/pages/GamesPage.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Write failing create flow test**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { GamesPage } from "./GamesPage";

vi.mock("@werewolf-arena/game-client", async () => {
  const actual = await vi.importActual<typeof import("@werewolf-arena/game-client")>(
    "@werewolf-arena/game-client",
  );
  return {
    ...actual,
    createGameRun: vi.fn(async () => ({
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
    })),
    listPlayerProfiles: vi.fn(async () => ({
      profiles: [
        { id: "p1", display_name: "一号", model: "deepseek", personality_id: "balanced", personality_text: "", short_description: "稳健", background_story: "", speaking_style: "", catchphrases: [], strategy_profile: "balanced", risk_tolerance: 3, bluffing_tendency: 3, trust_tendency: 3, leadership_tendency: 3, talkativeness: 3, example_messages: [], favorite: true, appearance_id: "default", avatar_prompt: "", avatar_image_url: "", avatar_image_mime: "", tags: [], owner_user_id: null, created_at: "", updated_at: "" },
        { id: "p2", display_name: "二号", model: "deepseek", personality_id: "balanced", personality_text: "", short_description: "进攻", background_story: "", speaking_style: "", catchphrases: [], strategy_profile: "balanced", risk_tolerance: 3, bluffing_tendency: 3, trust_tendency: 3, leadership_tendency: 3, talkativeness: 3, example_messages: [], favorite: false, appearance_id: "default", avatar_prompt: "", avatar_image_url: "", avatar_image_mime: "", tags: [], owner_user_id: null, created_at: "", updated_at: "" },
      ],
    })),
    listRuleSets: vi.fn(async () => ({
      rule_sets: [
        { id: "classic_8", version: "1", name: "经典 8 人", player_count: 2, roles: [], role_summary: "测试阵容" },
      ],
    })),
  };
});

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <GamesPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("GamesPage", () => {
  it("loads rules and profiles, fills seats, and starts a run", async () => {
    const user = userEvent.setup();
    const { createGameRun } = await import("@werewolf-arena/game-client");

    renderPage();

    expect(await screen.findByText("经典 8 人")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "随机补齐" }));
    await user.click(screen.getByRole("button", { name: "发起对局" }));

    await waitFor(() => {
      expect(createGameRun).toHaveBeenCalledWith({
        rule_set_id: "classic_8",
        seed: null,
        max_rounds: 8,
        player_configs: [
          { seat: 1, profile_id: expect.any(String) },
          { seat: 2, profile_id: expect.any(String) },
        ],
      });
    });
  });

  it("blocks creation when the player library is too small", async () => {
    renderPage();

    expect(await screen.findByText("经典 8 人")).toBeInTheDocument();
    expect(screen.queryByText("玩家库玩家不足")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir apps/mobile-web test -- --run src/pages/GamesPage.test.tsx`

Expected: FAIL because the page is still a placeholder.

- [ ] **Step 3: Implement mobile create run page**

Implement `apps/mobile-web/src/pages/GamesPage.tsx` with these elements:

- Query `listRuleSets` with key `["rule-sets"]`.
- Query `listPlayerProfiles` with key `["player-profiles"]`.
- State: `selectedRuleSetId`, `playerConfigs`, `seed`, `maxRounds`, `validationError`, `shortage`.
- Use `removeInvalidProfileRefs`, `resizeLineupForPlayerCount`, `randomFillEmptySeats`, and `hasPlayerConfig` from `@werewolf-arena/game-client`.
- Render rule cards as radio buttons.
- Render a seat grid button for each seat.
- Render selected profile names by seat.
- Render player profile buttons for assigning the active seat.
- Buttons: `随机补齐`, `收藏补齐`, `清空席位`, `发起对局`.
- On submit, validate max rounds between 1 and 20, auto-fill remaining seats, show shortage if unique selected profile count is less than `selectedRuleSet.player_count`, then call `createGameRun`.
- On create success, navigate to `/games/live/${run.run_id}`.

Use this normalization helper inside the page:

```ts
function normalizePlayerConfigs(configs: PlayerConfig[], playerCount: number) {
  return configs
    .filter((config) => config.seat >= 1 && config.seat <= playerCount)
    .map((config) => {
      const normalized: PlayerConfig = { seat: config.seat };
      if (config.profile_id) normalized.profile_id = config.profile_id;
      if (config.model?.trim()) normalized.model = config.model.trim();
      if (config.personality_id) normalized.personality_id = config.personality_id;
      if (config.appearance_id) normalized.appearance_id = config.appearance_id;
      return normalized;
    })
    .filter((config) => hasPlayerConfig(config))
    .sort((left, right) => left.seat - right.seat);
}
```

- [ ] **Step 4: Add mobile page CSS**

Add CSS classes for:

- `.mobile-page-section`
- `.mobile-card`
- `.mobile-rule-list`
- `.mobile-choice-row`
- `.mobile-seat-grid`
- `.mobile-seat-button`
- `.mobile-seat-button-active`
- `.mobile-action-bar`
- `.mobile-button`
- `.mobile-button-primary`
- `.mobile-status-banner`

Keep touch targets at least `44px`, and keep bottom action bar above the tab bar.

- [ ] **Step 5: Run tests**

Run: `pnpm --dir apps/mobile-web test -- --run src/pages/GamesPage.test.tsx`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/mobile-web
git commit -m "feat: add mobile game creation flow"
```

## Task 8: Mobile Players Page

**Files:**
- Create: `apps/mobile-web/src/pages/PlayersPage.test.tsx`
- Modify: `apps/mobile-web/src/pages/PlayersPage.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Write failing players page test**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PlayersPage } from "./PlayersPage";

vi.mock("@werewolf-arena/game-client", () => ({
  listPlayerProfiles: vi.fn(async () => ({
    profiles: [
      {
        id: "p1",
        owner_user_id: null,
        display_name: "月下猎人",
        model: "deepseek-v4-flash",
        personality_id: "analytical",
        personality_text: "",
        short_description: "冷静复盘型玩家",
        background_story: "",
        speaking_style: "短句推进",
        catchphrases: [],
        strategy_profile: "logic_leader",
        risk_tolerance: 2,
        bluffing_tendency: 2,
        trust_tendency: 3,
        leadership_tendency: 5,
        talkativeness: 4,
        example_messages: [],
        favorite: true,
        appearance_id: "default",
        avatar_prompt: "",
        avatar_image_url: "",
        avatar_image_mime: "",
        tags: ["控场"],
        created_at: "",
        updated_at: "",
      },
    ],
  })),
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <PlayersPage />
    </QueryClientProvider>,
  );
}

describe("PlayersPage", () => {
  it("renders read-only mobile player cards", async () => {
    renderPage();

    expect(await screen.findByText("月下猎人")).toBeInTheDocument();
    expect(screen.getByText("deepseek-v4-flash")).toBeInTheDocument();
    expect(screen.getByText("冷静复盘型玩家")).toBeInTheDocument();
    expect(screen.getByText("控场")).toBeInTheDocument();
    expect(screen.getByText("编辑能力不在第一版范围内")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm --dir apps/mobile-web test -- --run src/pages/PlayersPage.test.tsx`

Expected: FAIL because the page is still a placeholder.

- [ ] **Step 3: Implement read-only player page**

Implement `PlayersPage` using `useQuery({ queryKey: ["player-profiles"], queryFn: listPlayerProfiles })`.

Render:

- heading `玩家图鉴`
- loading text `正在读取玩家档案...`
- error text `无法读取玩家档案`
- empty text `暂无玩家档案`
- player cards with avatar image when `avatar_image_url` exists, display name, model, short description, favorite badge, tags, and speaking style.
- informational text `编辑能力不在第一版范围内`.

- [ ] **Step 4: Run players page test**

Run: `pnpm --dir apps/mobile-web test -- --run src/pages/PlayersPage.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/mobile-web
git commit -m "feat: add mobile players page"
```

## Task 9: Mobile History And Playback Pages

**Files:**
- Create: `apps/mobile-web/src/pages/HistoryPage.test.tsx`
- Create: `apps/mobile-web/src/pages/PlaybackPage.test.tsx`
- Modify: `apps/mobile-web/src/pages/HistoryPage.tsx`
- Modify: `apps/mobile-web/src/pages/PlaybackPage.tsx`
- Modify: `apps/mobile-web/src/pages/GameDetailPage.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Write failing history test**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { HistoryPage } from "./HistoryPage";

vi.mock("@werewolf-arena/game-client", () => ({
  listGames: vi.fn(async () => ({
    sessions: [
      {
        session_id: "session-1",
        status: "partial",
        winner: null,
        round_count: 3,
        created_at: "2026-06-19T00:00:00Z",
        rule_set: { id: "classic_8", version: "1", name: "经典 8 人", player_count: 8, roles: [] },
        resumable: true,
      },
    ],
  })),
  resumeGameRun: vi.fn(async () => ({
    run_id: "run-resumed",
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
  })),
}));

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <HistoryPage />
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

describe("HistoryPage", () => {
  it("renders session cards and exposes resume for resumable sessions", async () => {
    const user = userEvent.setup();
    const { resumeGameRun } = await import("@werewolf-arena/game-client");

    renderPage();

    expect(await screen.findByText("session-1")).toBeInTheDocument();
    expect(screen.getByText("经典 8 人")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "继续对局" }));

    expect(resumeGameRun).toHaveBeenCalledWith("session-1");
  });
});
```

- [ ] **Step 2: Write failing playback test**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { PlaybackPage } from "./PlaybackPage";

vi.mock("@werewolf-arena/game-client", () => ({
  getGamePlayback: vi.fn(async () => ({
    session_id: "session-1",
    status: "complete",
    state: {
      session_id: "session-1",
      winner: "villagers",
      error_message: "",
      players: [],
      rounds: [{ number: 1, debate: [], bids: [], votes: [], summaries: {}, players: [], eliminated: null, protected: null, investigated: null, exiled: null, success: true }],
    },
    logs: [],
  })),
}));

describe("PlaybackPage", () => {
  it("renders a mobile replay summary", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <MemoryRouter initialEntries={["/games/playback/session-1"]}>
        <QueryClientProvider client={queryClient}>
          <Routes>
            <Route path="/games/playback/:sessionId" element={<PlaybackPage />} />
          </Routes>
        </QueryClientProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText("移动复盘")).toBeInTheDocument();
    expect(screen.getByText("session-1")).toBeInTheDocument();
    expect(screen.getByText("villagers")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pnpm --dir apps/mobile-web test -- --run src/pages/HistoryPage.test.tsx src/pages/PlaybackPage.test.tsx`

Expected: FAIL because both pages are placeholders.

- [ ] **Step 4: Implement history and playback**

History page:

- Use `listGames`.
- Render refresh button.
- Render mobile cards for sessions.
- Show rule name, status, winner, round count, created date.
- Show `继续对局` when `session.resumable` or `session.status === "partial"`.
- Use `resumeGameRun`; on success navigate to `/games/live/${run.run_id}`.
- Link completed sessions to `/games/playback/${session.session_id}`.

Playback page:

- Use `useParams` for `sessionId`.
- Use `getGamePlayback`.
- Render heading `移动复盘`.
- Render session id, status, winner, player count, round count.
- Render round summaries in collapsible `<details>` blocks.

`GameDetailPage` should redirect to `/games/playback/:sessionId`:

```tsx
import { Navigate, useParams } from "react-router-dom";

export function GameDetailPage() {
  const { sessionId } = useParams();

  return <Navigate replace to={`/games/playback/${sessionId ?? ""}`} />;
}
```

- [ ] **Step 5: Run history and playback tests**

Run: `pnpm --dir apps/mobile-web test -- --run src/pages/HistoryPage.test.tsx src/pages/PlaybackPage.test.tsx`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/mobile-web
git commit -m "feat: add mobile history and playback"
```

## Task 10: Mobile Live Page

**Files:**
- Create: `packages/game-client/src/live/useGameRunEvents.ts`
- Create: `packages/game-client/src/live/useGameRunEvents.test.tsx`
- Modify: `packages/game-client/src/live/index.ts`
- Create: `apps/mobile-web/src/pages/LivePage.test.tsx`
- Modify: `apps/mobile-web/src/pages/LivePage.tsx`
- Modify: `apps/mobile-web/src/styles/index.css`

- [ ] **Step 1: Move SSE hook into shared package with a failing test**

Create `packages/game-client/src/live/useGameRunEvents.test.tsx` by copying `apps/web/src/features/games/hooks/useGameRunEvents.test.tsx` and changing imports to:

```ts
import { useGameRunEvents } from "./useGameRunEvents";
```

Run: `pnpm --dir packages/game-client test -- --run src/live/useGameRunEvents.test.tsx`

Expected: FAIL because the shared hook does not exist.

- [ ] **Step 2: Implement shared hook**

Copy `apps/web/src/features/games/hooks/useGameRunEvents.ts` to `packages/game-client/src/live/useGameRunEvents.ts`, changing the type import to:

```ts
import type { LiveGameEvent } from "../types";
```

Export it from `packages/game-client/src/live/index.ts`:

```ts
export * from "./useGameRunEvents";
```

Replace `apps/web/src/features/games/hooks/useGameRunEvents.ts` with:

```ts
export * from "@werewolf-arena/game-client/live";
```

- [ ] **Step 3: Run shared hook and web live tests**

Run:

```bash
pnpm --dir packages/game-client test -- --run src/live/useGameRunEvents.test.tsx
pnpm --dir apps/web test -- --run src/features/games/hooks/useGameRunEvents.test.tsx src/pages/LiveGamePage.test.tsx
```

Expected: PASS.

- [ ] **Step 4: Write failing mobile live page test**

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { LivePage } from "./LivePage";

vi.mock("@werewolf-arena/game-client", async () => {
  const actual = await vi.importActual<typeof import("@werewolf-arena/game-client")>(
    "@werewolf-arena/game-client",
  );
  return {
    ...actual,
    getGameRun: vi.fn(async () => ({
      run_id: "run-1",
      session_id: "session-1",
      villager_model: "",
      werewolf_model: "",
      rule_set: { id: "classic_8", version: "1", name: "经典 8 人", player_count: 8, roles: [] },
      seed: null,
      max_rounds: 8,
      winner: null,
      status: "running",
      created_at: "2026-06-19T00:00:00Z",
      started_at: "2026-06-19T00:00:00Z",
      completed_at: null,
      error: null,
      event_count: 1,
    })),
    useGameRunEvents: () => ({
      connectionState: "open",
      events: [
        {
          id: 1,
          type: "game_started",
          run_id: "run-1",
          session_id: "session-1",
          created_at: "2026-06-19T00:00:00Z",
          round: null,
          phase: null,
          actor: null,
          action: null,
          payload: { players: [] },
        },
      ],
      latestEvent: {
        id: 1,
        type: "game_started",
        run_id: "run-1",
        session_id: "session-1",
        created_at: "2026-06-19T00:00:00Z",
        round: null,
        phase: null,
        actor: null,
        action: null,
        payload: { players: [] },
      },
    }),
  };
});

describe("LivePage", () => {
  it("renders live status and current event from the shared live logic", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

    render(
      <MemoryRouter initialEntries={["/games/live/run-1"]}>
        <QueryClientProvider client={queryClient}>
          <Routes>
            <Route path="/games/live/:runId" element={<LivePage />} />
          </Routes>
        </QueryClientProvider>
      </MemoryRouter>,
    );

    expect(await screen.findByText("实时观战")).toBeInTheDocument();
    expect(screen.getByText("经典 8 人")).toBeInTheDocument();
    expect(screen.getByText("连接正常")).toBeInTheDocument();
    expect(screen.getByText("game_started")).toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Run mobile live test to verify it fails**

Run: `pnpm --dir apps/mobile-web test -- --run src/pages/LivePage.test.tsx`

Expected: FAIL because the live page is a placeholder.

- [ ] **Step 6: Implement mobile live page**

Use:

- `getGameRun`
- `resumeGameRun`
- `useGameRunEvents`
- `useLiveDirector`
- `deriveLiveSpectatorState`
- `deriveGodViewState`
- `deriveLiveNavStatus`

Render:

- heading `实时观战`
- rule name
- session id
- connection label
- current event type
- current round and phase
- player seat overview when players exist
- buttons: `暂停/继续`, `1x/2x`, `追到最新`
- failed run action: `继续对局`
- terminal action: `查看复盘`

Use this connection label helper:

```ts
function connectionLabel(state: string) {
  if (state === "open") return "连接正常";
  if (state === "connecting") return "正在连接";
  if (state === "error") return "连接中断";
  if (state === "closed") return "连接已关闭";
  return "等待连接";
}
```

- [ ] **Step 7: Run tests**

Run:

```bash
pnpm --dir packages/game-client test -- --run src/live/useGameRunEvents.test.tsx
pnpm --dir apps/mobile-web test -- --run src/pages/LivePage.test.tsx
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add packages/game-client apps/web apps/mobile-web
git commit -m "feat: add mobile live view"
```

## Task 11: Scripts, Docs, And Full Verification

**Files:**
- Modify: `package.json`
- Modify: `Makefile`
- Modify: `README.md`
- Modify: `docs/architecture.md`

- [ ] **Step 1: Add root scripts**

Update root `package.json` scripts:

```json
{
  "dev:web": "pnpm --dir apps/web dev",
  "build:web": "pnpm --dir apps/web build",
  "lint:web": "pnpm --dir apps/web lint",
  "test:web": "pnpm --dir apps/web test -- --run",
  "dev:mobile": "pnpm --dir apps/mobile-web dev",
  "build:mobile": "pnpm --dir apps/mobile-web build",
  "lint:mobile": "pnpm --dir apps/mobile-web lint",
  "test:mobile": "pnpm --dir apps/mobile-web test -- --run",
  "test:game-client": "pnpm --dir packages/game-client test -- --run"
}
```

- [ ] **Step 2: Add Makefile target**

Update `.PHONY` to include `mobile-web`.

Add:

```make
mobile-web:
	cd apps/mobile-web && pnpm dev --host 127.0.0.1 --port 5174
```

Keep existing `web` target unchanged.

- [ ] **Step 3: Update README**

Add mobile local runtime docs:

````md
终端 3，启动移动端 Web：

```bash
make mobile-web
```

移动端地址：

```text
http://127.0.0.1:5174
```

移动端和桌面端共用 `/api/v1/...`，开发服务器会把 `/api` 代理到 `http://localhost:8000`。
````

Add quality checks:

```bash
pnpm --dir packages/game-client test -- --run
pnpm --dir apps/mobile-web test -- --run
pnpm --dir apps/mobile-web build
```

- [ ] **Step 4: Update architecture doc**

Update `docs/architecture.md` applications section:

```md
- `apps/api`: FastAPI service exposing `/api/v1/...`
- `apps/web`: Vite React desktop SPA consuming the API
- `apps/mobile-web`: independent Vite React mobile SPA consuming the same API
- `packages/game-client`: shared frontend API client, types, lineup helpers, replay adapters, and live-state derivation
```

Update local runtime ports:

```md
- The desktop SPA runs locally on `http://localhost:5173`
- The mobile SPA runs locally on `http://localhost:5174`
```

- [ ] **Step 5: Run complete verification**

Run:

```bash
pnpm --dir packages/game-client test -- --run
pnpm --dir apps/web test -- --run
pnpm --dir apps/mobile-web test -- --run
pnpm --dir packages/game-client typecheck
pnpm --dir apps/web build
pnpm --dir apps/mobile-web build
```

Expected: all commands PASS.

- [ ] **Step 6: Commit**

```bash
git add package.json pnpm-lock.yaml Makefile README.md docs/architecture.md packages/game-client apps/web apps/mobile-web
git commit -m "docs: document mobile web runtime"
```

## Self-Review

- Spec coverage: The plan covers the independent mobile app, shared API and logic package, current web compatibility, complete core flow pages, px2rem 375px adaptation, player management scope, live viewing, history, playback, scripts, docs, and verification.
- Placeholder scan: The plan contains exact paths, commands, tests, expected failures, expected passes, and implementation details for each task.
- Type consistency: Shared exports use `@werewolf-arena/game-client`, subpath exports use `/api`, `/lineup`, `/live`, `/profile`, and `/replay`; mobile route paths match the approved spec.
