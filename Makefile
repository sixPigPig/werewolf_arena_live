LAN_IP ?= $(shell ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)
LAN_HOST = $(if $(LAN_IP),$(LAN_IP),<your-lan-ip>)
APP_ENVIRONMENT ?= development
ADMIN_DEV_AUTH_ENABLED ?= true
ADMIN_SESSION_COOKIE_SECURE ?= false
PUBLIC_SESSION_COOKIE_SECURE ?= false
API_LOCAL_ENV = APP_ENVIRONMENT=$(APP_ENVIRONMENT) ADMIN_DEV_AUTH_ENABLED=$(ADMIN_DEV_AUTH_ENABLED) ADMIN_SESSION_COOKIE_SECURE=$(ADMIN_SESSION_COOKIE_SECURE) PUBLIC_SESSION_COOKIE_SECURE=$(PUBLIC_SESSION_COOKIE_SECURE)
VITE_ADMIN_AUTH_ENABLED ?= true
VITE_ADMIN_DEV_LOGIN_ENABLED ?= true
VITE_ADMIN_PREVIEW_MODE ?= false
ADMIN_WEB_LOCAL_ENV = VITE_ADMIN_AUTH_ENABLED=$(VITE_ADMIN_AUTH_ENABLED) VITE_ADMIN_DEV_LOGIN_ENABLED=$(VITE_ADMIN_DEV_LOGIN_ENABLED) VITE_ADMIN_PREVIEW_MODE=$(VITE_ADMIN_PREVIEW_MODE)

.PHONY: install dev api web mobile-web admin-web voice-worker db-up db-down lint test build format release-check

install:
	cd apps/api && uv sync
	pnpm install

dev:
	@printf "Run 'make api', 'make web', 'make mobile-web', and 'make admin-web' in separate terminals.\n"
	@printf "API: http://127.0.0.1:8000\n"
	@printf "Web: http://127.0.0.1:5173\n"
	@printf "Mobile Web: http://127.0.0.1:5174\n"
	@printf "Admin Web: http://127.0.0.1:5175\n"
	@printf "LAN Web: http://$(LAN_HOST):5173\n"
	@printf "LAN Mobile Web: http://$(LAN_HOST):5174\n"

api:
	cd apps/api && $(API_LOCAL_ENV) .venv/bin/alembic upgrade head
	cd apps/api && $(API_LOCAL_ENV) .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

web:
	cd apps/web && pnpm dev --host 0.0.0.0 --port 5173

mobile-web:
	cd apps/mobile-web && pnpm dev --host 0.0.0.0 --port 5174

admin-web:
	cd apps/admin-web && $(ADMIN_WEB_LOCAL_ENV) pnpm dev --host 0.0.0.0 --port 5175

voice-worker:
	cd apps/api && $(API_LOCAL_ENV) .venv/bin/python -m app.cli run-judge-voice-worker

db-up:
	docker compose up -d db

db-down:
	docker compose down

lint:
	cd apps/api && .venv/bin/ruff check .
	cd apps/web && pnpm lint
	pnpm --dir packages/game-client typecheck
	pnpm --dir apps/mobile-web lint
	pnpm --dir apps/admin-web lint

format:
	cd apps/api && .venv/bin/ruff format .
	cd apps/web && pnpm exec eslint . --fix

test:
	cd apps/api && .venv/bin/python -m pytest
	cd apps/web && pnpm test -- --run
	pnpm --dir packages/game-client test -- --run
	pnpm --dir apps/mobile-web test -- --run
	pnpm --dir apps/admin-web test -- --run

build:
	pnpm --dir apps/web build
	pnpm --dir apps/mobile-web build
	pnpm --dir apps/admin-web build

release-check: lint test build
	cd apps/api && .venv/bin/alembic check
