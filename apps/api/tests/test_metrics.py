from threading import Thread
from unittest.mock import Mock

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.game_session import GameSessionRecord
from app.models.rule_set import RuleSetRecord
from app.rule_sets.telemetry import (
    _reset_rule_set_metrics_for_tests,
    record_legacy_rule_create,
    record_rule_checkpoint_failure,
    record_rule_create_conflict,
    record_rule_publish,
    record_rule_snapshot_failure,
    render_rule_set_metrics,
)
from tests.rule_set_fixtures import seed_official_rule_sets


client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_rule_metrics() -> None:
    _reset_rule_set_metrics_for_tests()


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_metrics_endpoint_returns_prometheus_text_without_cache() -> None:
    testing_session = _session_factory()
    record_rule_publish("success")
    record_rule_create_conflict("classic_8", 1)
    record_rule_snapshot_failure("content_hash_mismatch")
    record_rule_checkpoint_failure("invalid_structure")
    record_legacy_rule_create("starter_6", 1)
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
    assert "# TYPE werewolf_rule_publish_total counter" in response.text
    assert 'werewolf_rule_publish_total{result="success"} 1' in response.text
    assert "# TYPE werewolf_rule_create_conflicts_total counter" in response.text
    assert (
        'werewolf_rule_create_conflicts_total{rule_set_id="classic_8",revision_no="1"} 1'
        in response.text
    )
    assert "# TYPE werewolf_rule_snapshot_failures_total counter" in response.text
    assert "# TYPE werewolf_rule_checkpoint_failures_total counter" in response.text
    assert "# TYPE werewolf_rule_legacy_creates_total counter" in response.text
    assert "# TYPE werewolf_rule_games gauge" in response.text
    assert "# TYPE werewolf_rule_game_failure_ratio_delta gauge" in response.text
    assert "# TYPE werewolf_rule_published_defaults gauge" in response.text
    assert "werewolf_rule_published_defaults 0" in response.text


def test_rule_metrics_render_all_fixed_results_and_reasons() -> None:
    publish_results = ("success", "rejected", "conflict", "failure")
    snapshot_reasons = (
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
    )
    checkpoint_reasons = (
        "missing",
        "unsupported_schema",
        "invalid_structure",
        "invalid_rule_snapshot",
        "rule_snapshot_mismatch",
        "rule_metadata_mismatch",
    )
    for result in publish_results:
        record_rule_publish(result)
    for reason in snapshot_reasons:
        record_rule_snapshot_failure(reason)
    for reason in checkpoint_reasons:
        record_rule_checkpoint_failure(reason)

    with _session_factory()() as db:
        metrics = render_rule_set_metrics(db)

    for result in publish_results:
        assert f'werewolf_rule_publish_total{{result="{result}"}} 1' in metrics
    for reason in snapshot_reasons:
        assert f'werewolf_rule_snapshot_failures_total{{reason="{reason}"}} 1' in metrics
    for reason in checkpoint_reasons:
        assert f'werewolf_rule_checkpoint_failures_total{{reason="{reason}"}} 1' in metrics


def test_rule_metrics_use_only_scalar_game_columns_and_group_normalized_values() -> None:
    marker = 'SECRET description {winner="张三"}\\nwerewolf_injected 1'
    session_factory = _session_factory()
    with session_factory() as db:
        db.add_all(
            [
                GameSessionRecord(
                    session_id="game_00000001",
                    status="complete",
                    rule_set_id="classic_8",
                    rule_set_revision_no=1,
                    rule_set={"id": marker, "revision_no": 999, "description": marker},
                ),
                GameSessionRecord(
                    session_id="game_00000002",
                    status="complete",
                    rule_set_id="classic_8",
                    rule_set_revision_no=1,
                    rule_set={"id": "other_json_rule", "revision_no": 2},
                ),
                GameSessionRecord(
                    session_id="game_00000003",
                    status="partial",
                    rule_set_id="classic_8",
                    rule_set_revision_no=None,
                    rule_set={"description": marker},
                ),
                GameSessionRecord(
                    session_id="game_00000004",
                    status=marker,
                    rule_set_id=marker,
                    rule_set_revision_no=-1,
                    rule_set={"description": marker},
                ),
            ]
        )
        db.commit()
        metrics = render_rule_set_metrics(db)

    assert (
        'werewolf_rule_games{rule_set_id="classic_8",revision_no="1",status="complete"} 2'
        in metrics
    )
    assert (
        'werewolf_rule_games{rule_set_id="classic_8",revision_no="legacy",status="partial"} 1'
        in metrics
    )
    assert (
        'werewolf_rule_games{rule_set_id="unknown",revision_no="unknown",status="other"} 1'
        in metrics
    )
    assert marker not in metrics
    assert "other_json_rule" not in metrics
    assert "999" not in metrics


