"""Tests for src/status/status.py.

Does NOT test status_loop itself (infinite loop — untestable without mocking time).
Tests all helper functions: _decide_status_action, _get_analysis_status,
_get_internal_deployment_status, _refresh_keycloak_token,
inform_analysis_of_partner_statuses, _fix_stuck_status,
_update_running_status, _update_finished_status, _set_analysis_hub_status.
"""

from unittest.mock import MagicMock, patch

import pytest
from httpx import ConnectError, ConnectTimeout

from src.status.constants import AnalysisStatus, _MAX_RESTARTS
from src.status.status import (
    _decide_status_action,
    _fix_stuck_status,
    _get_analysis_status,
    _get_internal_deployment_status,
    _refresh_keycloak_token,
    _set_analysis_hub_status,
    _update_finished_status,
    _update_running_status,
    inform_analysis_of_partner_statuses,
)


# ─── TestDecideStatusAction ───────────────────────────────────────────────────

class TestDecideStatusAction:
    """All 9 combinations of db_status × int_status."""

    def test_stuck_any_db_status_returns_unstuck(self):
        # is_stuck: int_status=STUCK regardless of db_status
        assert _decide_status_action(AnalysisStatus.EXECUTING.value, AnalysisStatus.STUCK.value) == "unstuck"

    def test_slow_started_failed_returns_unstuck(self):
        # is_slow: db=STARTED + int=FAILED
        assert _decide_status_action(AnalysisStatus.STARTED.value, AnalysisStatus.FAILED.value) == "unstuck"

    def test_newly_running_returns_running(self):
        # db=STARTED + int=EXECUTING
        assert _decide_status_action(AnalysisStatus.STARTED.value, AnalysisStatus.EXECUTING.value) == "running"

    def test_speedy_finished_returns_finishing(self):
        # db=STARTED + int=EXECUTED
        assert _decide_status_action(AnalysisStatus.STARTED.value, AnalysisStatus.EXECUTED.value) == "finishing"

    def test_newly_ended_executing_to_executed_returns_finishing(self):
        # db=EXECUTING + int=EXECUTED
        assert _decide_status_action(AnalysisStatus.EXECUTING.value, AnalysisStatus.EXECUTED.value) == "finishing"

    def test_newly_ended_executing_to_failed_returns_finishing(self):
        # db=EXECUTING + int=FAILED (newly_ended)
        assert _decide_status_action(AnalysisStatus.EXECUTING.value, AnalysisStatus.FAILED.value) == "finishing"

    def test_firmly_stuck_failed_db_stuck_int_returns_unstuck(self):
        # db=FAILED + int=STUCK: is_stuck fires before firmly_stuck branch
        # Note: firmly_stuck (db=FAILED, int=STUCK) overlaps with is_stuck,
        # so this returns 'unstuck', not 'finishing'.
        assert _decide_status_action(AnalysisStatus.FAILED.value, AnalysisStatus.STUCK.value) == "unstuck"

    def test_was_stopped_returns_finishing(self):
        # int_status=STOPPED
        assert _decide_status_action(AnalysisStatus.EXECUTING.value, AnalysisStatus.STOPPED.value) == "finishing"

    def test_no_matching_condition_returns_none(self):
        # db=EXECUTING + int=EXECUTING: no condition matches
        assert _decide_status_action(AnalysisStatus.EXECUTING.value, AnalysisStatus.EXECUTING.value) is None


# ─── TestGetAnalysisStatus ────────────────────────────────────────────────────

