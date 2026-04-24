from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

Transport = Callable[[str, dict[str, str], dict[str, Any]], dict[str, Any]]
Sleep = Callable[[float], None]


class DeepSeekProvider:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        transport: Transport | None = None,
        max_retries: int = 3,
        sleep: Sleep = time.sleep,
    ) -> None:
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is required to call DeepSeek.")

        self.base_url = (base_url or os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com").rstrip("/")
        self.transport = transport or _urlopen_transport
        self.max_retries = max_retries
        self.sleep = sleep

    def complete_json(self, *, model: str, prompt: str, temperature: float) -> str:
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是狼人杀游戏玩家。所有内容使用中文，并严格输出 json。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "stream": False,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "werewolf-arena-live/0.1",
        }
        response = self._send_with_retries(f"{self.base_url}/chat/completions", headers, payload)
        return response["choices"][0]["message"]["content"]

    def _send_with_retries(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return self.transport(url, headers, payload)
            except urllib.error.HTTPError:
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionResetError, OSError) as exc:
                last_error = exc
                if attempt == self.max_retries:
                    break
                self.sleep(min(2.0, 0.25 * attempt))

        raise RuntimeError(
            f"DeepSeek network request failed after {self.max_retries} attempts: {last_error}"
        ) from last_error


def _urlopen_transport(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek request failed with HTTP {exc.code}: {body}") from exc
