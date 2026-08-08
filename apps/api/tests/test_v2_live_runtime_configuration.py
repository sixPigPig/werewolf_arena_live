from __future__ import annotations

import asyncio

from app.core.config import Settings
from app.v2.live_runtime import build_v2_live_runtime


def test_live_runtime_defaults_every_provider_route_to_schema_fallback() -> None:
    runtime = build_v2_live_runtime(Settings(_env_file=None))
    try:
        routes = runtime._model_client._routes

        assert routes["agent_plan"].supports_strict_json_schema is False
        assert routes["ark"].supports_strict_json_schema is False
        assert routes["deepseek"].supports_strict_json_schema is False
    finally:
        asyncio.run(runtime.aclose())


def test_live_runtime_enables_strict_schema_only_for_explicit_routes() -> None:
    runtime = build_v2_live_runtime(
        Settings(
            _env_file=None,
            live_v2_agent_plan_supports_strict_json_schema=True,
            live_v2_ark_supports_strict_json_schema=False,
            live_v2_deepseek_supports_strict_json_schema=True,
        )
    )
    try:
        routes = runtime._model_client._routes

        assert routes["agent_plan"].supports_strict_json_schema is True
        assert routes["ark"].supports_strict_json_schema is False
        assert routes["deepseek"].supports_strict_json_schema is True
    finally:
        asyncio.run(runtime.aclose())
