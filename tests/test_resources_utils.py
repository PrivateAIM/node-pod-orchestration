"""
Tests for src/resources/utils.py — business logic layer.

All external dependencies are mocked:
  - get_current_namespace / create_harbor_secret
  - Analysis class / read_db_analysis
  - get_analysis_logs
  - init_hub_client_and_update_hub_status_with_client
  - find_k8s_resources / delete_k8s_resource
  - _get_all_keycloak_clients / delete_keycloak_client
  - update_hub_status / get_node_analysis_id
  - time.sleep / resource_name_to_analysis
"""

from unittest.mock import MagicMock, patch, call

import pytest

from src.resources.analysis.entity import CreateAnalysis
from src.resources.log.entity import CreateLogEntity
from src.status.constants import AnalysisStatus

# Sample log string: a valid Python literal representing the log dict stored in the DB.
# retrieve_history calls ast.literal_eval() on this, then reads ['analysis'][id] and ['nginx'][id].
_ANALYSIS_ID = "analysis_id"
_SAMPLE_LOG = str({
    "analysis": {_ANALYSIS_ID: ["analysis log line"]},
    "nginx": {_ANALYSIS_ID: ["nginx log line"]},
})


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _analysis_mock(
    analysis_id=_ANALYSIS_ID,
    status="started",
    deployment_name="analysis-analysis_id-0",
    namespace="default",
    log=None,
    pod_ids=None,
    progress=0,
):
    """Create a mock Analysis object with configurable attributes."""
    m = MagicMock()
    m.analysis_id = analysis_id
    m.status = status
    m.deployment_name = deployment_name
    m.namespace = namespace
    m.log = log
    m.pod_ids = pod_ids if pod_ids is not None else ["pod-1"]
    m.progress = progress
    return m


# ─── create_analysis ──────────────────────────────────────────────────────────

class TestCreateAnalysis:
    _VALID_UUID = "123e4567-e89b-42d3-a456-426614174000"

    def _valid_body_kwargs(self):
        return {
            "analysis_id": self._VALID_UUID,
            "project_id": self._VALID_UUID,
            "registry_url": "harbor.privateaim",
            "image_url": "harbor.privateaim/node_id/analysis_id",
            "registry_user": "robot_user",
            "registry_password": "default_pw",
            "kong_token": "default_kong_token",
        }

    @patch("src.resources.utils.init_hub_client_and_update_hub_status_with_client")
    @patch("src.resources.utils.Analysis")
    @patch("src.resources.utils.create_harbor_secret")
    @patch("src.resources.utils.get_current_namespace", return_value="default")
    def test_from_create_analysis_body(
        self, mock_ns, mock_harbor, mock_analysis_cls, mock_hub, mock_database
    ):
        from src.resources.utils import create_analysis

        mock_inst = _analysis_mock(
            analysis_id=self._VALID_UUID, status=AnalysisStatus.STARTED.value
        )
        mock_analysis_cls.return_value = mock_inst

        body = CreateAnalysis(**self._valid_body_kwargs())
        result = create_analysis(body, mock_database)

        mock_harbor.assert_called_once()
        mock_inst.start.assert_called_once_with(database=mock_database, namespace="default")
        mock_hub.assert_called_once_with(self._VALID_UUID, AnalysisStatus.STARTED.value)
        assert result == {self._VALID_UUID: AnalysisStatus.STARTED.value}

    @patch("src.resources.utils.init_hub_client_and_update_hub_status_with_client")
    @patch("src.resources.utils.Analysis")
    @patch("src.resources.utils.create_harbor_secret")
    @patch("src.resources.utils.get_current_namespace", return_value="default")
    def test_from_string_extracts_body_and_restarts(
        self, mock_ns, mock_harbor, mock_analysis_cls, mock_hub, mock_database
    ):
        """When body is a string, extract_analysis_body is called and the analysis is restarted."""
        from src.resources.utils import create_analysis

        mock_inst = _analysis_mock(
            analysis_id=self._VALID_UUID, status=AnalysisStatus.STARTED.value
        )
        mock_analysis_cls.return_value = mock_inst
        mock_database.extract_analysis_body.return_value = self._valid_body_kwargs()

        result = create_analysis(self._VALID_UUID, mock_database)

        mock_database.extract_analysis_body.assert_called_once_with(self._VALID_UUID)
        mock_harbor.assert_called_once()
        mock_hub.assert_called_once()
        assert self._VALID_UUID in result

    def test_from_string_not_found_returns_status_message(self, mock_database):
        """When extract_analysis_body returns None, return a status error dict."""
        from src.resources.utils import create_analysis

        mock_database.extract_analysis_body.return_value = None

        with patch("src.resources.utils.get_current_namespace", return_value="default"):
            result = create_analysis("nonexistent_id", mock_database)

        assert result == {"status": "Analysis ID not found in database."}


