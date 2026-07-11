from unittest.mock import Mock

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app


client = TestClient(app)


def test_metrics_endpoint_returns_prometheus_text_without_cache() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with testing_session() as db:
        app.dependency_overrides[get_db] = lambda: db
        try:
            response = client.get("/api/v1/metrics")
        finally:
            app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["cache-control"] == "no-store"
    assert "werewolf_live_run_reaper_up 0" in response.text
    assert "# TYPE werewolf_live_run_reaper_scans_total counter" in response.text


def test_metrics_endpoint_hides_database_failures() -> None:
    session = Mock()
    session.scalars.side_effect = SQLAlchemyError("secret database details")
    app.dependency_overrides[get_db] = lambda: session
    try:
        response = client.get("/api/v1/metrics")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.text == "# metrics unavailable\n"
    assert "secret" not in response.text
