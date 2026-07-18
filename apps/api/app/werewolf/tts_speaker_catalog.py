from __future__ import annotations

from dataclasses import dataclass
import logging
import re
import threading
import time
from typing import Any

import httpx

from app.werewolf.volcengine_tts import supports_tts_context_texts

logger = logging.getLogger(__name__)

VOLCENGINE_TTS_SPEAKER_DOC_URL = (
    "https://docs.volcengine.com/api/doc/getDocDetail"
)
VOLCENGINE_TTS_SPEAKER_DOC_PARAMS = {
    "LibraryID": "6561",
    "DocumentID": "1257544",
    "lang": "zh",
    "type": "online",
}
DEFAULT_TTL_SECONDS = 60 * 60
DEFAULT_TIMEOUT_SECONDS = 5.0
_SECTION_HEADING_RE = re.compile(r"(?=^## )", re.MULTILINE)


class TtsSpeakerCatalogUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class TtsSpeakerOption:
    voice_type: str
    name: str


def parse_supported_tts_speakers(
    content: str,
    *,
    resource_id: str,
) -> tuple[TtsSpeakerOption, ...]:
    """Parse bidirectional seed-tts-2.0 presets from the official voice table."""

    options: list[TtsSpeakerOption] = []
    seen: set[str] = set()
    for section in _SECTION_HEADING_RE.split(content):
        heading = section.splitlines()[0] if section else ""
        if "豆包语音合成模型2.0" not in heading:
            continue
        for line in section.splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) < 3:
                continue
            name = cells[1]
            voice_type = cells[2]
            if (
                not name
                or voice_type in seen
                or "仅限单向流" in line
                or "不支持双向流" in line
                or not supports_tts_context_texts(
                    resource_id=resource_id,
                    speaker=voice_type,
                )
            ):
                continue
            seen.add(voice_type)
            options.append(TtsSpeakerOption(voice_type=voice_type, name=name))

    if not options:
        raise TtsSpeakerCatalogUnavailable(
            "The official Volcengine document contained no compatible TTS speakers"
        )
    return tuple(options)


class VolcengineTtsSpeakerCatalog:
    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
    ) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds
        self._cache: dict[str, tuple[float, tuple[TtsSpeakerOption, ...]]] = {}
        self._lock = threading.Lock()

    def list_supported(self, *, resource_id: str) -> tuple[TtsSpeakerOption, ...]:
        cache_key = resource_id.strip().lower()
        now = time.monotonic()
        with self._lock:
            cached = self._cache.get(cache_key)
        if cached is not None and now < cached[0]:
            return cached[1]

        try:
            content = self._fetch_document_content()
            options = parse_supported_tts_speakers(
                content,
                resource_id=resource_id,
            )
        except (
            TtsSpeakerCatalogUnavailable,
            httpx.HTTPError,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            if cached is not None:
                logger.warning("Using stale Volcengine TTS speaker catalog")
                return cached[1]
            raise TtsSpeakerCatalogUnavailable(
                "Unable to load the official Volcengine TTS speaker catalog"
            ) from exc

        with self._lock:
            self._cache[cache_key] = (now + self._ttl_seconds, options)
        return options

    def _fetch_document_content(self) -> str:
        if self._client is not None:
            return self._content_from_response(
                self._client.get(
                    VOLCENGINE_TTS_SPEAKER_DOC_URL,
                    params=VOLCENGINE_TTS_SPEAKER_DOC_PARAMS,
                )
            )
        with httpx.Client(
            timeout=DEFAULT_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            return self._content_from_response(
                client.get(
                    VOLCENGINE_TTS_SPEAKER_DOC_URL,
                    params=VOLCENGINE_TTS_SPEAKER_DOC_PARAMS,
                )
            )

    @staticmethod
    def _content_from_response(response: httpx.Response) -> str:
        response.raise_for_status()
        payload: Any = response.json()
        content = payload["Result"]["Content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Volcengine speaker document content is empty")
        return content


tts_speaker_catalog = VolcengineTtsSpeakerCatalog()