# ─── retrieve_history ─────────────────────────────────────────────────────────

class TestRetrieveHistory:
    def test_single_stopped_analysis(self, mock_database, sample_analysis_db):
        from src.resources.utils import retrieve_history

        db_row = sample_analysis_db(status=AnalysisStatus.STOPPED.value, log=_SAMPLE_LOG)
        mock_database.get_latest_deployment.return_value = db_row

        result = retrieve_history(_ANALYSIS_ID, mock_database)

        assert result["analysis"][_ANALYSIS_ID] == ["analysis log line"]
        assert result["nginx"][_ANALYSIS_ID] == ["nginx log line"]

    def test_single_executed_analysis(self, mock_database, sample_analysis_db):
        from src.resources.utils import retrieve_history

        db_row = sample_analysis_db(status=AnalysisStatus.EXECUTED.value, log=_SAMPLE_LOG)
        mock_database.get_latest_deployment.return_value = db_row

        result = retrieve_history(_ANALYSIS_ID, mock_database)

        assert _ANALYSIS_ID in result["analysis"]

    def test_running_analysis_excluded(self, mock_database, sample_analysis_db):
        """A running (started) analysis is not included in history."""
        from src.resources.utils import retrieve_history

        db_row = sample_analysis_db(status=AnalysisStatus.STARTED.value)
        mock_database.get_latest_deployment.return_value = db_row

        result = retrieve_history(_ANALYSIS_ID, mock_database)

        assert result == {"analysis": {}, "nginx": {}}

    def test_all_analyses_queries_all_ids(self, mock_database, sample_analysis_db):
        from src.resources.utils import retrieve_history

        db_row = sample_analysis_db(status=AnalysisStatus.STOPPED.value, log=_SAMPLE_LOG)
        mock_database.get_analysis_ids.return_value = [_ANALYSIS_ID]
        mock_database.get_latest_deployment.return_value = db_row

        result = retrieve_history("all", mock_database)

        mock_database.get_analysis_ids.assert_called_once()
        assert _ANALYSIS_ID in result["analysis"]

    def test_not_found_excluded(self, mock_database):
        from src.resources.utils import retrieve_history

        mock_database.get_latest_deployment.return_value = None

        result = retrieve_history(_ANALYSIS_ID, mock_database)

        assert result == {"analysis": {}, "nginx": {}}


# ─── retrieve_logs ────────────────────────────────────────────────────────────

