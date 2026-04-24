.PHONY: install dev api web db-up db-down lint test format

install:
	cd apps/api && uv sync
	pnpm install

dev:
	@printf "Run 'make api' and 'make web' in separate terminals.\n"
	@printf "API: http://127.0.0.1:8000\n"
	@printf "Web: http://127.0.0.1:5173\n"

api:
	cd apps/api && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

web:
	cd apps/web && pnpm dev --host 127.0.0.1 --port 5173

db-up:
	docker compose up -d db

db-down:
	docker compose down

lint:
	cd apps/api && uv run ruff check .
	cd apps/web && pnpm lint

format:
	cd apps/api && uv run ruff format .
	cd apps/web && pnpm exec eslint . --fix

test:
	cd apps/api && uv run pytest
	cd apps/web && pnpm test -- --run
