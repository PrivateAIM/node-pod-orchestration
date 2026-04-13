"""Tests for src/resources/database/entity.py — SQLite in-memory backend."""

import json
import time
from unittest.mock import patch

import pytest

from src.resources.database.db_models import Base


# ─── Fixture ─────────────────────────────────────────────────────────────────


@pytest.fixture
def db():
    """Database instance backed by SQLite in-memory."""
    from sqlalchemy import create_engine as real_create_engine

    sqlite_engine = real_create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )

    with patch("src.resources.database.entity.create_engine", return_value=sqlite_engine):
        from src.resources.database.entity import Database

        database = Database()

    yield database

    Base.metadata.drop_all(bind=sqlite_engine)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _insert(db, analysis_id="a1", deployment_name="analysis-a1-0", **kwargs):
    """Insert a record with sensible defaults."""
    defaults = dict(
        analysis_id=analysis_id,
        deployment_name=deployment_name,
        project_id="proj1",
        pod_ids=["pod-1"],
        status="started",
        registry_url="harbor.test",
        image_url="harbor.test/img",
        registry_user="user",
        registry_password="pw",
        kong_token="token",
        restart_counter=0,
        progress=0,
    )
    defaults.update(kwargs)
    return db.create_analysis(**defaults)


# ─── create_analysis ─────────────────────────────────────────────────────────


class TestCreateAnalysis:
    def test_returns_record_with_correct_fields(self, db):
        record = _insert(db)
        assert record.analysis_id == "a1"
        assert record.deployment_name == "analysis-a1-0"
        assert record.project_id == "proj1"

    def test_sets_time_created(self, db):
        before = time.time()
        record = _insert(db)
        after = time.time()
        assert before <= record.time_created <= after

    def test_serializes_pod_ids_as_json_string(self, db):
        record = _insert(db, pod_ids=["pod-1", "pod-2"])
        assert record.pod_ids == json.dumps(["pod-1", "pod-2"])

    def test_respects_custom_namespace(self, db):
        record = _insert(db, namespace="custom-ns")
        assert record.namespace == "custom-ns"

    def test_default_namespace_is_default(self, db):
        record = _insert(db)
        assert record.namespace == "default"


# ─── get_deployment / get_latest_deployment / get_deployments ────────────────


class TestGetDeployment:
    def test_get_deployment_found(self, db):
        _insert(db)
        record = db.get_deployment("analysis-a1-0")
        assert record is not None
        assert record.deployment_name == "analysis-a1-0"

    def test_get_deployment_not_found(self, db):
        assert db.get_deployment("nonexistent") is None

    def test_get_latest_deployment_found(self, db):
        _insert(db)
        record = db.get_latest_deployment("a1")
        assert record is not None
        assert record.analysis_id == "a1"

    def test_get_latest_deployment_not_found(self, db):
        assert db.get_latest_deployment("nonexistent") is None

    def test_get_latest_deployment_returns_last(self, db):
        _insert(db, deployment_name="analysis-a1-0")
        _insert(db, deployment_name="analysis-a1-1")
        record = db.get_latest_deployment("a1")
        assert record.deployment_name == "analysis-a1-1"

    def test_get_deployments_returns_all(self, db):
        _insert(db, deployment_name="analysis-a1-0")
        _insert(db, deployment_name="analysis-a1-1")
        records = db.get_deployments("a1")
        assert len(records) == 2

    def test_get_deployments_empty(self, db):
        assert db.get_deployments("nonexistent") == []


# ─── analysis_is_running ─────────────────────────────────────────────────────


class TestAnalysisIsRunning:
    def test_started_is_running(self, db):
        _insert(db, status="started")
        assert db.analysis_is_running("a1") is True

    def test_executed_is_not_running(self, db):
        _insert(db, status="executed")
        assert db.analysis_is_running("a1") is False

    def test_stopped_is_not_running(self, db):
        _insert(db, status="stopped")
        assert db.analysis_is_running("a1") is False

    def test_failed_is_not_running(self, db):
        _insert(db, status="failed")
        assert db.analysis_is_running("a1") is False

    def test_no_deployment_is_not_running(self, db):
        assert db.analysis_is_running("nonexistent") is False


