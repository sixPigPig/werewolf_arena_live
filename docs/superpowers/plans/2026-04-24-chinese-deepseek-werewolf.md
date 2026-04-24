# Chinese DeepSeek Werewolf Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the simplified local Werewolf runner with a Chinese prompt-driven game engine that uses DeepSeek for all player decisions while remaining testable without real network calls.

**Architecture:** Keep the backend-only `app.werewolf` package. Add Chinese prompt builders, an LLM client abstraction, a DeepSeek JSON provider, richer player state, and a game engine closer to the reference project flow: night actions, bidding, debate, voting, summaries, observations, and full model-call logs.

**Tech Stack:** Python 3.12, argparse, dataclasses, urllib, pytest, ruff

---

## Task 1: Chinese Prompt And JSON Generation Layer

**Files:**
- Create: `apps/api/tests/test_werewolf_lm.py`
- Create: `apps/api/app/werewolf/prompts_zh.py`
- Create: `apps/api/app/werewolf/lm.py`
- Create: `apps/api/app/werewolf/providers.py`
- Modify: `apps/api/.env.example`

- [ ] Write failing tests for Chinese prompt rendering, JSON parsing, allowed-value retry, and DeepSeek provider configuration.
- [ ] Verify the tests fail because the new modules do not exist.
- [ ] Implement Chinese prompt builders for `bid`, `debate`, `vote`, `investigate`, `remove`, `protect`, and `summarize`.
- [ ] Implement `LmLog`, `ModelProvider`, `FakeProvider`, `DeepSeekProvider`, and `generate_action`.
- [ ] Update `.env.example` with `DEEPSEEK_API_KEY=`, `DEEPSEEK_BASE_URL=https://api.deepseek.com`, and `DEEPSEEK_MODEL=deepseek-chat`, without committing any real key.
- [ ] Run `tests/test_werewolf_lm.py`.

## Task 2: Reference-Style Chinese Game State And Engine

**Files:**
- Modify: `apps/api/app/werewolf/models.py`
- Modify: `apps/api/app/werewolf/engine.py`
- Modify: `apps/api/app/werewolf/config.py`
- Modify: `apps/api/app/werewolf/runner.py`
- Modify: `apps/api/tests/test_werewolf_runner.py`

- [ ] Write failing tests that prove a fake LLM game runs with Chinese output, logs prompts/raw responses/results, records summaries, and preserves observations.
- [ ] Verify the tests fail against the simplified fixed-choice engine.
- [ ] Restore richer state concepts from the reference project: player game view, observations, other-wolf context, seer investigation history, bidding rationale, per-action LLM logs, debate, votes, and summaries.
- [ ] Run the game through provider-backed actions rather than `LocalModel`.
- [ ] Keep `max_rounds` partial-log behavior.
- [ ] Run runner tests.

## Task 3: CLI Defaults And Backend-Only Smoke Path

**Files:**
- Modify: `apps/api/app/cli.py`
- Modify: `apps/api/tests/test_werewolf_cli.py`

- [ ] Write failing tests showing `run-game` defaults both camps to `deepseek-chat`, prints Chinese summary fields, and still supports `serve`.
- [ ] Verify the tests fail against the current CLI.
- [ ] Update CLI defaults and output.
- [ ] Run CLI tests.

## Task 4: Verification

**Files:**
- No frontend files.

- [ ] Run `cd apps/api && .venv/bin/python -m pytest`.
- [ ] Run `cd apps/api && .venv/bin/ruff check .`.
- [ ] Run an offline CLI smoke test with fake provider if exposed.
- [ ] Optionally run a real DeepSeek smoke test only after explicit network approval and with `DEEPSEEK_API_KEY` supplied via environment, not committed.

## Self-Review

- The plan restores prompts, model calls, richer state, and Chinese output while preserving backend-only scope.
- The real key is never written to repository files.
- Tests use fake providers, so CI and local tests do not require external API access.