class TestGetAnalysisStatus:
    def test_not_found_returns_none(self, mock_database):
        mock_database.get_latest_deployment.return_value = None
        assert _get_analysis_status("analysis_id", mock_database) is None

    def test_already_executed_skips_internal_check(self, mock_database, sample_analysis_db):
        analysis = sample_analysis_db(status=AnalysisStatus.EXECUTED.value)
        mock_database.get_latest_deployment.return_value = analysis

        result = _get_analysis_status("analysis_id", mock_database)

        assert result["db_status"] == AnalysisStatus.EXECUTED.value
        assert result["int_status"] == AnalysisStatus.EXECUTED.value

    @patch("src.status.status._get_internal_deployment_status")
    def test_found_non_executed_calls_internal_check(self, mock_internal, mock_database, sample_analysis_db):
        analysis = sample_analysis_db(status=AnalysisStatus.EXECUTING.value, deployment_name="dep-name")
        mock_database.get_latest_deployment.return_value = analysis
        mock_internal.return_value = AnalysisStatus.EXECUTING.value

        result = _get_analysis_status("analysis_id", mock_database)

        mock_internal.assert_called_once_with("dep-name", "analysis_id")
        assert result["analysis_id"] == "analysis_id"
        assert result["db_status"] == AnalysisStatus.EXECUTING.value
        assert result["int_status"] == AnalysisStatus.EXECUTING.value
        assert "status_action" in result


# ─── TestGetInternalDeploymentStatus ─────────────────────────────────────────

class TestGetInternalDeploymentStatus:
    @patch("src.status.status._refresh_keycloak_token")
    @patch("src.status.status.Client")
    def test_executing_status_returned(self, mock_client_cls, mock_refresh):
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "executing", "token_remaining_time": 9999}
        mock_client_cls.return_value.get.return_value = mock_response

        result = _get_internal_deployment_status("dep-name", "analysis_id")

        assert result == AnalysisStatus.EXECUTING.value

    @patch("src.status.status._refresh_keycloak_token")
    @patch("src.status.status.Client")
    def test_executed_status_returned(self, mock_client_cls, mock_refresh):
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "executed", "token_remaining_time": 9999}
        mock_client_cls.return_value.get.return_value = mock_response

        result = _get_internal_deployment_status("dep-name", "analysis_id")

        assert result == AnalysisStatus.EXECUTED.value

    @patch("src.status.status.time")
    @patch("src.status.status.Client")
    def test_timeout_returns_failed(self, mock_client_cls, mock_time):
        # start_time=0, then elapsed_time=11 > _INTERNAL_STATUS_TIMEOUT=10
        mock_time.time.side_effect = [0, 11]
        mock_time.sleep = MagicMock()
        mock_client_cls.return_value.get.side_effect = ConnectError("connection refused")

        result = _get_internal_deployment_status("dep-name", "analysis_id")

        assert result == AnalysisStatus.FAILED.value


# ─── TestRefreshKeycloakToken ─────────────────────────────────────────────────

class TestRefreshKeycloakToken:
    @patch("src.status.status.get_keycloak_token")
    @patch("src.status.status.Client")
    def test_no_refresh_when_token_valid(self, mock_client_cls, mock_get_token, monkeypatch):
        monkeypatch.setenv("STATUS_LOOP_INTERVAL", "30")
        # threshold = 30*2+1 = 61; 9999 >= 61 → no refresh
        _refresh_keycloak_token("dep-name", "analysis_id", 9999)
        mock_get_token.assert_not_called()
        mock_client_cls.assert_not_called()

    @patch("src.status.status.get_keycloak_token", return_value="new-token")
    @patch("src.status.status.Client")
    def test_refresh_when_token_expiring(self, mock_client_cls, mock_get_token, monkeypatch):
        monkeypatch.setenv("STATUS_LOOP_INTERVAL", "30")
        # threshold = 30*2+1 = 61; 10 < 61 → refresh
        mock_client_cls.return_value.post.return_value = MagicMock()

        _refresh_keycloak_token("dep-name", "analysis_id", 10)

        mock_get_token.assert_called_once_with("analysis_id")
        mock_client_cls.return_value.post.assert_called_once()


# ─── TestInformAnalysisOfPartnerStatuses ─────────────────────────────────────

