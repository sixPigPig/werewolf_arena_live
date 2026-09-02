#!/usr/bin/env python3
"""Create and run one classic-12 Live V2 match until completed or failed.

Requires a running API (default http://127.0.0.1:8000) and twelve published
player profiles. Mixes six enabled models, always including glm-5-3-flash.

Usage:
    apps/api/.venv/bin/python scripts/smoke_v2_full_game.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
import psycopg
import websockets


RULE_SET_ID = "classic_12_seer_witch_hunter_idiot"
REQUIRED_MODEL = "glm-5-3-flash"
MIXED_MODELS: tuple[tuple[str, str], ...] = (
    ("agent_plan", "glm-5-3-flash"),
    ("agent_plan", "glm-5-2-260617"),
    ("agent_plan", "kimi-k3"),
    ("agent_plan", "minimax-m3"),
    ("agent_plan", "doubao-seed-2-0-lite-260215"),
    ("deepseek", "deepseek-v4-flash"),
)
PLAYER_CONFIG_KEYS = {
    "seat",
    "profile_id",
    "name",
    "model_provider",
    "model",
    "personality_id",
    "personality",
    "appearance_id",
    "avatar_image_url",
    "avatar_asset_id",
    "strategy_profile",
    "tts_speaker",
    "tts_dialect",
    "base_delivery_mood",
    "base_delivery_intensity",
    "base_delivery_pace",
    "base_delivery_instruction",
    "voice_enabled",
    "voice_config_version",
    "tags",
}
TERMINAL_MATCH_STATUSES = {"completed", "failed", "canceled"}
FAILURE_EVENT_TYPES = {
    "game_failed",
    "model_request_failed",
    "pre_exile_vote_degraded_to_abstain",
    "day_vote_degraded_to_abstain",
    "day_vote_technical_abstention_committed",
}
DEGRADED_EVENT_TYPES = {
    "pre_exile_vote_degraded_to_abstain",
    "day_vote_degraded_to_abstain",
}


def _log(message: str) -> None:
    print(message, flush=True)


def _ws_url(http_base: str, path: str) -> str:
    parsed = urlparse(http_base)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, path, "", "", ""))


def _ready_message() -> dict[str, Any]:
    return {
        "protocol_version": 1,
        "type": "client.ready",
        "audio": {
            "encoding": "pcm_s16le",
            "sample_rate": 24000,
            "channels": 1,
        },
    }


def _psycopg_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def _fetch_rule_set(client: httpx.Client) -> dict[str, Any]:
    payload = client.get("/api/v1/games/rule-sets").raise_for_status().json()
    for item in payload["rule_sets"]:
        if item["id"] == RULE_SET_ID:
            return item
    raise SystemExit(f"rule set {RULE_SET_ID} is not in the public catalog")


def _fetch_profiles(client: httpx.Client) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        payload = (
            client.get(
                "/api/v1/public/player-profiles",
                params={"page": page, "page_size": 100},
            )
            .raise_for_status()
            .json()
        )
        items.extend(payload["items"])
        pages = int(payload["pagination"]["pages"])
        if page >= pages:
            break
        page += 1
    return items


def _lobby_player(config: dict[str, Any], *, provider: str, model: str) -> dict[str, Any]:
    player = {key: config[key] for key in PLAYER_CONFIG_KEYS if key in config}
    player["model_provider"] = provider
    player["model"] = model
    if not player.get("profile_id"):
        raise SystemExit(f"lineup preview returned a seat without profile_id: {config}")
    return player


def _create_game(
    client: httpx.Client,
    *,
    audio_mode: str | None,
) -> dict[str, Any]:
    rule = _fetch_rule_set(client)
    profiles = _fetch_profiles(client)
    if len(profiles) < 12:
        raise SystemExit(f"need 12 published profiles, found {len(profiles)}")
    selected = profiles[:12]
    preview = (
        client.post(
            "/api/v1/games/lineup-preview",
            json={
                "rule_set_id": RULE_SET_ID,
                "expected_rule_revision_id": rule["revision_id"],
                "seed": 12,
                "player_configs": [
                    {"seat": seat, "profile_id": profile["id"]}
                    for seat, profile in enumerate(selected, start=1)
                ],
                "locked_seats": list(range(1, 13)),
                "repair_scope": "empty_only",
            },
        )
        .raise_for_status()
        .json()
    )
    report = preview["lineup_quality_report"]
    player_configs = []
    bound_models: list[str] = []
    for index, config in enumerate(sorted(preview["player_configs"], key=lambda item: item["seat"])):
        provider, model = MIXED_MODELS[index % len(MIXED_MODELS)]
        player_configs.append(_lobby_player(config, provider=provider, model=model))
        bound_models.append(f"{provider}/{model}")
    if REQUIRED_MODEL not in {item.split("/", 1)[1] for item in bound_models}:
        raise SystemExit(f"{REQUIRED_MODEL} was not bound into the lineup")
    unique_models = sorted(set(bound_models))
    if len(unique_models) < 6:
        raise SystemExit(f"expected 6 mixed models, bound {unique_models}")
    _log("bound models: " + ", ".join(unique_models))
    body: dict[str, Any] = {
        "title": "v2 success-rate smoke classic-12",
        "lobby_snapshot": {
            "schema_version": 1,
            "model_binding_mode": "explicit_snapshot",
            "rule_set": rule,
            "rule_set_revision_id": rule["revision_id"],
            "seed": 12,
            "max_rounds": 12,
            "player_configs": player_configs,
            "lineup_quality_report": report,
            "allow_lineup_quality_warnings": bool(report.get("is_blocked")),
        },
    }
    if audio_mode:
        body["audio_mode"] = audio_mode
    response = client.post("/api/v2/games", json=body)
    if response.status_code != 201:
        raise SystemExit(f"create game failed ({response.status_code}): {response.text}")
    created = response.json()
    _log(f"created {created['game_id']} run={created['run_id']}")
    return created


def _load_events(database_url: str, game_id: str) -> list[dict[str, Any]]:
    with psycopg.connect(_psycopg_url(database_url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT record_seq, event_type, payload
                FROM v2_game_record_events
                WHERE game_id = %s
                ORDER BY record_seq
                """,
                (game_id,),
            )
            return [
                {
                    "record_seq": record_seq,
                    "event_type": event_type,
                    "payload": payload if isinstance(payload, dict) else {},
                }
                for record_seq, event_type, payload in cursor.fetchall()
            ]


