"""Tests for src/resources/log/entity.py"""

import pytest

from src.resources.log.entity import (
    LogEntity,
    CreateLogEntity,
    CreateStartUpErrorLog,
    AnalysisStoppedLog,
)
from src.status.constants import _MAX_RESTARTS


# ─── LogEntity ────────────────────────────────────────────────────────────────

class TestLogEntity:
    def test_creation_with_required_fields(self):
        entity = LogEntity(log="test message", log_type="info", id="id-1", created_at="2026-01-01")
        assert entity.log == "test message"
        assert entity.log_type == "info"

    def test_id_and_created_at_are_strings(self):
        entity = LogEntity(log="msg", log_type="debug", id="id-1", created_at="2026-01-01")
        assert isinstance(entity.id, str)
        assert isinstance(entity.created_at, str)

    @pytest.mark.parametrize("log_type", [
        "emerg", "alert", "crit", "error", "warn", "notice", "info", "debug"
    ])
    def test_all_valid_log_types(self, log_type):
        entity = LogEntity(log="msg", log_type=log_type, id="id-1", created_at="2026-01-01")
        assert entity.log_type == log_type

    def test_invalid_log_type_raises(self):
        with pytest.raises(Exception):
            LogEntity(log="msg", log_type="invalid", id="id-1", created_at="2026-01-01")

    def test_str_representation(self):
        entity = LogEntity(log="hello", log_type="warn", id="id-1", created_at="2026-01-01")
        s = str(entity)
        assert "LogEntity" in s
        assert entity.id in s
        assert "hello" in s
        assert "warn" in s


# ─── CreateLogEntity ──────────────────────────────────────────────────────────

class TestCreateLogEntity:
    def test_creation(self):
        entity = CreateLogEntity(
            log="test",
            log_type="info",
            analysis_id="analysis-1",
            status="started",
            progress=50,
        )
        assert entity.log == "test"
        assert entity.analysis_id == "analysis-1"
        assert entity.status == "started"
        assert entity.progress == 50

    def test_to_log_entity_returns_log_entity(self):
        entity = CreateLogEntity(
            log="my log",
            log_type="error",
            analysis_id="analysis-1",
            status="failed",
            progress=10,
        )
        result = entity.to_log_entity()
        assert isinstance(result, LogEntity)

    def test_to_log_entity_copies_log_and_type(self):
        entity = CreateLogEntity(
            log="the message",
            log_type="warn",
            analysis_id="analysis-1",
            status="started",
            progress=0,
        )
        result = entity.to_log_entity()
        assert result.log == "the message"
        assert result.log_type == "warn"

    def test_to_log_entity_drops_analysis_fields(self):
        entity = CreateLogEntity(
            log="msg",
            log_type="debug",
            analysis_id="analysis-42",
            status="executing",
            progress=99,
        )
        result = entity.to_log_entity()
        assert not hasattr(result, "analysis_id")
        assert not hasattr(result, "status")
        assert not hasattr(result, "progress")


# ─── CreateStartUpErrorLog ────────────────────────────────────────────────────

class TestCreateStartUpErrorLog:
    def test_stuck_type_log_content(self):
        log = CreateStartUpErrorLog(
            restart_num=1,
            error_type="stuck",
            analysis_id="analysis-1",
            status="stuck",
        )
        assert "ANALYSISSTARTUPERROR" in log.log
        assert "failed to connect" in log.log
        assert f"restart 1 of {_MAX_RESTARTS}" in log.log
        assert log.log_type == "error"
        assert log.analysis_id == "analysis-1"
        assert log.status == "stuck"
        assert log.progress == 0

    def test_slow_type_log_content(self):
        log = CreateStartUpErrorLog(
            restart_num=3,
            error_type="slow",
            analysis_id="analysis-2",
            status="stuck",
        )
        assert "took to long during startup" in log.log
        assert f"restart 3 of {_MAX_RESTARTS}" in log.log
        assert log.log_type == "error"

    def test_k8s_type_log_content_no_k8s_msg(self):
        log = CreateStartUpErrorLog(
            restart_num=2,
            error_type="k8s",
            analysis_id="analysis-3",
            status="stuck",
        )
        assert "failed to deploy in kubernetes" in log.log
        assert f"restart 2 of {_MAX_RESTARTS}" in log.log
        assert "KubernetesApiError" not in log.log

    def test_k8s_type_log_content_with_k8s_msg(self):
        log = CreateStartUpErrorLog(
            restart_num=2,
            error_type="k8s",
            analysis_id="analysis-3",
            status="stuck",
            k8s_error_msg="ImagePullBackOff",
        )
        assert "KubernetesApiError: ImagePullBackOff" in log.log

    def test_termination_message_at_max_restarts(self):
        log = CreateStartUpErrorLog(
            restart_num=_MAX_RESTARTS,
            error_type="stuck",
            analysis_id="analysis-4",
            status="stuck",
        )
        assert "Terminating analysis as failed" in log.log

    def test_no_termination_message_below_max_restarts(self):
        log = CreateStartUpErrorLog(
            restart_num=_MAX_RESTARTS - 1,
            error_type="stuck",
            analysis_id="analysis-4",
            status="stuck",
        )
        assert "Terminating" not in log.log

    def test_unknown_error_type_produces_empty_log(self):
        log = CreateStartUpErrorLog(
            restart_num=1,
            error_type="unknown",  # type: ignore[arg-type]
            analysis_id="analysis-5",
            status="stuck",
        )
        assert log.log == ""

    def test_restart_num_reflected_in_log(self):
        for num in [1, 5, _MAX_RESTARTS]:
            log = CreateStartUpErrorLog(
                restart_num=num,
                error_type="slow",
                analysis_id="analysis-1",
                status="stuck",
            )
            assert f"restart {num} of {_MAX_RESTARTS}" in log.log

    def test_is_create_log_entity_subclass(self):
        log = CreateStartUpErrorLog(
            restart_num=1,
            error_type="stuck",
            analysis_id="analysis-1",
            status="stuck",
        )
        assert isinstance(log, CreateLogEntity)

    def test_to_log_entity(self):
        log = CreateStartUpErrorLog(
            restart_num=1,
            error_type="k8s",
            analysis_id="analysis-1",
            status="stuck",
        )
        result = log.to_log_entity()
        assert isinstance(result, LogEntity)
        assert result.log_type == "error"


# ─── AnalysisStoppedLog ───────────────────────────────────────────────────────

class TestAnalysisStoppedLog:
    def test_instantiation(self):
        """AnalysisStoppedLog can be created with just an analysis_id."""
        log = AnalysisStoppedLog(analysis_id="analysis-1")
        assert log.analysis_id == "analysis-1"
        assert log.progress == 0
        assert log.log_type == "info"
        assert log.status == "stopped"

    def test_log_content(self):
        """Verify log message content."""
        log = AnalysisStoppedLog(analysis_id="analysis-99")
        assert "ANALYSISSTOPPED" in log.log
        assert log.analysis_id == "analysis-99"
        assert log.log_type == "info"