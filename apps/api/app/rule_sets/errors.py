from __future__ import annotations

from collections.abc import Iterable
from itertools import islice

from app.rule_sets.types import RuleValidationIssue


_MAX_RULE_SET_ID = 80
_MAX_REVISION_ID = 36
_MAX_STATUS = 20
_MAX_ISSUES = 50
_MAX_ISSUE_CODE = 80
_MAX_ISSUE_PATH = 120
_MAX_ISSUE_MESSAGE = 240
_MAX_LOCK_VERSION = 2_147_483_647
_GENERIC_ISSUE_MESSAGE = "Rule configuration is invalid."
_CATALOG_POINTER_GENERIC = "catalog_pointer"
_CATALOG_REASON_GENERIC = "catalog_inconsistent"
_KNOWN_CATALOG_POINTERS = frozenset({"draft_revision_id", "current_published_revision_id"})
_KNOWN_CATALOG_REASONS = frozenset(
    {
        _CATALOG_REASON_GENERIC,
        "content_hash_mismatch",
        "pointer_owner_mismatch",
        "pointer_state_mismatch",
        "pointer_target_missing",
        "public_revision_unavailable",
        "published_config_invalid",
        "revision_config_invalid",
        "schema_version_unsupported",
    }
)
_CANONICAL_ISSUE_MESSAGES = frozenset(
    {
        "At least one good player is required.",
        "At least one werewolf is required.",
        "Badge bomb rules require werewolf self-explosion.",
        "Display order must be a non-negative integer.",
        "Double badge bomb rules require sheriff rules.",
        "Each special role may appear at most once.",
        "Player count must be between 6 and 12.",
        "Sheriff vote weight must be 1 when sheriff rules are disabled.",
        "Sheriff vote weight must be 1, 1.5, or 2.",
        "Sheriff-directed speech requires sheriff rules.",
        "Slaughter-side rules require at least one god role.",
        "Slaughter-side rules require at least one villager.",
        "Speech must be sequential when sheriff rules are disabled.",
        "Werewolves must be fewer than good players.",
    }
)


class RuleSetError(Exception):
    """Base class for HTTP-independent rule-set lifecycle failures."""


class RuleSetNotFound(RuleSetError):
    def __init__(self, rule_set_id: str) -> None:
        self.rule_set_id = _bounded(rule_set_id, _MAX_RULE_SET_ID)
        super().__init__(f"Rule set not found: {self.rule_set_id}")


class RuleSetRevisionNotFound(RuleSetError):
    def __init__(self, rule_set_id: str, *, revision_id: str | None = None) -> None:
        self.rule_set_id = _bounded(rule_set_id, _MAX_RULE_SET_ID)
        self.revision_id = _bounded_optional(revision_id, _MAX_REVISION_ID)
        super().__init__(f"Rule set draft revision not found: {self.rule_set_id}")


class RuleSetValidationFailed(RuleSetError):
    def __init__(
        self,
        rule_set_id: str,
        *,
        revision_id: str | None,
        issues: Iterable[RuleValidationIssue],
    ) -> None:
        self.rule_set_id = _bounded(rule_set_id, _MAX_RULE_SET_ID)
        self.revision_id = _bounded_optional(revision_id, _MAX_REVISION_ID)
        self.issues = tuple(
            RuleValidationIssue(
                code=_bounded(issue.code, _MAX_ISSUE_CODE),
                path=_bounded(issue.path, _MAX_ISSUE_PATH),
                message=_safe_issue_message(issue.message),
            )
            for issue in islice(issues, _MAX_ISSUES)
        )
        super().__init__(f"Rule set validation failed: {self.rule_set_id}")


class RuleSetVersionConflict(RuleSetError):
    def __init__(
        self,
        rule_set_id: str,
        *,
        revision_id: str | None = None,
        expected_rule_set_lock_version: int | None = None,
        current_rule_set_lock_version: int | None = None,
        expected_revision_lock_version: int | None = None,
        current_revision_lock_version: int | None = None,
    ) -> None:
        self.rule_set_id = _bounded(rule_set_id, _MAX_RULE_SET_ID)
        self.revision_id = _bounded_optional(revision_id, _MAX_REVISION_ID)
        self.expected_rule_set_lock_version = _bounded_version(expected_rule_set_lock_version)
        self.current_rule_set_lock_version = _bounded_version(current_rule_set_lock_version)
        self.expected_revision_lock_version = _bounded_version(expected_revision_lock_version)
        self.current_revision_lock_version = _bounded_version(current_revision_lock_version)
        super().__init__(f"Rule set version conflict: {self.rule_set_id}")