def _assert_technical_abstain_lineage(events: list[dict[str, Any]]) -> None:
    by_seq = {item["record_seq"]: item for item in events}
    mismatches: list[str] = []
    for item in events:
        if item["event_type"] != "day_vote_technical_abstention_committed":
            continue
        payload = item["payload"]
        source_action_id = payload.get("source_action_id")
        supporting_seq = payload.get("supporting_event_record_seq")
        supporting = by_seq.get(supporting_seq) if isinstance(supporting_seq, int) else None
        if supporting is None or supporting["event_type"] not in DEGRADED_EVENT_TYPES:
            mismatches.append(
                f"seq={item['record_seq']} missing degraded supporting event {supporting_seq}"
            )
            continue
        supporting_payload = supporting["payload"]
        expected = (
            supporting_payload.get("recovery_action_id")
            or supporting_payload.get("action_id")
            or supporting_payload.get("source_action_id")
        )
        if source_action_id != expected:
            mismatches.append(
                f"seq={item['record_seq']} source_action_id={source_action_id!r} "
                f"expected {expected!r}"
            )
    if mismatches:
        raise SystemExit("technical abstain lineage mismatch:\n" + "\n".join(mismatches))
    degraded_count = sum(1 for item in events if item["event_type"] in DEGRADED_EVENT_TYPES)
    _log(
        "technical abstain lineage ok "
        f"(degraded={degraded_count}, committed="
        f"{sum(1 for item in events if item['event_type'] == 'day_vote_technical_abstention_committed')})"
    )