class TestInformAnalysisOfPartnerStatuses:
    @patch("src.status.status.get_partner_node_statuses")
    @patch("src.status.status.Client")
    def test_success_returns_response_json(
        self, mock_client_cls, mock_get_partners, mock_database, mock_hub_client, sample_analysis_db
    ):
        mock_database.get_latest_deployment.return_value = sample_analysis_db(deployment_name="analysis-id-0")
        mock_get_partners.return_value = {"node-1": "running"}
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True}
        mock_client_cls.return_value.post.return_value = mock_response

        result = inform_analysis_of_partner_statuses(
            mock_database, mock_hub_client, "analysis_id", "node-analysis-id"
        )

        assert result == {"ok": True}

    @patch("src.status.status.get_partner_node_statuses")
    @patch("src.status.status.Client")
    def test_connect_error_returns_none(
        self, mock_client_cls, mock_get_partners, mock_database, mock_hub_client, sample_analysis_db
    ):
        mock_database.get_latest_deployment.return_value = sample_analysis_db(deployment_name="analysis-id-0")
        mock_get_partners.return_value = {}
        mock_client_cls.return_value.post.side_effect = ConnectError("refused")

        result = inform_analysis_of_partner_statuses(
            mock_database, mock_hub_client, "analysis_id", "node-analysis-id"
        )

        assert result is None

    @patch("src.status.status.get_partner_node_statuses")
    @patch("src.status.status.Client")
    def test_connect_timeout_returns_none(
        self, mock_client_cls, mock_get_partners, mock_database, mock_hub_client, sample_analysis_db
    ):
        mock_database.get_latest_deployment.return_value = sample_analysis_db(deployment_name="analysis-id-0")
        mock_get_partners.return_value = {}
        mock_client_cls.return_value.post.side_effect = ConnectTimeout("timed out")

        result = inform_analysis_of_partner_statuses(
            mock_database, mock_hub_client, "analysis_id", "node-analysis-id"
        )

        assert result is None


# ─── TestFixStuckStatus ───────────────────────────────────────────────────────

class TestFixStuckStatus:
    @patch("src.status.status.unstuck_analysis_deployments")
    @patch("src.status.status._stream_stuck_logs")
    def test_restartable_calls_unstuck(
        self, mock_stream, mock_unstuck, mock_database, mock_hub_client, sample_analysis_db
    ):
        analysis = sample_analysis_db(restart_counter=0)
        mock_database.get_latest_deployment.return_value = analysis
        analysis_status = {
            "analysis_id": "analysis_id",
            "db_status": AnalysisStatus.EXECUTING.value,
            "int_status": AnalysisStatus.STUCK.value,
            "status_action": "unstuck",
        }

        _fix_stuck_status(mock_database, analysis_status, "node-id", False, mock_hub_client)

        mock_database.update_deployment_status.assert_not_called()
        mock_unstuck.assert_called_once_with("analysis_id", mock_database)
        mock_stream.assert_called_once()

    @patch("src.status.status.unstuck_analysis_deployments")
    @patch("src.status.status._stream_stuck_logs")
    def test_max_restarts_skips_unstuck(
        self, mock_stream, mock_unstuck, mock_database, mock_hub_client, sample_analysis_db
    ):
        analysis = sample_analysis_db(restart_counter=_MAX_RESTARTS)
        mock_database.get_latest_deployment.return_value = analysis
        analysis_status = {
            "analysis_id": "analysis_id",
            "db_status": AnalysisStatus.EXECUTING.value,
            "int_status": AnalysisStatus.STUCK.value,
            "status_action": "unstuck",
        }

        _fix_stuck_status(mock_database, analysis_status, "node-id", False, mock_hub_client)

        mock_unstuck.assert_not_called()
        mock_stream.assert_called_once()


# ─── TestUpdateRunningStatus ──────────────────────────────────────────────────

class TestUpdateRunningStatus:
    def test_updates_deployment_to_executing(self, mock_database, sample_analysis_db):
        analysis = sample_analysis_db(deployment_name="dep-name", status=AnalysisStatus.STARTED.value)
        mock_database.get_latest_deployment.return_value = analysis

        _update_running_status(
            mock_database,
            {"analysis_id": "analysis_id", "db_status": AnalysisStatus.STARTED.value, "int_status": AnalysisStatus.EXECUTING.value},
        )

        mock_database.update_deployment_status.assert_called_once_with("dep-name", AnalysisStatus.EXECUTING.value)

    def test_no_update_when_deployment_not_found(self, mock_database):
        mock_database.get_latest_deployment.return_value = None
        _update_running_status(mock_database, {"analysis_id": "analysis_id"})
        mock_database.update_deployment_status.assert_not_called()


