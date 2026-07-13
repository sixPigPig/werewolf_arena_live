from __future__ import annotations

from collections import Counter
import re
from threading import Lock

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.game_session import GameSessionRecord
from app.models.rule_set import RuleSetRecord


_MAX_DYNAMIC_SERIES = 512
_RULE_SET_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]{2,79}")
_PUBLISH_RESULTS = ("success", "rejected", "conflict", "failure", "unknown")
_SNAPSHOT_REASONS = (
    "invalid_snapshot",
    "catalog_inconsistent",
    "content_hash_mismatch",
    "pointer_owner_mismatch",
    "pointer_state_mismatch",
    "pointer_target_missing",
    "public_revision_unavailable",
    "published_config_invalid",
    "revision_config_invalid",
    "schema_version_unsupported",
    "unknown",
)
_CHECKPOINT_REASONS = (
    "missing",
    "unsupported_schema",
    "invalid_structure",
    "invalid_rule_snapshot",
    "rule_snapshot_mismatch",
    "rule_metadata_mismatch",
    "unknown",
)
_GAME_STATUSES = frozenset({"complete", "partial"})

_LOCK = Lock()
_PUBLISH_COUNTER: Counter[tuple[str]] = Counter()
_CREATE_CONFLICT_COUNTER: Counter[tuple[str, str]] = Counter()
_SNAPSHOT_FAILURE_COUNTER: Counter[tuple[str]] = Counter()
_CHECKPOINT_FAILURE_COUNTER: Counter[tuple[str]] = Counter()
_LEGACY_CREATE_COUNTER: Counter[tuple[str, str]] = Counter()


def record_rule_publish(result: str) -> None:
    _record_bounded(_PUBLISH_COUNTER, (_fixed_label(result, _PUBLISH_RESULTS),))


def record_rule_create_conflict(rule_set_id: str, revision_no: int | None) -> None:
    _record_bounded(
        _CREATE_CONFLICT_COUNTER,
        (_stable_rule_set_id(rule_set_id), _revision_label(revision_no)),
    )


def record_rule_snapshot_failure(reason: str) -> None:
    _record_bounded(_SNAPSHOT_FAILURE_COUNTER, (_fixed_label(reason, _SNAPSHOT_REASONS),))


def record_rule_checkpoint_failure(reason: str) -> None:
    _record_bounded(
        _CHECKPOINT_FAILURE_COUNTER,
        (_fixed_label(reason, _CHECKPOINT_REASONS),),
    )


def record_legacy_rule_create(rule_set_id: str, revision_no: int | None) -> None:
    _record_bounded(
        _LEGACY_CREATE_COUNTER,
        (_stable_rule_set_id(rule_set_id), _revision_label(revision_no)),
    )


def render_rule_set_metrics(db: Session) -> str:
    game_counts: Counter[tuple[str, str, str]] = Counter()
    rows = db.execute(
        select(
            GameSessionRecord.rule_set_id,
            GameSessionRecord.rule_set_revision_no,
            GameSessionRecord.status,
            func.count(),
        ).group_by(
            GameSessionRecord.rule_set_id,
            GameSessionRecord.rule_set_revision_no,
            GameSessionRecord.status,
        )
    ).all()
    for rule_set_id, revision_no, status, count in rows:
        game_counts[
            (
                _stable_rule_set_id(rule_set_id),
                _revision_label(revision_no),
                status if type(status) is str and status in _GAME_STATUSES else "other",
            )
        ] += int(count)
    failure_rate_deltas = _game_failure_rate_deltas(game_counts)

    published_defaults = int(
        db.scalar(
            select(func.count())
            .select_from(RuleSetRecord)
            .where(
                RuleSetRecord.status == "published",
                RuleSetRecord.is_default.is_(True),
                RuleSetRecord.archived_at.is_(None),
            )
        )
        or 0
    )
    with _LOCK:
        publish = _PUBLISH_COUNTER.copy()
        conflicts = _CREATE_CONFLICT_COUNTER.copy()
        snapshots = _SNAPSHOT_FAILURE_COUNTER.copy()
        checkpoints = _CHECKPOINT_FAILURE_COUNTER.copy()
        legacy = _LEGACY_CREATE_COUNTER.copy()

    lines: list[str] = []
    _append_counter(
        lines,
        name="werewolf_rule_publish_total",
        help_text="Rule publication outcomes.",
        label_names=("result",),
        counter=publish,
        zero_keys=((value,) for value in _PUBLISH_RESULTS),
    )
    _append_counter(
        lines,
        name="werewolf_rule_create_conflicts_total",
        help_text="Public game creation revision conflicts.",
        label_names=("rule_set_id", "revision_no"),
        counter=conflicts,
    )
    _append_counter(
        lines,
        name="werewolf_rule_snapshot_failures_total",
        help_text="Rule snapshot parsing failures.",
        label_names=("reason",),
        counter=snapshots,
        zero_keys=((value,) for value in _SNAPSHOT_REASONS),
    )
    _append_counter(
        lines,
        name="werewolf_rule_checkpoint_failures_total",
        help_text="Rule checkpoint parsing failures.",
        label_names=("reason",),
        counter=checkpoints,
        zero_keys=((value,) for value in _CHECKPOINT_REASONS),
    )
    _append_counter(
        lines,
        name="werewolf_rule_legacy_creates_total",
        help_text="Successful game creates without an expected revision.",
        label_names=("rule_set_id", "revision_no"),
        counter=legacy,
    )
    lines.extend(
        (
            "# HELP werewolf_rule_games Persisted games grouped by pinned rule revision and status.",
            "# TYPE werewolf_rule_games gauge",
        )
    )
    for key, count in sorted(game_counts.items()):
        lines.append(
            _sample("werewolf_rule_games", ("rule_set_id", "revision_no", "status"), key, count)
        )
    lines.extend(
        (
            "# HELP werewolf_rule_game_failure_ratio_delta Partial-game ratio minus the preceding revision ratio.",
            "# TYPE werewolf_rule_game_failure_ratio_delta gauge",
        )
    )
    for key, delta in sorted(failure_rate_deltas.items()):
        lines.append(
            _sample(
                "werewolf_rule_game_failure_ratio_delta",
                ("rule_set_id", "revision_no"),
                key,
                delta,
            )
        )
    lines.extend(
        (
            "# HELP werewolf_rule_published_defaults Published non-archived default rule sets.",
            "# TYPE werewolf_rule_published_defaults gauge",
            f"werewolf_rule_published_defaults {published_defaults}",
            "",
        )
    )
    return "\n".join(lines)