class TestRetrieveLogs:
    @patch("src.resources.utils.get_analysis_logs", return_value={"analysis": {}, "nginx": {}})
    def test_single_executing_deployment(self, mock_get_logs, mock_database, sample_analysis_db):
        from src.resources.utils import retrieve_logs

        db_row = sample_analysis_db(
            status=AnalysisStatus.EXECUTING.value,
            deployment_name="analysis-analysis_id-0",
        )
        mock_database.get_latest_deployment.return_value = db_row

        retrieve_logs(_ANALYSIS_ID, mock_database)

        mock_get_logs.assert_called_once_with(
            {_ANALYSIS_ID: "analysis-analysis_id-0"}, database=mock_database
        )

    @patch("src.resources.utils.get_analysis_logs", return_value={"analysis": {}, "nginx": {}})
    def test_non_executing_excluded(self, mock_get_logs, mock_database, sample_analysis_db):
        """Non-executing deployments are not passed to get_analysis_logs."""
        from src.resources.utils import retrieve_logs

        db_row = sample_analysis_db(status=AnalysisStatus.STARTED.value)
        mock_database.get_latest_deployment.return_value = db_row

        retrieve_logs(_ANALYSIS_ID, mock_database)

        mock_get_logs.assert_called_once_with({}, database=mock_database)

    @patch("src.resources.utils.get_analysis_logs", return_value={"analysis": {}, "nginx": {}})
    def test_all_analyses(self, mock_get_logs, mock_database, sample_analysis_db):
        from src.resources.utils import retrieve_logs

        db_row = sample_analysis_db(status=AnalysisStatus.EXECUTING.value)
        mock_database.get_analysis_ids.return_value = [_ANALYSIS_ID]
        mock_database.get_latest_deployment.return_value = db_row

        retrieve_logs("all", mock_database)

        mock_database.get_analysis_ids.assert_called_once()


# ─── get_status_and_progress ──────────────────────────────────────────────────

class TestGetStatusAndProgress:
    def test_single_analysis(self, mock_database, sample_analysis_db):
        from src.resources.utils import get_status_and_progress

        db_row = sample_analysis_db(status="executing", progress=50)
        mock_database.get_latest_deployment.return_value = db_row

        result = get_status_and_progress(_ANALYSIS_ID, mock_database)

        assert result[_ANALYSIS_ID]["status"] == "executing"
        assert result[_ANALYSIS_ID]["progress"] == 50

    def test_all_analyses(self, mock_database, sample_analysis_db):
        from src.resources.utils import get_status_and_progress

        db_row = sample_analysis_db(status="started")
        mock_database.get_analysis_ids.return_value = [_ANALYSIS_ID]
        mock_database.get_latest_deployment.return_value = db_row

        result = get_status_and_progress("all", mock_database)

        mock_database.get_analysis_ids.assert_called_once()
        assert _ANALYSIS_ID in result

    def test_not_found_excluded(self, mock_database):
        from src.resources.utils import get_status_and_progress

        mock_database.get_latest_deployment.return_value = None

        result = get_status_and_progress(_ANALYSIS_ID, mock_database)

        assert result == {}


# ─── get_pods ─────────────────────────────────────────────────────────────────

class TestGetPods:
    def test_single_analysis(self, mock_database):
        from src.resources.utils import get_pods

        mock_database.get_analysis_pod_ids.return_value = ["pod-1", "pod-2"]

        result = get_pods(_ANALYSIS_ID, mock_database)

        assert result == {_ANALYSIS_ID: ["pod-1", "pod-2"]}

    def test_all_analyses(self, mock_database):
        from src.resources.utils import get_pods

        mock_database.get_analysis_ids.return_value = [_ANALYSIS_ID]
        mock_database.get_analysis_pod_ids.return_value = ["pod-1"]

        result = get_pods("all", mock_database)

        mock_database.get_analysis_ids.assert_called_once()
        assert _ANALYSIS_ID in result


# ─── stop_analysis ────────────────────────────────────────────────────────────

