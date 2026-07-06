# Architecture Overview

## Applications

- `apps/api`: FastAPI service exposing `/api/v1/...`
- `apps/web`: Vite React SPA consuming the API
- `apps/mobile-web`: independent Vite React mobile SPA consuming the same API
- `packages/game-client`: shared frontend API client, types, lineup helpers, replay adapters, and live-state derivation

## Local runtime

- PostgreSQL runs in Docker via `docker-compose.yml`
- The API runs locally on `http://localhost:8000`
- The desktop SPA runs locally on `http://localhost:5173`
- The mobile SPA runs locally on `http://localhost:5174`

## Request flow

1. The browser loads the SPA from Vite.
2. React Router renders the page shell.
3. TanStack Query calls `/api/v1/health`.
4. FastAPI responds from the backend.

## Runtime data ownership

- PostgreSQL is the only runtime source for virtual player profiles. Profile API operations return `503` when the database is unavailable.
- Legacy `player_profiles.json` files are migration inputs only and can be imported with `python -m app.cli import-player-profiles --source <path>`.
- Game checkpoints and completed replays are stored in PostgreSQL in `game_sessions` and `game_replay_payloads`.
- Avatar image assets and legacy avatar migration inputs may still use `WEREWOLF_LOGS_DIR`.
- Active live runs and SSE event history are held by the in-process `LiveRunRegistry`; production currently assumes one API worker.
- Resume requests are idempotent per active `session_id` within that process.
