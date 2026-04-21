"""Tests for src/status/constants.py"""

from src.status.constants import AnalysisStatus, _MAX_RESTARTS, _INTERNAL_STATUS_TIMEOUT


class TestAnalysisStatusEnum:
    def test_all_values_present(self):
        values = {s.value for s in AnalysisStatus}
        assert values == {
            "starting",
            "started",
            "stuck",
            "stopping",
            "stopped",
            "executing",
            "executed",
            "failed",
        }

    def test_starting(self):
        assert AnalysisStatus.STARTING.value == "starting"

    def test_started(self):
        assert AnalysisStatus.STARTED.value == "started"

    def test_stuck(self):
        assert AnalysisStatus.STUCK.value == "stuck"

    def test_stopping(self):
        assert AnalysisStatus.STOPPING.value == "stopping"

    def test_stopped(self):
        assert AnalysisStatus.STOPPED.value == "stopped"

    def test_executing(self):
        assert AnalysisStatus.EXECUTING.value == "executing"

    def test_executed(self):
        assert AnalysisStatus.EXECUTED.value == "executed"

    def test_failed(self):
        assert AnalysisStatus.FAILED.value == "failed"

    def test_member_count(self):
        assert len(AnalysisStatus) == 8

    def test_lookup_by_value(self):
        assert AnalysisStatus("executing") is AnalysisStatus.EXECUTING

    def test_invalid_value_raises(self):
        import pytest
        with pytest.raises(ValueError):
            AnalysisStatus("nonexistent")


class TestConstants:
    def test_max_restarts_value(self):
        assert _MAX_RESTARTS == 10

    def test_internal_status_timeout_value(self):
        assert _INTERNAL_STATUS_TIMEOUT == 10

    def test_max_restarts_is_int(self):
        assert isinstance(_MAX_RESTARTS, int)

    def test_internal_status_timeout_is_int(self):
        assert isinstance(_INTERNAL_STATUS_TIMEOUT, int)