class TestStopAnalysis:
    @patch("src.resources.utils.init_hub_client_and_update_hub_status_with_client")
    @patch("src.resources.utils.get_analysis_logs", return_value={"analysis": {}, "nginx": {}})
    @patch("src.resources.utils.read_db_analysis")
    def test_running_analysis_stopped(self, mock_read, mock_logs, mock_hub, mock_database):
        from src.resources.utils import stop_analysis

        mock_deployment = _analysis_mock(status=AnalysisStatus.STARTED.value)
        mock_read.return_value = mock_deployment

        stop_analysis(_ANALYSIS_ID, mock_database)

        # STARTED status is preserved to avoid signaling failure to partner nodes
        mock_deployment.stop.assert_called_once()
        assert mock_deployment.stop.call_args.kwargs["status"] == AnalysisStatus.STARTED.value
        mock_hub.assert_called_once_with(_ANALYSIS_ID, AnalysisStatus.STARTED.value)

    @patch("src.resources.utils.init_hub_client_and_update_hub_status_with_client")
    @patch("src.resources.utils.get_analysis_logs", return_value={"analysis": {}, "nginx": {}})
    @patch("src.resources.utils.read_db_analysis")
    def test_executed_analysis_keeps_executed_status(self, mock_read, mock_logs, mock_hub, mock_database):
        from src.resources.utils import stop_analysis

        mock_deployment = _analysis_mock(status=AnalysisStatus.EXECUTED.value)
        mock_read.return_value = mock_deployment

        stop_analysis(_ANALYSIS_ID, mock_database)

        call_kwargs = mock_deployment.stop.call_args.kwargs
        assert call_kwargs["status"] == AnalysisStatus.EXECUTED.value
        mock_hub.assert_called_once_with(_ANALYSIS_ID, AnalysisStatus.EXECUTED.value)

    @patch("src.resources.utils.init_hub_client_and_update_hub_status_with_client")
    @patch("src.resources.utils.get_analysis_logs", return_value={"analysis": {}, "nginx": {}})
    @patch("src.resources.utils.read_db_analysis")
    def test_failed_analysis_keeps_failed_status(self, mock_read, mock_logs, mock_hub, mock_database):
        from src.resources.utils import stop_analysis

        mock_deployment = _analysis_mock(status=AnalysisStatus.FAILED.value)
        mock_read.return_value = mock_deployment

        stop_analysis(_ANALYSIS_ID, mock_database)

        call_kwargs = mock_deployment.stop.call_args.kwargs
        assert call_kwargs["status"] == AnalysisStatus.FAILED.value
        mock_hub.assert_called_once_with(_ANALYSIS_ID, AnalysisStatus.FAILED.value)

    @patch("src.resources.utils.init_hub_client_and_update_hub_status_with_client")
    @patch("src.resources.utils.get_analysis_logs", return_value={"analysis": {}, "nginx": {}})
    @patch("src.resources.utils.read_db_analysis")
    def test_all_analyses(self, mock_read, mock_logs, mock_hub, mock_database):
        from src.resources.utils import stop_analysis

        mock_deployment = _analysis_mock(status=AnalysisStatus.STARTED.value)
        mock_read.return_value = mock_deployment
        mock_database.get_analysis_ids.return_value = [_ANALYSIS_ID]

        result = stop_analysis("all", mock_database)

        mock_database.get_analysis_ids.assert_called_once()
        assert _ANALYSIS_ID in result

    def test_not_found_returns_empty(self, mock_database):
        from src.resources.utils import stop_analysis

        mock_database.get_latest_deployment.return_value = None

        result = stop_analysis(_ANALYSIS_ID, mock_database)

        assert result == {}


# ─── delete_analysis ──────────────────────────────────────────────────────────

class TestDeleteAnalysis:
    @patch("src.resources.utils.delete_keycloak_client")
    @patch("src.resources.utils.read_db_analysis")
    def test_stopped_analysis_also_stopped(self, mock_read, mock_keycloak, mock_database):
        """New behavior: delete_analysis unconditionally calls stop() on the deployment."""
        from src.resources.utils import delete_analysis

        mock_deployment = _analysis_mock(status=AnalysisStatus.STOPPED.value)
        mock_read.return_value = mock_deployment

        delete_analysis(_ANALYSIS_ID, mock_database)

        mock_deployment.stop.assert_called_once_with(mock_database, log="")
        mock_keycloak.assert_called_once_with(_ANALYSIS_ID)
        mock_database.delete_analysis.assert_called_once_with(_ANALYSIS_ID)

    @patch("src.resources.utils.delete_keycloak_client")
    @patch("src.resources.utils.read_db_analysis")
    def test_running_analysis_stopped_then_deleted(self, mock_read, mock_keycloak, mock_database):
        from src.resources.utils import delete_analysis

        mock_deployment = _analysis_mock(status=AnalysisStatus.STARTED.value)
        mock_read.return_value = mock_deployment

        delete_analysis(_ANALYSIS_ID, mock_database)

        mock_deployment.stop.assert_called_once_with(mock_database, log="")
        mock_keycloak.assert_called_once_with(_ANALYSIS_ID)
        mock_database.delete_analysis.assert_called_once_with(_ANALYSIS_ID)

    def test_not_found_returns_empty(self, mock_database):
        from src.resources.utils import delete_analysis

        mock_database.get_latest_deployment.return_value = None

        result = delete_analysis(_ANALYSIS_ID, mock_database)

        assert result == {}

    @patch("src.resources.utils.delete_keycloak_client")
    @patch("src.resources.utils.read_db_analysis")
    def test_all_analyses(self, mock_read, mock_keycloak, mock_database):
        from src.resources.utils import delete_analysis

        mock_deployment = _analysis_mock(status=AnalysisStatus.STOPPED.value)
        mock_read.return_value = mock_deployment
        mock_database.get_analysis_ids.return_value = [_ANALYSIS_ID]

        delete_analysis("all", mock_database)

        mock_database.get_analysis_ids.assert_called_once()
        mock_database.delete_analysis.assert_called_once_with(_ANALYSIS_ID)