def test_rule_metrics_compare_failure_ratio_with_preceding_numeric_revision() -> None:
    session_factory = _session_factory()
    with session_factory() as db:
        db.add_all(
            [
                GameSessionRecord(
                    session_id=f"game_{index:08d}",
                    status="partial" if index >= 36 else "complete",
                    rule_set_id="history_rule",
                    rule_set_revision_no=1 if index < 20 else 2,
                )
                for index in range(40)
            ]
        )
        db.commit()
        metrics = render_rule_set_metrics(db)

    assert (
        'werewolf_rule_game_failure_ratio_delta{rule_set_id="history_rule",revision_no="2"} 0.2'
        in metrics
    )
    assert 'revision_no="1"} 0' not in metrics


def test_rule_published_default_count_covers_zero_one_and_corrupt_many() -> None:
    session_factory = _session_factory()
    with session_factory() as db:
        assert "werewolf_rule_published_defaults 0" in render_rule_set_metrics(db)
        seed_official_rule_sets(db)
        db.commit()
        assert "werewolf_rule_published_defaults 1" in render_rule_set_metrics(db)

        db.execute(update(RuleSetRecord).values(is_default=False))
        db.commit()
        default_index = next(
            index
            for index in RuleSetRecord.__table__.indexes
            if index.name == "uq_rule_sets_one_default"
        )
        default_index.drop(db.connection())
        db.execute(
            update(RuleSetRecord)
            .where(RuleSetRecord.id.in_(("classic_8", "starter_6")))
            .values(is_default=True)
        )
        db.commit()
        assert "werewolf_rule_published_defaults 2" in render_rule_set_metrics(db)


def test_rule_metric_recorders_are_thread_safe_and_deterministic() -> None:
    threads = [
        Thread(target=lambda: [record_rule_create_conflict("classic_8", 1) for _ in range(200)])
        for _ in range(8)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    with _session_factory()() as db:
        first = render_rule_set_metrics(db)
        second = render_rule_set_metrics(db)

    assert first == second
    assert (
        'werewolf_rule_create_conflicts_total{rule_set_id="classic_8",revision_no="1"} 1600'
        in first
    )


def test_rule_metric_513th_dynamic_series_uses_overflow_bucket() -> None:
    for index in range(513):
        record_rule_create_conflict(f"rule_{index:04d}", index + 1)

    with _session_factory()() as db:
        metrics = render_rule_set_metrics(db)

    samples = [
        line
        for line in metrics.splitlines()
        if line.startswith("werewolf_rule_create_conflicts_total{")
    ]
    assert len(samples) == 512
    assert (
        'werewolf_rule_create_conflicts_total{rule_set_id="overflow",revision_no="overflow"} 2'
        in samples
    )


def test_rule_metric_labels_and_reset_never_leak_unbounded_input() -> None:
    marker = 'SECRET description {winner="张三"}\\nwerewolf_injected 1'
    revision_uuid = "e9fa678e-9b18-5079-91d2-f74835364fb6"
    record_rule_publish(marker)
    record_rule_create_conflict(marker, revision_uuid)  # type: ignore[arg-type]
    record_rule_snapshot_failure(marker)
    record_rule_checkpoint_failure(marker)
    record_legacy_rule_create(marker, -1)

    with _session_factory()() as db:
        metrics = render_rule_set_metrics(db)

    assert marker not in metrics
    assert revision_uuid not in metrics
    assert "winner" not in metrics
    assert 'werewolf_rule_publish_total{result="unknown"} 1' in metrics
    assert (
        'werewolf_rule_create_conflicts_total{rule_set_id="unknown",revision_no="unknown"} 1'
        in metrics
    )
    _reset_rule_set_metrics_for_tests()
    with _session_factory()() as db:
        reset_metrics = render_rule_set_metrics(db)
    assert 'werewolf_rule_publish_total{result="unknown"} 0' in reset_metrics
    assert "werewolf_rule_create_conflicts_total{" not in reset_metrics


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
