from __future__ import annotations

import json

PUBLIC_STREAM_FIELD_BY_ACTION = {
    "debate": "say",
    "sheriff_speech": "say",
    "sheriff_pk_speech": "say",
    "summarize": "summary",
}


def action_visible_stream_field(action: str) -> str | None:
    return PUBLIC_STREAM_FIELD_BY_ACTION.get(action)


class VisibleJsonFieldExtractor:
    def __init__(self, field: str) -> None:
        self.field = field
        self._visible_text = ""

    def update(self, raw_text: str) -> str:
        visible_text = extract_json_string_field_prefix(raw_text, self.field)
        if not visible_text.startswith(self._visible_text):
            self._visible_text = ""
        delta = visible_text[len(self._visible_text) :]
        self._visible_text = visible_text
        return delta


def extract_json_string_field_prefix(raw_text: str, field: str) -> str:
    marker = json.dumps(field, ensure_ascii=False)
    marker_index = raw_text.find(marker)
    if marker_index < 0:
        return ""

    colon_index = raw_text.find(":", marker_index + len(marker))
    if colon_index < 0:
        return ""

    index = colon_index + 1
    while index < len(raw_text) and raw_text[index].isspace():
        index += 1
    if index >= len(raw_text) or raw_text[index] != '"':
        return ""

    raw_value = _raw_json_string_prefix(raw_text[index + 1 :])
    return _decode_json_string_prefix(raw_value)


def _raw_json_string_prefix(text: str) -> str:
    chars: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"':
            break
        if char == "\\":
            if index + 1 >= len(text):
                break
            next_char = text[index + 1]
            if next_char == "u":
                if index + 6 >= len(text):
                    break
                chars.append(text[index : index + 6])
                index += 6
                continue
            if index + 2 >= len(text):
                break
            chars.append(text[index : index + 2])
            index += 2
            continue
        chars.append(char)
        index += 1
    return "".join(chars)


def _decode_json_string_prefix(raw_value: str) -> str:
    if raw_value == "":
        return ""
    try:
        return json.loads(f'"{raw_value}"')
    except json.JSONDecodeError:
        trimmed = raw_value.rstrip("\\")
        return json.loads('"' + trimmed + '"')


def extract_openai_chat_delta(chunk: bytes) -> str | None:
    text = chunk.decode("utf-8", errors="replace").strip()
    if not text or text.startswith(":"):
        return None

    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if data == "[DONE]":
            return None
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return None
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return None
        delta = first_choice.get("delta")
        if not isinstance(delta, dict):
            return None
        content = delta.get("content")
        return content if isinstance(content, str) and content else None
    return None