# ─── unstuck_analysis_deployments ─────────────────────────────────────────────

class TestUnstuckAnalysisDeployments:
    @patch("src.resources.utils.create_analysis")
    @patch("src.resources.utils.stop_analysis")
    @patch("src.resources.utils.time.sleep")
    def test_restartable_analysis(self, mock_sleep, mock_stop, mock_create, mock_database):
        from src.resources.utils import unstuck_analysis_deployments

        unstuck_analysis_deployments(_ANALYSIS_ID, mock_database)

        mock_stop.assert_called_once_with(_ANALYSIS_ID, mock_database)
        mock_sleep.assert_called_once_with(10)
        mock_create.assert_called_once_with(_ANALYSIS_ID, mock_database)
        mock_database.delete_old_deployments_from_db.assert_called_once_with(_ANALYSIS_ID)

    def test_not_found_does_nothing(self, mock_database):
        from src.resources.utils import unstuck_analysis_deployments

        mock_database.get_latest_deployment.return_value = None

        with patch("src.resources.utils.stop_analysis") as mock_stop:
            unstuck_analysis_deployments("nonexistent_id", mock_database)
            mock_stop.assert_not_called()


# ─── cleanup ──────────────────────────────────────────────────────────────────

class TestCleanup:
    @patch("src.resources.utils.clean_up_the_rest", return_value="")
    def test_analyzes_resets_db(self, mock_cztr, mock_database):
        from src.resources.utils import cleanup

        mock_database.get_analysis_ids.return_value = ["id1", "id2"]
        result = cleanup("analyzes", mock_database)

        mock_database.reset_db.assert_called_once()
        assert "analyzes" in result

    @patch("src.resources.utils.clean_up_the_rest", return_value="")
    @patch("src.resources.utils.delete_k8s_resource")
    @patch(
        "src.resources.utils.find_k8s_resources",
        return_value=["flame-message-broker-pod"],
    )
    def test_mb_reinitializes_message_broker(self, mock_find, mock_delete, mock_cztr, mock_database):
        from src.resources.utils import cleanup

        result = cleanup("mb", mock_database)

        mock_find.assert_called_once_with(
            "pod", "label", "component=flame-message-broker", namespace="default"
        )
        mock_delete.assert_called_once_with("flame-message-broker-pod", "pod", "default")
        assert result["mb"] == "Reset message broker"

    @patch("src.resources.utils.clean_up_the_rest", return_value="")
    @patch("src.resources.utils.delete_k8s_resource")
    @patch(
        "src.resources.utils.find_k8s_resources",
        return_value=["flame-storage-service-pod"],
    )
    def test_rs_reinitializes_storage_service(self, mock_find, mock_delete, mock_cztr, mock_database):
        from src.resources.utils import cleanup

        result = cleanup("rs", mock_database)

        mock_find.assert_called_once_with(
            "pod", "label", "component=flame-storage-service", namespace="default"
        )
        mock_delete.assert_called_once_with("flame-storage-service-pod", "pod", "default")
        assert result["rs"] == "Reset storage service"

    @patch("src.resources.utils.clean_up_the_rest", return_value="")
    @patch("src.resources.utils.delete_keycloak_client")
    @patch("src.resources.utils._get_all_keycloak_clients")
    def test_keycloak_deletes_orphaned_clients(self, mock_get_clients, mock_delete, mock_cztr, mock_database):
        from src.resources.utils import cleanup

        mock_database.get_analysis_ids.return_value = ["existing_analysis"]
        mock_get_clients.return_value = [
            {"clientId": "orphaned_analysis", "name": "flame-orphaned_analysis"},
            {"clientId": "existing_analysis", "name": "flame-existing_analysis"},
            {"clientId": "non_flame_client", "name": "other-client"},
        ]

        cleanup("keycloak", mock_database)

        # Only the orphaned flame client should be deleted; existing and non-flame skipped.
        mock_delete.assert_called_once_with("orphaned_analysis")

    @patch("src.resources.utils.clean_up_the_rest", return_value="")
    def test_unknown_type_returns_error_message(self, mock_cztr, mock_database):
        from src.resources.utils import cleanup

        result = cleanup("unknown_type", mock_database)

        assert "unknown_type" in result["unknown_type"]
        assert "Unknown cleanup type" in result["unknown_type"]

    @patch("src.resources.utils.clean_up_the_rest", return_value="")
    @patch("src.resources.utils.delete_k8s_resource")
    @patch("src.resources.utils.find_k8s_resources", return_value=["pod-name"])
    def test_comma_separated_processes_both_types(self, mock_find, mock_delete, mock_cztr, mock_database):
        from src.resources.utils import cleanup

        result = cleanup("mb,rs", mock_database)

        # mb calls find for message-broker, rs calls find for storage-service
        assert mock_find.call_count == 2

    @patch("src.resources.utils.clean_up_the_rest", return_value="zombie cleanup done")
    def test_always_calls_clean_up_the_rest(self, mock_cztr, mock_database):
        from src.resources.utils import cleanup

        result = cleanup("unknown_type", mock_database)

        mock_cztr.assert_called_once_with(mock_database, "default")
        assert result["zombies"] == "zombie cleanup done"


