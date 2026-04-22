# Web App

This package contains the Vite React frontend for the monorepo.

- Copy `.env.example` to `.env` and keep `VITE_API_BASE_URL=http://localhost:8000` for local development.
- Start the app from the repo root with `make web`, or from this directory with `pnpm dev`.
- The SPA expects the API to be running locally and serves the health check through `/api/v1/health`.
