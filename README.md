# Python + React Web Monorepo

This repository contains:

- `apps/api`: FastAPI backend
- `apps/web`: React SPA frontend

## Local development

1. Start PostgreSQL:
   - `docker compose up -d db`
2. Install backend dependencies:
   - `cd apps/api && uv sync`
3. Install frontend dependencies:
   - `pnpm install`
4. Start the backend:
   - `make api`
5. Start the frontend:
   - `make web`
