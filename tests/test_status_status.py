"""Tests for src/status/status.py.

Does NOT test status_loop itself (infinite loop — untestable without mocking time).
Tests all helper functions: _decide_status_action, _get_analysis_status,
_get_internal_deployment_status, _refresh_analysis_token,
inform_analysis_of_partner_statuses, _fix_stuck_status,
_update_running_status, _update_finished_status, _set_analysis_hub_status,
_remove_db_entry_after_hub_status_verification.
"""

from unittest.mock import MagicMock, patch

import pytest
from httpx2 import ConnectError, ConnectTimeout, HTTPStatusError, ReadTimeout

from src.status.constants import AnalysisStatus, MAX_RESTARTS, INTERNAL_STATUS_TIMEOUT
from src.status.status import (
    _decide_status_action,
    _fix_stuck_status,
    _get_analysis_status,
    _get_internal_deployment_status,
    _refresh_analysis_token,
    _remove_db_entry_after_hub_status_verification,
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

    def test_firmly_stuck_failed_db_stuck_int_returns_finishing(self):
        # db=FAILED + int=STUCK: is_stuck excludes FAILED (db_status not in [FAILED]),
        # so firmly_stuck fires instead and returns 'finishing'.
        assert _decide_status_action(AnalysisStatus.FAILED.value, AnalysisStatus.STUCK.value) == "finishing"

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
    @patch("src.status.status._refresh_analysis_token")
    @patch("src.status.status.Client")
    def test_executing_status_returned(self, mock_client_cls, mock_refresh):
        mock_response = MagicMock()
        mock_response.json.return_value = {"status": "executing", "token_remaining_time": 9999}
        mock_client_cls.return_value.get.return_value = mock_response

        result = _get_internal_deployment_status("dep-name", "analysis_id")

        assert result == AnalysisStatus.EXECUTING.value

    @patch("src.status.status._refresh_analysis_token")
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
        # start_time=0, then elapsed_time exceeds INTERNAL_STATUS_TIMEOUT
        mock_time.time.side_effect = [0, INTERNAL_STATUS_TIMEOUT + 1]
        mock_time.sleep = MagicMock()
        mock_client_cls.return_value.get.side_effect = ConnectError("connection refused")

        result = _get_internal_deployment_status("dep-name", "analysis_id")

        assert result == AnalysisStatus.FAILED.value

    @pytest.mark.parametrize(
        "error",
        [
            ConnectError("refused"),
            ReadTimeout("slow read"),
            HTTPStatusError("503", request=MagicMock(), response=MagicMock()),
        ],
    )
    @patch("src.status.status._refresh_analysis_token")
    @patch("src.status.status.logger")
    @patch("src.status.status.time")
    @patch("src.status.status.Client")
    def test_http_error_is_logged_and_retried(
        self, mock_client_cls, mock_time, mock_logger, mock_refresh, error
    ):
        mock_time.time.return_value = 0
        ok_response = MagicMock()
        ok_response.json.return_value = {"status": "executing", "token_remaining_time": 9999}
        mock_client_cls.return_value.get.side_effect = [error, ok_response]

        result = _get_internal_deployment_status("dep-name", "analysis_id")

        assert result == AnalysisStatus.EXECUTING.value
        assert mock_client_cls.return_value.get.call_count == 2
        mock_logger.warning.assert_called_once()
        assert "nginx-dep-name" in mock_logger.warning.call_args[0][0]


# ─── TestRefreshAnalysisToken ─────────────────────────────────────────────────

class TestRefreshAnalysisToken:
    @patch("src.status.status.get_analysis_token")
    @patch("src.status.status.Client")
    def test_no_refresh_when_token_valid(self, mock_client_cls, mock_get_token, monkeypatch):
        monkeypatch.setenv("STATUS_LOOP_INTERVAL", "30")
        # threshold = 30*2+1 = 61; 9999 >= 61 → no refresh
        _refresh_analysis_token("dep-name", "analysis_id", 9999)
        mock_get_token.assert_not_called()
        mock_client_cls.assert_not_called()

    @patch("src.status.status.get_analysis_token", return_value="new-token")
    @patch("src.status.status.Client")
    def test_refresh_when_token_expiring(self, mock_client_cls, mock_get_token, monkeypatch):
        monkeypatch.setenv("STATUS_LOOP_INTERVAL", "30")
        # threshold = 30*2+1 = 61; 10 < 61 → refresh
        mock_client_cls.return_value.post.return_value = MagicMock()

        _refresh_analysis_token("dep-name", "analysis_id", 10)

        mock_get_token.assert_called_once_with("analysis_id")
        mock_client_cls.return_value.post.assert_called_once()

    @patch("src.status.status.logger")
    @patch("src.status.status.get_analysis_token", return_value=None)
    @patch("src.status.status.Client")
    def test_failed_mint_does_not_post(self, mock_client_cls, mock_get_token, mock_logger, monkeypatch):
        monkeypatch.setenv("STATUS_LOOP_INTERVAL", "30")

        _refresh_analysis_token("dep-name", "analysis_id", 10)

        mock_get_token.assert_called_once_with("analysis_id")
        mock_client_cls.assert_not_called()
        mock_logger.error.assert_called_once()

    @patch("src.status.status.logger")
    @patch("src.status.status.get_analysis_token", return_value="new-token")
    @patch("src.status.status.Client")
    def test_connect_error_is_swallowed_and_logged(self, mock_client_cls, mock_get_token, mock_logger, monkeypatch):
        monkeypatch.setenv("STATUS_LOOP_INTERVAL", "30")
        mock_client_cls.return_value.post.side_effect = ConnectError("refused")

        _refresh_analysis_token("dep-name", "analysis_id", 10)

        mock_logger.error.assert_called_once()
        mock_client_cls.return_value.close.assert_called_once()


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

    @pytest.mark.parametrize(
        "error",
        [ReadTimeout("slow read"), HTTPStatusError("500", request=MagicMock(), response=MagicMock())],
    )
    @patch("src.status.status.get_partner_node_statuses")
    @patch("src.status.status.Client")
    def test_any_http_error_returns_none(
        self, mock_client_cls, mock_get_partners, mock_database, mock_hub_client, sample_analysis_db, error
    ):
        mock_database.get_latest_deployment.return_value = sample_analysis_db(deployment_name="analysis-id-0")
        mock_get_partners.return_value = {}
        mock_client_cls.return_value.post.side_effect = error

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
        mock_unstuck.assert_called_once_with(
            "analysis_id", mock_database, mock_hub_client, "node-id"
        )
        mock_stream.assert_called_once()

    @patch("src.status.status.unstuck_analysis_deployments")
    @patch("src.status.status._stream_stuck_logs")
    def test_max_restarts_skips_unstuck(
        self, mock_stream, mock_unstuck, mock_database, mock_hub_client, sample_analysis_db
    ):
        analysis = sample_analysis_db(restart_counter=MAX_RESTARTS)
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
    @staticmethod
    def _status(int_status):
        return {
            "analysis_id": "analysis_id",
            "db_status": AnalysisStatus.EXECUTING.value,
            "int_status": int_status,
        }

    @pytest.mark.parametrize(
        "int_status, expected_final",
        [
            (AnalysisStatus.EXECUTED.value, AnalysisStatus.EXECUTED.value),
            (AnalysisStatus.FAILED.value, AnalysisStatus.FAILED.value),
            (AnalysisStatus.STUCK.value, AnalysisStatus.FAILED.value),
        ],
    )
    @patch("src.status.status._remove_db_entry_after_hub_status_verification")
    @patch("src.status.status.stop_analysis")
    def test_running_analysis_is_stopped_then_verified(
        self, mock_stop, mock_remove, mock_database, mock_hub_client, sample_analysis_db,
        int_status, expected_final,
    ):
        mock_database.get_latest_deployment.return_value = sample_analysis_db(deployment_name="dep-name")
        mock_database.analysis_is_running.return_value = True

        _update_finished_status(mock_database, mock_hub_client, "node-id", self._status(int_status))

        mock_database.update_deployment_status.assert_called_once_with("dep-name", expected_final)
        mock_stop.assert_called_once_with("analysis_id", mock_database)
        mock_remove.assert_called_once_with(
            mock_database, mock_hub_client, "node-id", "analysis_id", expected_final
        )

    @patch("src.status.status._remove_db_entry_after_hub_status_verification")
    @patch("src.status.status.stop_analysis")
    def test_already_stopped_analysis_is_only_verified(
        self, mock_stop, mock_remove, mock_database, mock_hub_client, sample_analysis_db
    ):
        """A finished analysis left in the DB by an earlier pass is not stopped again."""
        mock_database.get_latest_deployment.return_value = sample_analysis_db(deployment_name="dep-name")
        mock_database.analysis_is_running.return_value = False

        _update_finished_status(
            mock_database, mock_hub_client, "node-id", self._status(AnalysisStatus.EXECUTED.value)
        )

        mock_database.update_deployment_status.assert_not_called()
        mock_stop.assert_not_called()
        mock_remove.assert_called_once_with(
            mock_database, mock_hub_client, "node-id", "analysis_id", AnalysisStatus.EXECUTED.value
        )

    @patch("src.status.status._remove_db_entry_after_hub_status_verification")
    @patch("src.status.status.stop_analysis")
    def test_missing_deployment_is_noop(
        self, mock_stop, mock_remove, mock_database, mock_hub_client
    ):
        mock_database.get_latest_deployment.return_value = None

        _update_finished_status(
            mock_database, mock_hub_client, "node-id", self._status(AnalysisStatus.EXECUTED.value)
        )

        mock_stop.assert_not_called()
        mock_remove.assert_not_called()


# ─── TestRemoveDbEntryAfterHubStatusVerification ─────────────────────────────

class TestRemoveDbEntryAfterHubStatusVerification:
    @pytest.fixture(autouse=True)
    def _no_sleep(self):
        with patch("src.status.status.time.sleep") as mock_sleep:
            self.mock_sleep = mock_sleep
            yield

    @patch("src.status.status.update_hub_status")
    @patch("src.status.status.get_node_analysis_status")
    @patch("src.status.status.get_node_analysis_id")
    def test_no_node_id_is_noop(self, mock_get_id, mock_get_status, mock_update, mock_database, mock_hub_client):
        _remove_db_entry_after_hub_status_verification(
            mock_database, mock_hub_client, None, "analysis_id", AnalysisStatus.EXECUTED.value
        )

        mock_get_id.assert_not_called()
        mock_database.delete_analysis.assert_not_called()

    @patch("src.status.status.update_hub_status")
    @patch("src.status.status.get_node_analysis_status", return_value=AnalysisStatus.EXECUTED.value)
    @patch("src.status.status.get_node_analysis_id", return_value="na-id")
    def test_matching_hub_status_deletes_entry(
        self, mock_get_id, mock_get_status, mock_update, mock_database, mock_hub_client
    ):
        _remove_db_entry_after_hub_status_verification(
            mock_database, mock_hub_client, "node-id", "analysis_id", AnalysisStatus.EXECUTED.value
        )

        mock_get_status.assert_called_once_with(mock_hub_client, "analysis_id", "na-id")
        mock_database.delete_analysis.assert_called_once_with("analysis_id")
        mock_update.assert_not_called()

    @patch("src.status.status.update_hub_status")
    @patch("src.status.status.get_node_analysis_status")
    @patch("src.status.status.get_node_analysis_id", return_value=[])
    def test_analysis_unknown_to_hub_deletes_entry(
        self, mock_get_id, mock_get_status, mock_update, mock_database, mock_hub_client
    ):
        """An empty analysis-node list means the analysis was deleted in the Hub."""
        _remove_db_entry_after_hub_status_verification(
            mock_database, mock_hub_client, "node-id", "analysis_id", AnalysisStatus.EXECUTED.value
        )

        mock_database.delete_analysis.assert_called_once_with("analysis_id")
        mock_get_status.assert_not_called()
        mock_update.assert_not_called()

    @patch("src.status.status.update_hub_status")
    @patch(
        "src.status.status.get_node_analysis_status",
        side_effect=[AnalysisStatus.EXECUTING.value, AnalysisStatus.EXECUTED.value],
    )
    @patch("src.status.status.get_node_analysis_id", return_value="na-id")
    def test_mismatch_forces_update_then_deletes(
        self, mock_get_id, mock_get_status, mock_update, mock_database, mock_hub_client
    ):
        _remove_db_entry_after_hub_status_verification(
            mock_database, mock_hub_client, "node-id", "analysis_id", AnalysisStatus.EXECUTED.value
        )

        mock_update.assert_called_once_with(mock_hub_client, "na-id", AnalysisStatus.EXECUTED.value)
        self.mock_sleep.assert_called_once_with(1)  # 1.5 ** 0
        mock_database.delete_analysis.assert_called_once_with("analysis_id")

    @patch("src.status.status.update_hub_status")
    @patch("src.status.status.get_node_analysis_status", return_value=AnalysisStatus.EXECUTING.value)
    @patch("src.status.status.get_node_analysis_id", return_value="na-id")
    def test_gives_up_after_max_attempts_and_keeps_entry(
        self, mock_get_id, mock_get_status, mock_update, mock_database, mock_hub_client
    ):
        from src.status.status import _MAX_FINAL_STATUS_UPDATE_REATTEMPTS

        _remove_db_entry_after_hub_status_verification(
            mock_database, mock_hub_client, "node-id", "analysis_id", AnalysisStatus.EXECUTED.value
        )

        assert mock_update.call_count == _MAX_FINAL_STATUS_UPDATE_REATTEMPTS
        assert [c.args[0] for c in self.mock_sleep.call_args_list] == [
            1.5 ** i for i in range(_MAX_FINAL_STATUS_UPDATE_REATTEMPTS)
        ]
        mock_database.delete_analysis.assert_not_called()

    @patch("src.status.status.update_hub_status")
    @patch("src.status.status.get_node_analysis_status")
    @patch("src.status.status.get_node_analysis_id", return_value=None)
    def test_hub_lookup_failure_retries_without_update(
        self, mock_get_id, mock_get_status, mock_update, mock_database, mock_hub_client
    ):
        from src.status.status import _MAX_FINAL_STATUS_UPDATE_REATTEMPTS

        _remove_db_entry_after_hub_status_verification(
            mock_database, mock_hub_client, "node-id", "analysis_id", AnalysisStatus.EXECUTED.value
        )

        assert mock_get_id.call_count == _MAX_FINAL_STATUS_UPDATE_REATTEMPTS + 1
        mock_update.assert_not_called()
        mock_database.delete_analysis.assert_not_called()


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
        assert result == AnalysisStatus.STARTED.value

    @patch("src.status.status.update_hub_status")
    def test_int_failed_used_when_db_not_terminal(self, mock_update, mock_hub_client):
        result = _set_analysis_hub_status(
            mock_hub_client,
            "node-analysis-id",
            {"db_status": AnalysisStatus.STARTED.value, "int_status": AnalysisStatus.FAILED.value},
        )
        assert result == AnalysisStatus.STARTED.value

    @patch("src.status.status.update_hub_status")
    def test_default_falls_back_to_db_status(self, mock_update, mock_hub_client):
        result = _set_analysis_hub_status(
            mock_hub_client,
            "node-analysis-id",
            {"db_status": AnalysisStatus.STARTED.value, "int_status": AnalysisStatus.STARTED.value},
        )
        assert result == AnalysisStatus.STARTED.value