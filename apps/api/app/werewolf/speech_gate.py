from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass


_SYSTEM_ARTIFACT_RE = re.compile(
    r"(?:```|<\/?(?:system|assistant|tool)>|\b(?:system|assistant|developer)\s*:|"
    r"(?:prompt|schema|json)\s*(?:要求|字段|格式))",
    re.IGNORECASE,
)
_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。！？!?；;])")
_COMPLETE_SENTENCE_RE = re.compile(r"[。！？!?；;]")


@dataclass(frozen=True)
class HardSpeechGateReportV1:
    accepted: bool
    codes: tuple[str, ...]
    checked_chars: int

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "accepted": self.accepted,
            "codes": list(self.codes),
            "checked_chars": self.checked_chars,
        }


class IncrementalSpeechSegmenter:
    """Turn renderer text deltas into irreversible complete-clause candidates.

    ``append`` only releases text ending at an explicit sentence boundary. The
    remaining tail is released by ``finish`` only after the provider response
    has been parsed and accepted as a complete renderer result.
    """

    def __init__(self, *, max_chars: int = 90) -> None:
        self.max_chars = max_chars
        self._observed = ""
        self._pending = ""
        self._released = ""

    @property
    def observed_text(self) -> str:
        return self._observed

    @property
    def released_text(self) -> str:
        return self._released

    @property
    def pending_text(self) -> str:
        return self._pending

    def append(self, delta: str) -> list[str]:
        if not isinstance(delta, str) or not delta:
            return []
        self._observed += delta
        self._pending += delta
        boundary_end = 0
        for match in _COMPLETE_SENTENCE_RE.finditer(self._pending):
            boundary_end = match.end()
        if boundary_end == 0:
            return []
        complete = self._pending[:boundary_end]
        self._pending = self._pending[boundary_end:]
        segments = split_complete_speech_segments(complete, max_chars=self.max_chars)
        self._released += "".join(segments)
        return segments

    def finish(self, final_text: str) -> list[str]:
        normalized_final = " ".join(final_text.split()).strip()
        normalized_observed = " ".join(self._observed.split()).strip()
        if normalized_observed and not normalized_final.startswith(normalized_observed):
            raise ValueError("renderer final text differs from streamed prefix")
        released = " ".join(self._released.split()).strip()
        if released and not normalized_final.startswith(released):
            raise ValueError("renderer final text differs from committed prefix")
        remaining = normalized_final[len(released) :].strip()
        self._pending = ""
        if not remaining:
            return []
        segments = split_complete_speech_segments(remaining, max_chars=self.max_chars)
        self._released += "".join(segments)
        return segments


def hard_speech_gate(
    text: str,
    *,
    forbidden_private_terms: tuple[str, ...] = (),
    deterministic_codes: tuple[str, ...] = (),
) -> HardSpeechGateReportV1:
    normalized = text.strip()
    codes: list[str] = []
    if not normalized:
        codes.append("invalid_public_speech")
    if _SYSTEM_ARTIFACT_RE.search(normalized):
        codes.append("system_artifact")
    if any(term and term in normalized for term in forbidden_private_terms):
        codes.append("private_fact_leak")
    codes.extend(code for code in deterministic_codes if code not in codes)
    return HardSpeechGateReportV1(
        accepted=not codes,
        codes=tuple(codes),
        checked_chars=len(normalized),
    )


def split_complete_speech_segments(text: str, *, max_chars: int = 90) -> list[str]:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        return []
    clauses = [item.strip() for item in _SENTENCE_BOUNDARY_RE.split(normalized) if item.strip()]
    segments: list[str] = []
    for clause in clauses:
        if len(clause) > max_chars:
            segments.extend(_split_long_clause(clause, max_chars=max_chars))
        else:
            segments.append(clause)
    return segments


def truncate_to_complete_sentence(text: str, *, max_chars: int) -> str:
    normalized = " ".join(text.split()).strip()
    if len(normalized) <= max_chars:
        return normalized
    candidate = normalized[:max_chars]
    last_boundary = max(candidate.rfind(mark) for mark in "。！？!?；;")
    if last_boundary >= max(0, max_chars // 3):
        return candidate[: last_boundary + 1].strip()
    return candidate.rstrip("，、,:： ") + "。"


def stable_speech_id(session_id: str, action_id: str, speech_stream_version: str) -> str:
    material = f"speech-v1:{session_id}:{action_id}:{speech_stream_version}"
    return "sp_" + hashlib.sha256(material.encode()).hexdigest()[:24]


def stable_segment_id(speech_id: str, segment_index: int, text: str) -> str:
    digest = hashlib.sha256(f"segment-v1:{speech_id}:{segment_index}:{text}".encode()).hexdigest()
    return "seg_" + digest[:24]


def stable_segment_presentation_id(segment_id: str) -> str:
    return "pres_" + hashlib.sha256(f"presentation-v1:{segment_id}".encode()).hexdigest()[:24]


def _split_long_clause(clause: str, *, max_chars: int) -> list[str]:
    pieces = re.split(r"(?<=[，、,:：])", clause)
    result: list[str] = []
    pending = ""
    for piece in pieces:
        if not piece:
            continue
        while len(piece) > max_chars:
            if pending:
                result.append(pending)
                pending = ""
            result.append(piece[:max_chars])
            piece = piece[max_chars:]
        if pending and len(pending) + len(piece) > max_chars:
            result.append(pending)
            pending = ""
        pending += piece
    if pending:
        result.append(pending)
    return result
