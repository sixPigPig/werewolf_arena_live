from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20260728_49_player_profile_ordering_cleanup.py"
)


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "player_profile_ordering_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ordering_cleanup_normalizes_lifecycle_and_is_reversible() -> None:
    migration = load_migration()
    assert migration.revision == "20260728_49"
    assert migration.down_revision == "20260727_48"

    metadata = sa.MetaData()
    users = sa.Table(
        "users",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
    )
    profiles = sa.Table(
        "virtual_player_profiles",
        metadata,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "owner_user_id",
            sa.Integer(),
            sa.ForeignKey(
                users.c.id,
                name="virtual_player_profiles_owner_user_id_fkey",
            ),
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="published"),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("favorite", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("avatar_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("avatar_image_path", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    sa.Index(
        "ix_virtual_player_profiles_owner_user_id",
        profiles.c.owner_user_id,
    )
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(sa.insert(users), [{"id": 1}])
        connection.execute(
            sa.insert(profiles),
            [
                {
                    "id": "published-c",
                    "owner_user_id": 1,
                    "status": "published",
                    "published_at": datetime(2026, 7, 1, tzinfo=UTC),
                    "deleted_at": None,
                    "display_order": 20,
                    "favorite": True,
                    "avatar_prompt": "unused",
                    "avatar_image_path": "/tmp/unused.png",
                },
                {
                    "id": "published-a",
                    "owner_user_id": None,
                    "status": "published",
                    "published_at": datetime(2026, 7, 1, tzinfo=UTC),
                    "deleted_at": None,
                    "display_order": 5,
                    "favorite": False,
                    "avatar_prompt": "",
                    "avatar_image_path": "",
                },
                {
                    "id": "published-b",
                    "owner_user_id": None,
                    "status": "published",
                    "published_at": datetime(2026, 7, 1, tzinfo=UTC),
                    "deleted_at": None,
                    "display_order": 5,
                    "favorite": False,
                    "avatar_prompt": "",
                    "avatar_image_path": "",
                },
                {
                    "id": "draft",
                    "owner_user_id": None,
                    "status": "draft",
                    "published_at": None,
                    "deleted_at": None,
                    "display_order": 4,
                    "favorite": False,
                    "avatar_prompt": "",
                    "avatar_image_path": "",
                },
                {
                    "id": "archived",
                    "owner_user_id": None,
                    "status": "archived",
                    "published_at": datetime(2026, 6, 1, tzinfo=UTC),
                    "deleted_at": datetime(2026, 7, 1, tzinfo=UTC),
                    "display_order": 7,
                    "favorite": False,
                    "avatar_prompt": "",
                    "avatar_image_path": "",
                },
                {
                    "id": "legacy-deleted-published",
                    "owner_user_id": None,
                    "status": "published",
                    "published_at": datetime(2026, 6, 1, tzinfo=UTC),
                    "deleted_at": datetime(2026, 7, 1, tzinfo=UTC),
                    "display_order": 8,
                    "favorite": False,
                    "avatar_prompt": "",
                    "avatar_image_path": "",
                },
            ],
        )

        migration.op = Operations(
            MigrationContext.configure(connection, opts={"render_as_batch": True})
        )
        migration.upgrade()

        upgraded = sa.Table(
            "virtual_player_profiles",
            sa.MetaData(),
            autoload_with=connection,
        )
        assert {
            "favorite",
            "owner_user_id",
            "avatar_prompt",
            "avatar_image_path",
        }.isdisjoint(upgraded.c.keys())
        assert upgraded.c.display_order.nullable is True
        rows = connection.execute(
            sa.select(
                upgraded.c.id,
                upgraded.c.status,
                upgraded.c.display_order,
            ).order_by(upgraded.c.id)
        ).mappings()
        assert {
            row["id"]: row["display_order"]
            for row in rows
        } == {
            "archived": None,
            "draft": None,
            "legacy-deleted-published": None,
            "published-a": 1,
            "published-b": 2,
            "published-c": 3,
        }
        assert connection.execute(
            sa.select(upgraded.c.status).where(
                upgraded.c.id == "legacy-deleted-published"
            )
        ).scalar_one() == "archived"

        connection.execute(sa.insert(upgraded), {"id": "default-draft"})
        default_draft = connection.execute(
            sa.select(
                upgraded.c.status,
                upgraded.c.published_at,
                upgraded.c.display_order,
            ).where(upgraded.c.id == "default-draft")
        ).one()
        assert default_draft == ("draft", None, None)

        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                connection.execute(
                    sa.insert(upgraded),
                    {
                        "id": "invalid-draft-order",
                        "status": "draft",
                        "published_at": None,
                        "display_order": 9,
                    },
                )
        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                connection.execute(
                    sa.insert(upgraded),
                    {
                        "id": "duplicate-published-order",
                        "status": "published",
                        "display_order": 1,
                    },
                )

        migration.downgrade()
        downgraded = sa.Table(
            "virtual_player_profiles",
            sa.MetaData(),
            autoload_with=connection,
        )
        assert {
            "favorite",
            "owner_user_id",
            "avatar_prompt",
            "avatar_image_path",
        }.issubset(downgraded.c.keys())
        assert downgraded.c.display_order.nullable is False
        assert connection.execute(
            sa.select(downgraded.c.display_order).order_by(
                downgraded.c.display_order
            )
        ).scalars().all() == [1, 2, 3, 4, 5, 6, 7]
