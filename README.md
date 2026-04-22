# Python + React Web Monorepo

## Repository layout

- `apps/api`: FastAPI backend
- `apps/web`: React SPA frontend
- `docs`: architecture and planning docs

## Quick start

1. Copy environment files:
   - `cp apps/api/.env.example apps/api/.env`
   - `cp apps/web/.env.example apps/web/.env`
2. Start PostgreSQL:
   - `docker compose up -d db`
3. Install dependencies:
   - `cd apps/api && uv sync`
   - `pnpm install`
4. Run migrations:
   - `cd apps/api && uv run alembic upgrade head`
5. Start the backend:
   - `make api`
6. Start the frontend:
   - `make web`

## Quality checks

- `make lint`
- `make test`
- `cd apps/web && pnpm build`
