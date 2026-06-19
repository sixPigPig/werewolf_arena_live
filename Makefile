.PHONY: install dev api web mobile-web db-up db-down lint test format

install:
	cd apps/api && uv sync
	pnpm install

dev:
	@printf "Run 'make api', 'make web', and 'make mobile-web' in separate terminals.\n"
	@printf "API: http://127.0.0.1:8000\n"
	@printf "Web: http://127.0.0.1:5173\n"
	@printf "Mobile Web: http://127.0.0.1:5174\n"

api:
	cd apps/api && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

web:
	cd apps/web && pnpm dev --host 127.0.0.1 --port 5173

mobile-web:
	cd apps/mobile-web && pnpm dev --host 127.0.0.1 --port 5174

db-up:
	docker compose up -d db

db-down:
	docker compose down

lint:
	cd apps/api && .venv/bin/ruff check .
	cd apps/web && pnpm lint

format:
	cd apps/api && .venv/bin/ruff format .
	cd apps/web && pnpm exec eslint . --fix

test:
	cd apps/api && .venv/bin/python -m pytest
	cd apps/web && pnpm test -- --run