# ─── TestUpdateFinishedStatus ─────────────────────────────────────────────────

class TestUpdateFinishedStatus:
    @patch("src.status.status.delete_analysis")
    def test_executed_deletes_analysis(self, mock_delete, mock_database, sample_analysis_db):
        analysis = sample_analysis_db(deployment_name="dep-name")
        mock_database.get_latest_deployment.return_value = analysis

        _update_finished_status(
            mock_database,
            {"analysis_id": "analysis_id", "db_status": AnalysisStatus.EXECUTING.value, "int_status": AnalysisStatus.EXECUTED.value},
        )

        mock_database.update_deployment_status.assert_called_once_with("dep-name", AnalysisStatus.EXECUTED.value)
        mock_delete.assert_called_once_with("analysis_id", mock_database)

    @patch("src.status.status.stop_analysis")
    def test_failed_stops_analysis(self, mock_stop, mock_database, sample_analysis_db):
        analysis = sample_analysis_db(deployment_name="dep-name")
        mock_database.get_latest_deployment.return_value = analysis

        _update_finished_status(
            mock_database,
            {"analysis_id": "analysis_id", "db_status": AnalysisStatus.EXECUTING.value, "int_status": AnalysisStatus.FAILED.value},
        )

        mock_database.update_deployment_status.assert_called_once_with("dep-name", AnalysisStatus.FAILED.value)
        mock_stop.assert_called_once_with("analysis_id", mock_database)


# ─── TestSetAnalysisHubStatus ─────────────────────────────────────────────────

class TestSetAnalysisHubStatus:
    """Priority: db_status (if failed/executed) > int_status (if failed/executed/executing) > db_status (default)."""

    @patch("src.status.status.update_hub_status")
    def test_db_failed_takes_priority(self, mock_update, mock_hub_client):
        result = _set_analysis_hub_status(
            mock_hub_client,
            "node-analysis-id",
            {"db_status": AnalysisStatus.FAILED.value, "int_status": AnalysisStatus.EXECUTING.value},
        )
        assert result == AnalysisStatus.FAILED.value
        mock_update.assert_called_once_with(mock_hub_client, "node-analysis-id", AnalysisStatus.FAILED.value)

    @patch("src.status.status.update_hub_status")
    def test_db_executed_takes_priority(self, mock_update, mock_hub_client):
        result = _set_analysis_hub_status(
            mock_hub_client,
            "node-analysis-id",
            {"db_status": AnalysisStatus.EXECUTED.value, "int_status": AnalysisStatus.EXECUTING.value},
        )
        assert result == AnalysisStatus.EXECUTED.value

    @patch("src.status.status.update_hub_status")
    def test_int_executing_used_when_db_not_terminal(self, mock_update, mock_hub_client):
        result = _set_analysis_hub_status(
            mock_hub_client,
            "node-analysis-id",
            {"db_status": AnalysisStatus.STARTED.value, "int_status": AnalysisStatus.EXECUTING.value},
        )
        assert result == AnalysisStatus.EXECUTING.value

    @patch("src.status.status.update_hub_status")
    def test_int_failed_used_when_db_not_terminal(self, mock_update, mock_hub_client):
        result = _set_analysis_hub_status(
            mock_hub_client,
            "node-analysis-id",
            {"db_status": AnalysisStatus.STARTED.value, "int_status": AnalysisStatus.FAILED.value},
        )
        assert result == AnalysisStatus.FAILED.value

    @patch("src.status.status.update_hub_status")
    def test_default_falls_back_to_db_status(self, mock_update, mock_hub_client):
        result = _set_analysis_hub_status(
            mock_hub_client,
            "node-analysis-id",
            {"db_status": AnalysisStatus.STARTED.value, "int_status": AnalysisStatus.STARTED.value},
        )
        assert result == AnalysisStatus.STARTED.value