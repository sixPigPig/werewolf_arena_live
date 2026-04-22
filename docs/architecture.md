# Architecture Overview

## Applications

- `apps/api`: FastAPI service exposing `/api/v1/...`
- `apps/web`: Vite React SPA consuming the API

## Local runtime

- PostgreSQL runs in Docker via `docker-compose.yml`
- The API runs locally on `http://127.0.0.1:8000`
- The SPA runs locally on `http://127.0.0.1:5173`

## Request flow

1. The browser loads the SPA from Vite.
2. React Router renders the page shell.
3. TanStack Query calls `/api/v1/health`.
4. FastAPI responds from the backend.
