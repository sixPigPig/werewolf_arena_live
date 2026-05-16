from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.user import User
from app.models.virtual_player_profile import VirtualPlayerProfile


def test_user_table_is_registered_in_metadata() -> None:
    assert User.__table__.name == "users"
    assert "users" in Base.metadata.tables


def test_user_table_matches_expected_schema() -> None:
    table = User.__table__
    column_names = set(table.columns.keys())

    assert column_names == {"id", "email", "display_name", "created_at"}
    assert table.c.email.unique is True
    assert table.c.email.index is True
    assert any(index.name == "ix_users_email" for index in table.indexes)
    assert table.c.created_at.server_default is not None
    assert "now" in str(table.c.created_at.server_default.arg).lower()


def test_virtual_player_profile_table_is_registered_in_metadata() -> None:
    assert VirtualPlayerProfile.__table__.name == "virtual_player_profiles"
    assert "virtual_player_profiles" in Base.metadata.tables


def test_virtual_player_profile_table_matches_expected_schema() -> None:
    table = VirtualPlayerProfile.__table__
    column_names = set(table.columns.keys())

    assert column_names == {
        "id",
        "owner_user_id",
        "display_name",
        "model",
        "personality_id",
        "personality_text",
        "appearance_id",
        "avatar_prompt",
        "tags",
        "created_at",
        "updated_at",
    }
    assert table.c.id.primary_key is True
    assert table.c.owner_user_id.foreign_keys
    assert table.c.owner_user_id.index is True
    assert table.c.display_name.nullable is False
    assert table.c.model.nullable is False
    assert table.c.personality_id.nullable is False
    assert table.c.appearance_id.nullable is False
    assert table.c.tags.nullable is False
    assert table.c.created_at.server_default is not None
    assert table.c.updated_at.server_default is not None


def test_virtual_player_profile_tag_append_is_persisted() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        profile = VirtualPlayerProfile(
            id="profile-1",
            display_name="控场位",
            model="gpt-4.1-mini",
            personality_id="balanced",
            personality_text="稳健推进",
            appearance_id="default",
            avatar_prompt="",
            tags=[],
        )
        session.add(profile)
        session.commit()

        profile.tags.append("控场")
        session.commit()
        session.expunge_all()

        saved_profile = session.get(VirtualPlayerProfile, "profile-1")

    assert saved_profile is not None
    assert saved_profile.tags == ["控场"]