# ─── update_analysis / update_deployment ─────────────────────────────────────


class TestUpdate:
    def test_update_analysis_updates_all_deployments(self, db):
        _insert(db, deployment_name="analysis-a1-0")
        _insert(db, deployment_name="analysis-a1-1")
        db.update_analysis("a1", status="executing")
        for d in db.get_deployments("a1"):
            assert d.status == "executing"

    def test_update_deployment_updates_only_one(self, db):
        _insert(db, deployment_name="analysis-a1-0")
        _insert(db, deployment_name="analysis-a1-1")
        db.update_deployment("analysis-a1-0", status="executing")
        assert db.get_deployment("analysis-a1-0").status == "executing"
        assert db.get_deployment("analysis-a1-1").status == "started"

    def test_update_analysis_status(self, db):
        _insert(db)
        db.update_analysis_status("a1", "executing")
        assert db.get_latest_deployment("a1").status == "executing"

    def test_update_deployment_status(self, db):
        _insert(db)
        db.update_deployment_status("analysis-a1-0", "executing")
        assert db.get_deployment("analysis-a1-0").status == "executing"

    def test_update_analysis_progress(self, db):
        _insert(db)
        db.update_analysis_progress("a1", 50)
        assert db.get_latest_deployment("a1").progress == 50


# ─── delete_analysis / delete_deployment ─────────────────────────────────────


class TestDelete:
    def test_delete_analysis_removes_all(self, db):
        _insert(db, deployment_name="analysis-a1-0")
        _insert(db, deployment_name="analysis-a1-1")
        db.delete_analysis("a1")
        assert db.get_deployments("a1") == []

    def test_delete_deployment_removes_one(self, db):
        _insert(db, deployment_name="analysis-a1-0")
        _insert(db, deployment_name="analysis-a1-1")
        db.delete_deployment("analysis-a1-0")
        assert db.get_deployment("analysis-a1-0") is None
        assert db.get_deployment("analysis-a1-1") is not None

    def test_delete_deployment_not_found_no_error(self, db):
        db.delete_deployment("nonexistent")  # must not raise


# ─── get_analysis_ids / get_deployment_ids / pod_ids ─────────────────────────


class TestIds:
    def test_get_analysis_ids(self, db):
        _insert(db, analysis_id="a1", deployment_name="analysis-a1-0")
        _insert(db, analysis_id="a2", deployment_name="analysis-a2-0")
        assert set(db.get_analysis_ids()) == {"a1", "a2"}

    def test_get_deployment_ids(self, db):
        _insert(db, deployment_name="analysis-a1-0")
        _insert(db, deployment_name="analysis-a1-1")
        assert set(db.get_deployment_ids()) == {"analysis-a1-0", "analysis-a1-1"}

    def test_get_deployment_pod_ids(self, db):
        _insert(db, pod_ids=["pod-1", "pod-2"])
        result = db.get_deployment_pod_ids("analysis-a1-0")
        assert result == json.dumps(["pod-1", "pod-2"])

    def test_get_analysis_pod_ids_returns_list_of_pod_lists(self, db):
        _insert(db, deployment_name="analysis-a1-0", pod_ids=["pod-1"])
        _insert(db, deployment_name="analysis-a1-1", pod_ids=["pod-2"])
        result = db.get_analysis_pod_ids("a1")
        assert len(result) == 2


# ─── get_analysis_log / update_analysis_log ──────────────────────────────────