# ─── clean_up_the_rest ────────────────────────────────────────────────────────

class TestCleanUpTheRest:
    @patch("src.resources.utils.delete_k8s_resource")
    @patch("src.resources.utils.resource_name_to_analysis", return_value="zombie_id")
    @patch(
        "src.resources.utils.find_k8s_resources",
        return_value=["analysis-zombie_id-0"],
    )
    def test_deletes_zombie_resources(self, mock_find, mock_name_to_analysis, mock_delete, mock_database):
        from src.resources.utils import clean_up_the_rest

        mock_database.get_analysis_ids.return_value = ["known_id"]

        result = clean_up_the_rest(mock_database)

        # Zombie resources (not in known_analysis_ids) should be deleted.
        assert mock_delete.call_count > 0
        assert "Deleted" in result

    @patch("src.resources.utils.delete_k8s_resource")
    @patch("src.resources.utils.resource_name_to_analysis", return_value="known_id")
    @patch(
        "src.resources.utils.find_k8s_resources",
        return_value=["analysis-known_id-0"],
    )
    def test_skips_known_resources(self, mock_find, mock_name_to_analysis, mock_delete, mock_database):
        from src.resources.utils import clean_up_the_rest

        mock_database.get_analysis_ids.return_value = ["known_id"]

        clean_up_the_rest(mock_database)

        mock_delete.assert_not_called()

    @patch("src.resources.utils.delete_k8s_resource")
    @patch("src.resources.utils.find_k8s_resources", return_value=[None])
    def test_handles_none_resources(self, mock_find, mock_delete, mock_database):
        from src.resources.utils import clean_up_the_rest

        mock_database.get_analysis_ids.return_value = []

        result = clean_up_the_rest(mock_database)

        mock_delete.assert_not_called()
        assert isinstance(result, str)

    @patch("src.resources.utils.delete_k8s_resource")
    @patch("src.resources.utils.resource_name_to_analysis", return_value="zombie_id")
    @patch(
        "src.resources.utils.find_k8s_resources",
        return_value="analysis-zombie_id-0",  # str, not list
    )
    def test_wraps_string_result_in_list(self, mock_find, mock_name_to_analysis, mock_delete, mock_database):
        """find_k8s_resources returning a str (single result) is wrapped in a list."""
        from src.resources.utils import clean_up_the_rest

        mock_database.get_analysis_ids.return_value = ["known_id"]

        result = clean_up_the_rest(mock_database)

        # The string is treated as a single resource and identified as a zombie.
        assert mock_delete.call_count > 0


