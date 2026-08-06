from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from sqlalchemy.dialects import postgresql, sqlite

from app.v2.execution import database_utc_now


def test_postgresql_lease_clock_uses_wall_clock_not_transaction_timestamp() -> None:
    db = MagicMock()
    db.get_bind.return_value.dialect.name = "postgresql"
    db.scalar.return_value = datetime(2026, 8, 6, tzinfo=UTC)

    assert database_utc_now(db) == datetime(2026, 8, 6, tzinfo=UTC)

    statement = db.scalar.call_args.args[0]
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    assert "clock_timestamp()" in compiled
    assert "CURRENT_TIMESTAMP" not in compiled


def test_sqlite_lease_clock_keeps_supported_current_timestamp_fallback() -> None:
    db = MagicMock()
    db.get_bind.return_value.dialect.name = "sqlite"
    db.scalar.return_value = datetime(2026, 8, 6)

    assert database_utc_now(db) == datetime(2026, 8, 6, tzinfo=UTC)

    statement = db.scalar.call_args.args[0]
    compiled = str(statement.compile(dialect=sqlite.dialect()))
    assert "CURRENT_TIMESTAMP" in compiled
    assert "clock_timestamp()" not in compiled
