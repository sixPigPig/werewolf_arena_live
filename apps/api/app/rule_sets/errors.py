from __future__ import annotations


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
        self.rule_set_id = rule_set_id
        self.pointer = pointer
        self.revision_id = revision_id
        self.reason = reason
        details = [rule_set_id]
        if pointer is not None:
            details.append(pointer)
        if revision_id is not None:
            details.append(revision_id)
        super().__init__(f"Rule set catalog is corrupt: {' / '.join(details)}")
