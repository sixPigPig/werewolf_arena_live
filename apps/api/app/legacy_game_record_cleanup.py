from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

LEGACY_GAME_DIR_RE = re.compile(r"^game_[0-9a-f]{8}$")


@dataclass(frozen=True)
class LegacyGameRecordPurgeResult:
    matched_count: int
    deleted_count: int
    skipped_count: int


def purge_legacy_game_records(logs_dir: Path, *, confirm: bool) -> LegacyGameRecordPurgeResult:
    if not logs_dir.exists() or not logs_dir.is_dir():
        return LegacyGameRecordPurgeResult(matched_count=0, deleted_count=0, skipped_count=0)

    matched: list[Path] = []
    skipped_count = 0
    for child in logs_dir.iterdir():
        if not LEGACY_GAME_DIR_RE.fullmatch(child.name):
            continue
        if child.is_symlink() or not child.is_dir():
            skipped_count += 1
            continue
        matched.append(child)

    deleted_count = 0
    if confirm:
        for directory in matched:
            shutil.rmtree(directory)
            deleted_count += 1

    return LegacyGameRecordPurgeResult(
        matched_count=len(matched),
        deleted_count=deleted_count,
        skipped_count=skipped_count,
    )