# ─── stream_logs ──────────────────────────────────────────────────────────────

class TestStreamLogs:
    def _make_log_entity(self, progress=50, status="executing"):
        return CreateLogEntity(
            analysis_id=_ANALYSIS_ID,
            log="test log message",
            log_type="info",
            status=status,
            progress=progress,
        )

    def test_always_updates_database_log(self, mock_database, mock_hub_client):
        from src.resources.utils import stream_logs

        log_entity = self._make_log_entity()
        mock_database.progress_valid.return_value = False

        with patch("src.resources.utils.get_node_analysis_id", return_value="node_analysis_id"):
            with patch("src.resources.utils.update_hub_status"):
                stream_logs(log_entity, "node-id", False, mock_database, mock_hub_client)

        mock_database.update_analysis_log.assert_called_once()
        args, _ = mock_database.update_analysis_log.call_args
        assert args[0] == _ANALYSIS_ID
        assert "test log message" in args[1]
        assert "log_type=info" in args[1]

    def test_hub_logging_disabled_skips_hub_log(self, mock_database, mock_hub_client):
        from src.resources.utils import stream_logs

        log_entity = self._make_log_entity()
        mock_database.progress_valid.return_value = False

        with patch("src.resources.utils.get_node_analysis_id", return_value="na"):
            with patch("src.resources.utils.update_hub_status"):
                stream_logs(log_entity, "node-id", False, mock_database, mock_hub_client)

        mock_hub_client.create_analysis_node_log.assert_not_called()

    def test_hub_logging_enabled_calls_hub(self, mock_database, mock_hub_client):
        from src.resources.utils import stream_logs

        log_entity = self._make_log_entity()
        mock_database.progress_valid.return_value = False

        with patch("src.resources.utils.get_node_analysis_id", return_value="na"):
            with patch("src.resources.utils.update_hub_status"):
                stream_logs(log_entity, "node-id", True, mock_database, mock_hub_client)

        mock_hub_client.create_analysis_node_log.assert_called_once_with(
            analysis_id=_ANALYSIS_ID,
            node_id="node-id",
            status="executing",
            level="info",
            message="test log message",
        )

    def test_valid_progress_updates_progress_and_hub(self, mock_database, mock_hub_client):
        from src.resources.utils import stream_logs

        log_entity = self._make_log_entity(progress=75)
        mock_database.progress_valid.return_value = True

        with patch("src.resources.utils.get_node_analysis_id", return_value="node_analysis_id"):
            with patch("src.resources.utils.update_hub_status") as mock_hub_update:
                stream_logs(log_entity, "node-id", False, mock_database, mock_hub_client)

        mock_database.update_analysis_progress.assert_called_once_with(_ANALYSIS_ID, 75)
        mock_hub_update.assert_called_once_with(
            mock_hub_client,
            "node_analysis_id",
            run_status="executing",
            run_progress=75,
        )

    def test_invalid_progress_skips_progress_update(self, mock_database, mock_hub_client):
        from src.resources.utils import stream_logs

        log_entity = self._make_log_entity(progress=50)
        mock_database.progress_valid.return_value = False

        with patch("src.resources.utils.get_node_analysis_id", return_value="node_analysis_id"):
            with patch("src.resources.utils.update_hub_status") as mock_hub_update:
                stream_logs(log_entity, "node-id", False, mock_database, mock_hub_client)

        mock_database.update_analysis_progress.assert_not_called()
        mock_hub_update.assert_called_once_with(
            mock_hub_client,
            "node_analysis_id",
            run_status="executing",
        )