def _dump_failure(events: list[dict[str, Any]], dump_path: str) -> None:
    interesting = [
        item
        for item in events
        if item["event_type"] in FAILURE_EVENT_TYPES or item["event_type"] == "game_failed"
    ]
    payload = interesting or events[-20:]
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    Path(dump_path).write_text(text, encoding="utf-8")
    print(text, file=sys.stderr)


async def _run_until_terminal(
    *,
    http_base: str,
    created: dict[str, Any],
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    snapshot_path = created["director_snapshot_url"]
    ws_path = created["websocket_url"]
    deadline = time.monotonic() + timeout_seconds
    last_status = None
    async with httpx.AsyncClient(base_url=http_base, timeout=30.0) as client:
        async with websockets.connect(_ws_url(http_base, ws_path)) as websocket:
            initial = json.loads(await websocket.recv())
            _log(f"ws initial live_state={initial.get('live_state')}")
            await websocket.send(json.dumps(_ready_message()))
            while time.monotonic() < deadline:
                remaining = max(0.1, min(poll_seconds, deadline - time.monotonic()))
                try:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
                    message = json.loads(raw) if isinstance(raw, str) else None
                    if isinstance(message, dict) and message.get("live_state"):
                        status = (
                            message.get("match_status"),
                            message.get("live_state"),
                            (message.get("game_phase") or {}).get("phase_state"),
                        )
                        if status != last_status:
                            last_status = status
                            _log(
                                f"ws match_status={status[0]} live_state={status[1]} "
                                f"phase={status[2]}"
                            )
                        if status[0] in TERMINAL_MATCH_STATUSES:
                            return message
                except TimeoutError:
                    snapshot = (await client.get(snapshot_path)).raise_for_status().json()
                    status = (
                        snapshot.get("match_status"),
                        snapshot.get("live_state"),
                        (snapshot.get("game_phase") or {}).get("phase_state"),
                    )
                    if status != last_status:
                        last_status = status
                        _log(
                            f"http match_status={status[0]} live_state={status[1]} "
                            f"phase={status[2]}"
                        )
                    if status[0] in TERMINAL_MATCH_STATUSES:
                        return snapshot
            raise SystemExit(f"timed out after {timeout_seconds:.0f}s waiting for a terminal status")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-base",
        default=os.environ.get("SMOKE_API_BASE", "http://127.0.0.1:8000"),
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/app",
        ),
    )
    parser.add_argument("--audio-mode", default=os.environ.get("SMOKE_AUDIO_MODE") or None)
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.environ.get("SMOKE_TIMEOUT_SECONDS", "3600")),
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=float(os.environ.get("SMOKE_POLL_SECONDS", "5")),
    )
    parser.add_argument(
        "--dump-path",
        default=os.environ.get("SMOKE_DUMP_PATH", "/tmp/smoke-v2-last-failure.json"),
    )
    parser.add_argument(
        "--create-only",
        action="store_true",
        help="Create the waiting game and exit without sending ready.",
    )
    args = parser.parse_args()

    with httpx.Client(base_url=args.api_base.rstrip("/"), timeout=30.0) as client:
        created = _create_game(client, audio_mode=args.audio_mode)
    if args.create_only:
        _log("create-only: not starting the match")
        return 0
    terminal = asyncio.run(
        _run_until_terminal(
            http_base=args.api_base.rstrip("/"),
            created=created,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
    )
    match_status = terminal.get("match_status")
    events = _load_events(args.database_url, created["game_id"])
    if match_status != "completed":
        _dump_failure(events, args.dump_path)
        raise SystemExit(
            f"smoke failed: match_status={match_status!r} "
            f"live_state={terminal.get('live_state')!r} "
            f"reason={terminal.get('completion_reason')!r} dump={args.dump_path}"
        )
    _assert_technical_abstain_lineage(events)
    _log(
        f"smoke passed: {created['game_id']} completed "
        f"winner={terminal.get('winner')!r} reason={terminal.get('completion_reason')!r}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
