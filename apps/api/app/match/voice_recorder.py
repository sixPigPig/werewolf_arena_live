from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import wave


class VoiceRecordingError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecordedVoice:
    sample_count: int
    duration_ms: int
    pcm_sha256: str
    size_bytes: int


class VoiceRecorder:
    def __init__(
        self,
        *,
        root: Path,
        storage_key: str,
        sample_rate: int,
        channels: int = 1,
    ) -> None:
        self._root = root.resolve()
        self._final_path = (self._root / storage_key).resolve()
        if self._root not in self._final_path.parents:
            raise VoiceRecordingError("voice storage key escapes V2 root")
        self._final_path.parent.mkdir(parents=True, exist_ok=True)
        self._temporary_path = self._final_path.with_suffix(f"{self._final_path.suffix}.writing")
        self._sample_rate = sample_rate
        self._channels = channels
        self._sample_count = 0
        self._hash = hashlib.sha256()
        self._closed = False
        self._finalized = False
        try:
            self._writer = wave.open(str(self._temporary_path), "wb")
            self._writer.setnchannels(channels)
            self._writer.setsampwidth(2)
            self._writer.setframerate(sample_rate)
        except (OSError, wave.Error) as exc:
            raise VoiceRecordingError("cannot open V2 voice asset") from exc

    def append(self, pcm: bytes) -> int:
        if self._closed:
            raise VoiceRecordingError("voice recorder is closed")
        frame_width = self._channels * 2
        if not pcm or len(pcm) % frame_width:
            raise VoiceRecordingError("PCM chunk is empty or misaligned")
        try:
            self._writer.writeframesraw(pcm)
        except (OSError, wave.Error) as exc:
            raise VoiceRecordingError("cannot write V2 voice asset") from exc
        sample_count = len(pcm) // frame_width
        self._sample_count += sample_count
        self._hash.update(pcm)
        return sample_count

    def finalize(self) -> RecordedVoice:
        if self._closed:
            raise VoiceRecordingError("voice recorder is already closed")
        if self._sample_count <= 0:
            raise VoiceRecordingError("voice asset has no samples")
        try:
            self._writer.close()
            self._closed = True
            os.replace(self._temporary_path, self._final_path)
            self._finalized = True
            size_bytes = self._final_path.stat().st_size
        except (OSError, wave.Error) as exc:
            self.discard_finalized()
            raise VoiceRecordingError("cannot finalize V2 voice asset") from exc
        return RecordedVoice(
            sample_count=self._sample_count,
            duration_ms=round(self._sample_count * 1000 / self._sample_rate),
            pcm_sha256=self._hash.hexdigest(),
            size_bytes=size_bytes,
        )

    def abort(self) -> None:
        if not self._closed:
            try:
                self._writer.close()
            except (OSError, wave.Error):
                pass
            self._closed = True
        try:
            self._temporary_path.unlink(missing_ok=True)
        except OSError:
            pass

    def discard_finalized(self) -> None:
        """Remove an uncommitted final file after execution ownership is lost."""
        self.abort()
        if not self._finalized:
            return
        try:
            self._final_path.unlink(missing_ok=True)
        except OSError:
            return
        self._finalized = False
