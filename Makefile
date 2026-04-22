.PHONY: install dev api web db-up db-down lint test format

install:
	cd apps/api && uv sync
	pnpm install

dev:
	@printf "Run 'make api' and 'make web' in separate terminals.\n"

api:
	cd apps/api && uv run uvicorn app.main:app --reload

web:
	cd apps/web && pnpm dev

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
