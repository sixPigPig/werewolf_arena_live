from __future__ import annotations

import json


def extract_openai_chat_delta(chunk: bytes) -> str | None:
    text = chunk.decode("utf-8", errors="replace").strip()
    if not text:
        return None

    contents: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if data == "[DONE]":
            return "".join(contents) if contents else None
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            continue
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            continue
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            continue
        delta = first_choice.get("delta")
        if not isinstance(delta, dict):
            continue
        content = delta.get("content")
        if isinstance(content, str) and content:
            contents.append(content)
    return "".join(contents) if contents else None