def _record_bounded(counter: Counter, key: tuple[str, ...]) -> None:
    try:
        with _LOCK:
            overflow_key = tuple("overflow" for _ in key)
            if key in counter:
                counter[key] += 1
            elif len(counter) < _MAX_DYNAMIC_SERIES - 1:
                counter[key] += 1
            else:
                counter[overflow_key] += 1
    except Exception:
        return


def _fixed_label(value: object, allowed: tuple[str, ...]) -> str:
    return value if type(value) is str and value in allowed else "unknown"


def _stable_rule_set_id(value: object) -> str:
    if type(value) is str and _RULE_SET_ID_PATTERN.fullmatch(value) is not None:
        return value
    return "unknown"


def _revision_label(value: object) -> str:
    if value is None:
        return "legacy"
    if type(value) is int and value > 0:
        return str(value)
    return "unknown"


def _append_counter(
    lines: list[str],
    *,
    name: str,
    help_text: str,
    label_names: tuple[str, ...],
    counter: Counter,
    zero_keys: object = (),
) -> None:
    lines.extend((f"# HELP {name} {help_text}", f"# TYPE {name} counter"))
    keys = set(counter)
    keys.update(zero_keys)
    for key in sorted(keys):
        lines.append(_sample(name, label_names, key, counter[key]))


def _game_failure_rate_deltas(
    game_counts: Counter[tuple[str, str, str]],
) -> dict[tuple[str, str], float]:
    revisions: dict[str, dict[int, Counter[str]]] = {}
    for (rule_set_id, revision_label, status), count in game_counts.items():
        if not revision_label.isdecimal():
            continue
        revision_no = int(revision_label)
        if revision_no <= 0:
            continue
        revisions.setdefault(rule_set_id, {}).setdefault(revision_no, Counter())[status] += count

    deltas: dict[tuple[str, str], float] = {}
    for rule_set_id, counts_by_revision in revisions.items():
        previous_ratio: float | None = None
        for revision_no in sorted(counts_by_revision):
            status_counts = counts_by_revision[revision_no]
            total = status_counts["complete"] + status_counts["partial"]
            if total <= 0:
                continue
            ratio = status_counts["partial"] / total
            if previous_ratio is not None:
                deltas[(rule_set_id, str(revision_no))] = ratio - previous_ratio
            previous_ratio = ratio
    return deltas


def _sample(
    name: str,
    label_names: tuple[str, ...],
    label_values: tuple[str, ...],
    value: int | float,
) -> str:
    labels = ",".join(
        f'{label_name}="{_escape_label(label_value)}"'
        for label_name, label_value in zip(label_names, label_values, strict=True)
    )
    return f"{name}{{{labels}}} {value}"


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _reset_rule_set_metrics_for_tests() -> None:
    with _LOCK:
        _PUBLISH_COUNTER.clear()
        _CREATE_CONFLICT_COUNTER.clear()
        _SNAPSHOT_FAILURE_COUNTER.clear()
        _CHECKPOINT_FAILURE_COUNTER.clear()
        _LEGACY_CREATE_COUNTER.clear()


__all__ = [
    "record_legacy_rule_create",
    "record_rule_checkpoint_failure",
    "record_rule_create_conflict",
    "record_rule_publish",
    "record_rule_snapshot_failure",
    "render_rule_set_metrics",
]