class TestLog:
    def test_get_log_returns_empty_string_when_null(self, db):
        _insert(db)
        assert db.get_analysis_log("a1") == ""

    def test_get_log_returns_content(self, db):
        _insert(db)
        db.update_analysis("a1", log="hello")
        assert db.get_analysis_log("a1") == "hello"

    def test_get_log_not_found_returns_empty_string(self, db):
        assert db.get_analysis_log("nonexistent") == ""

    def test_update_log_sets_first_entry(self, db):
        _insert(db)
        db.update_analysis_log("a1", "first message")
        assert db.get_analysis_log("a1") == "first message"

    def test_update_log_appends_with_newline(self, db):
        _insert(db)
        db.update_analysis_log("a1", "first")
        db.update_analysis_log("a1", "second")
        assert db.get_analysis_log("a1") == "first\nsecond"


# ─── get_analysis_progress / progress_valid ──────────────────────────────────


class TestProgress:
    def test_get_progress_returns_value(self, db):
        _insert(db, progress=25)
        assert db.get_analysis_progress("a1") == 25

    def test_get_progress_not_found_returns_none(self, db):
        assert db.get_analysis_progress("nonexistent") is None

    def test_progress_valid_within_range(self, db):
        _insert(db, progress=10)
        assert db.progress_valid("a1", 50) is True

    def test_progress_valid_equal_to_current_is_false(self, db):
        _insert(db, progress=50)
        assert db.progress_valid("a1", 50) is False

    def test_progress_valid_below_current_is_false(self, db):
        _insert(db, progress=50)
        assert db.progress_valid("a1", 30) is False

    def test_progress_valid_over_100_is_false(self, db):
        _insert(db, progress=50)
        assert db.progress_valid("a1", 101) is False

    def test_progress_valid_exactly_100_is_valid(self, db):
        _insert(db, progress=50)
        assert db.progress_valid("a1", 100) is True

    def test_progress_valid_no_deployment_is_false(self, db):
        assert db.progress_valid("nonexistent", 50) is False


# ─── stop_analysis / extract_analysis_body ───────────────────────────────────


class TestStopAndExtract:
    def test_stop_analysis_sets_stopped_status(self, db):
        _insert(db)
        db.stop_analysis("a1")
        assert db.get_latest_deployment("a1").status == "stopped"

    def test_extract_analysis_body_returns_expected_keys(self, db):
        _insert(db)
        body = db.extract_analysis_body("a1")
        assert body is not None
        for key in (
            "analysis_id", "project_id", "registry_url", "image_url",
            "registry_user", "registry_password", "namespace",
            "kong_token", "restart_counter", "progress",
        ):
            assert key in body

    def test_extract_analysis_body_resets_progress_to_zero(self, db):
        _insert(db, progress=99)
        body = db.extract_analysis_body("a1")
        assert body["progress"] == 0

    def test_extract_analysis_body_not_found_returns_none(self, db):
        assert db.extract_analysis_body("nonexistent") is None


# ─── delete_old_deployments_from_db ──────────────────────────────────────────


class TestDeleteOldDeployments:
    def test_keeps_only_latest_by_time_created(self, db):
        _insert(db, deployment_name="analysis-a1-0")
        db.update_deployment("analysis-a1-0", time_created=1000.0)
        _insert(db, deployment_name="analysis-a1-1")
        db.update_deployment("analysis-a1-1", time_created=2000.0)

        db.delete_old_deployments_from_db("a1")

        remaining = db.get_deployments("a1")
        assert len(remaining) == 1
        assert remaining[0].deployment_name == "analysis-a1-1"

    def test_single_deployment_unchanged(self, db):
        _insert(db)
        db.delete_old_deployments_from_db("a1")
        assert len(db.get_deployments("a1")) == 1

    def test_no_deployments_no_error(self, db):
        db.delete_old_deployments_from_db("nonexistent")  # must not raise

    def test_three_deployments_keeps_newest(self, db):
        for i, t in enumerate([1000.0, 2000.0, 3000.0]):
            _insert(db, deployment_name=f"analysis-a1-{i}")
            db.update_deployment(f"analysis-a1-{i}", time_created=t)

        db.delete_old_deployments_from_db("a1")

        remaining = db.get_deployments("a1")
        assert len(remaining) == 1
        assert remaining[0].deployment_name == "analysis-a1-2"