class RuleSetTransitionConflict(RuleSetError):
    def __init__(
        self,
        rule_set_id: str,
        *,
        current_status: str,
        target_status: str,
    ) -> None:
        self.rule_set_id = _bounded(rule_set_id, _MAX_RULE_SET_ID)
        self.current_status = _bounded(current_status, _MAX_STATUS)
        self.target_status = _bounded(target_status, _MAX_STATUS)
        super().__init__(
            f"Rule set transition conflict: {self.rule_set_id} "
            f"({self.current_status} -> {self.target_status})"
        )


class RuleSetUnavailable(RuleSetError):
    def __init__(
        self,
        rule_set_id: str,
        *,
        current_status: str | None = None,
        current_revision_id: str | None = None,
    ) -> None:
        self.rule_set_id = _bounded(rule_set_id, _MAX_RULE_SET_ID)
        self.current_status = _bounded_optional(current_status, _MAX_STATUS)
        self.current_revision_id = _bounded_optional(current_revision_id, _MAX_REVISION_ID)
        super().__init__(f"Rule set is unavailable: {self.rule_set_id}")


class RuleRevisionChanged(RuleSetError):
    def __init__(
        self,
        rule_set_id: str,
        *,
        expected_revision_id: str | None,
        current_revision_id: str | None,
    ) -> None:
        self.rule_set_id = _bounded(rule_set_id, _MAX_RULE_SET_ID)
        self.expected_revision_id = _bounded_optional(
            expected_revision_id,
            _MAX_REVISION_ID,
        )
        self.current_revision_id = _bounded_optional(current_revision_id, _MAX_REVISION_ID)
        super().__init__(f"Rule set revision changed: {self.rule_set_id}")


class DefaultRuleRequired(RuleSetError):
    def __init__(
        self,
        rule_set_id: str,
        *,
        replacement_rule_set_id: str | None = None,
    ) -> None:
        self.rule_set_id = _bounded(rule_set_id, _MAX_RULE_SET_ID)
        self.replacement_rule_set_id = _bounded_optional(
            replacement_rule_set_id,
            _MAX_RULE_SET_ID,
        )
        super().__init__(f"A published default rule is required: {self.rule_set_id}")


class RuleSetCatalogCorrupt(RuntimeError):
    """Raised when persisted rule catalog pointers or revision data are inconsistent."""

    def __init__(
        self,
        rule_set_id: str,
        *,
        pointer: str | None = None,
        revision_id: str | None = None,
        reason: str = "catalog_inconsistent",
    ) -> None:
        self.rule_set_id = _bounded(rule_set_id, _MAX_RULE_SET_ID)
        self.pointer = _safe_catalog_pointer(pointer)
        self.revision_id = _bounded_optional(revision_id, _MAX_REVISION_ID)
        self.reason = _safe_catalog_reason(reason)
        details = [self.rule_set_id]
        if self.pointer is not None:
            details.append(self.pointer)
        if self.revision_id is not None:
            details.append(self.revision_id)
        super().__init__(f"Rule set catalog is corrupt: {' / '.join(details)}")


def _bounded(value: str, maximum: int) -> str:
    return value[:maximum] if isinstance(value, str) else ""


def _bounded_optional(value: str | None, maximum: int) -> str | None:
    if value is None:
        return None
    return _bounded(value, maximum)


def _bounded_version(value: int | None) -> int | None:
    if value is None or isinstance(value, bool) or not isinstance(value, int):
        return None
    return max(0, min(value, _MAX_LOCK_VERSION))


def _safe_issue_message(value: str) -> str:
    if value in _CANONICAL_ISSUE_MESSAGES:
        return _bounded(value, _MAX_ISSUE_MESSAGE)
    return _GENERIC_ISSUE_MESSAGE


def _safe_catalog_pointer(value: str | None) -> str | None:
    if value is None:
        return None
    if value in _KNOWN_CATALOG_POINTERS:
        return _bounded(value, 120)
    return _CATALOG_POINTER_GENERIC


def _safe_catalog_reason(value: str) -> str:
    if value in _KNOWN_CATALOG_REASONS:
        return _bounded(value, 80)
    return _CATALOG_REASON_GENERIC


__all__ = [
    "DefaultRuleRequired",
    "RuleRevisionChanged",
    "RuleSetCatalogCorrupt",
    "RuleSetError",
    "RuleSetNotFound",
    "RuleSetRevisionNotFound",
    "RuleSetTransitionConflict",
    "RuleSetUnavailable",
    "RuleSetValidationFailed",
    "RuleSetVersionConflict",
]
