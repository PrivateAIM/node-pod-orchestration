"""
Tests for src/k8s/kubernetes.py

Covers:
  - create_harbor_secret: success, first-call failure -> delete+retry, Conflict re-raises
  - create_analysis_deployment: full chain (deployment + service + nginx + network policy)
  - delete_deployment: all resources cleaned up, Not-Found exceptions handled silently
  - get_analysis_logs: structure, pod_id filtering, ApiException returns []
  - get_pod_status: ready/waiting/terminated/no pods
"""

import pytest
from unittest.mock import MagicMock, patch, call
from kubernetes.client.exceptions import ApiException

from src.k8s.kubernetes import (
    create_harbor_secret,
    create_analysis_deployment,
    delete_deployment,
    get_analysis_logs,
    get_pod_status,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_pod_item(name: str, pod_ip: str = "10.0.0.1") -> MagicMock:
    """Build a minimal mock K8s pod item with metadata.name and status.pod_ip."""
    pod = MagicMock()
    pod.metadata.name = name
    pod.status.pod_ip = pod_ip
    return pod


def _make_pod_list(*names: str, pod_ip: str = "10.0.0.1") -> MagicMock:
    """Build a mock K8s pod list response."""
    result = MagicMock()
    result.items = [_make_pod_item(n, pod_ip) for n in names]
    return result


def _not_found() -> ApiException:
    return ApiException(status=404, reason="Not Found")


# ─── create_harbor_secret ────────────────────────────────────────────────────

class TestCreateHarborSecret:
    def test_success_creates_secret(self, mock_k8s_clients):
        create_harbor_secret("harbor.test", "user", "password")

        mock_k8s_clients.core_v1.create_namespaced_secret.assert_called_once()
        mock_k8s_clients.core_v1.delete_namespaced_secret.assert_not_called()

    def test_first_call_fails_triggers_delete_and_retry(self, mock_k8s_clients):
        mock_k8s_clients.core_v1.create_namespaced_secret.side_effect = [
            ApiException(status=409, reason="AlreadyExists"),
            None,  # retry succeeds
        ]

        create_harbor_secret("harbor.test", "user", "password", name="my-secret")

        mock_k8s_clients.core_v1.delete_namespaced_secret.assert_called_once_with(
            name="my-secret", namespace="default"
        )
        assert mock_k8s_clients.core_v1.create_namespaced_secret.call_count == 2

    def test_conflict_on_retry_raises(self, mock_k8s_clients):
        conflict_exc = ApiException(status=409, reason="Conflict")
        mock_k8s_clients.core_v1.create_namespaced_secret.side_effect = [
            ApiException(status=409, reason="AlreadyExists"),
            conflict_exc,
        ]

        with pytest.raises(Exception, match="Conflict in harbor secret creation remains unresolved"):
            create_harbor_secret("harbor.test", "user", "password")

    def test_non_conflict_on_retry_raises(self, mock_k8s_clients):
        other_exc = ApiException(status=500, reason="InternalError")
        mock_k8s_clients.core_v1.create_namespaced_secret.side_effect = [
            ApiException(status=409, reason="AlreadyExists"),
            other_exc,
        ]

        with pytest.raises(Exception, match="Unknown error during harbor secret creation"):
            create_harbor_secret("harbor.test", "user", "password")

    def test_custom_name_and_namespace(self, mock_k8s_clients):
        create_harbor_secret("harbor.test", "user", "password", name="custom-secret", namespace="flame-ns")

        _, call_kwargs = mock_k8s_clients.core_v1.create_namespaced_secret.call_args
        assert call_kwargs["namespace"] == "flame-ns"


# ─── create_analysis_deployment ─────────────────────────────────────────────

class TestCreateAnalysisDeployment:
    """Tests for the full deployment chain.

    _create_nginx_config_map contains while-loops waiting for pod IPs and calls
    find_k8s_resources 7 times, so we patch both aggressively.
    """

    _ENV = {
        "PROJECT_ID": "project-123",
        "ANALYSIS_ID": "analysis-456",
    }

    @pytest.fixture(autouse=True)
    def _patch_sleep(self):
        with patch("src.k8s.kubernetes.time.sleep"):
            yield

    @pytest.fixture
    def _setup_pod_reads(self, mock_k8s_clients):
        """Return mocks configured so all while-loops exit on first iteration."""
        mb_pod = MagicMock()
        mb_pod.status.pod_ip = "10.0.0.1"
        po_pod = MagicMock()
        po_pod.status.pod_ip = "10.0.0.2"
        # read_namespaced_pod: first call = message-broker, second = po
        mock_k8s_clients.core_v1.read_namespaced_pod.side_effect = [mb_pod, po_pod]

        # list_namespaced_pod: used for analysis IP (config map) and _get_pods at end
        analysis_pod = _make_pod_item("analysis-my-dep-0-pod", pod_ip="10.0.0.3")
        pod_list = MagicMock()
        pod_list.items = [analysis_pod]
        mock_k8s_clients.core_v1.list_namespaced_pod.return_value = pod_list

        return mock_k8s_clients

    def _find_side_effects(self):
        return [
            "message-broker-svc",   # service/label/component=flame-message-broker
            "message-broker-pod",   # pod/label/component=flame-message-broker
            "po-svc",               # service/label/component=flame-po
            "po-pod",               # pod/label/component=flame-po
            "hub-adapter-svc",      # service/label/component=flame-hub-adapter
            "kong-proxy",           # service/label/app.kubernetes.io/name=kong
            "storage-svc",          # service/label/component=flame-storage-service
        ]

    def test_creates_analysis_deployment(self, mock_k8s_clients, _setup_pod_reads):
        with patch("src.k8s.kubernetes.find_k8s_resources", side_effect=self._find_side_effects()):
            create_analysis_deployment("my-dep", "harbor.test/image:latest", env=self._ENV)

        mock_k8s_clients.apps_v1.create_namespaced_deployment.assert_called()
        first_call_kwargs = mock_k8s_clients.apps_v1.create_namespaced_deployment.call_args_list[0][1]
        assert first_call_kwargs["namespace"] == "default"

    def test_creates_nginx_deployment(self, mock_k8s_clients, _setup_pod_reads):
        with patch("src.k8s.kubernetes.find_k8s_resources", side_effect=self._find_side_effects()):
            create_analysis_deployment("my-dep", "harbor.test/image:latest", env=self._ENV)

        deployment_names = [
            c[1]["body"].metadata.name
            for c in mock_k8s_clients.apps_v1.create_namespaced_deployment.call_args_list
        ]
        assert any("nginx" in name for name in deployment_names)

    def test_creates_services(self, mock_k8s_clients, _setup_pod_reads):
        with patch("src.k8s.kubernetes.find_k8s_resources", side_effect=self._find_side_effects()):
            create_analysis_deployment("my-dep", "harbor.test/image:latest", env=self._ENV)

        mock_k8s_clients.core_v1.create_namespaced_service.assert_called()

    def test_creates_config_map(self, mock_k8s_clients, _setup_pod_reads):
        with patch("src.k8s.kubernetes.find_k8s_resources", side_effect=self._find_side_effects()):
            create_analysis_deployment("my-dep", "harbor.test/image:latest", env=self._ENV)

        mock_k8s_clients.core_v1.create_namespaced_config_map.assert_called_once()

    def test_creates_network_policy(self, mock_k8s_clients, _setup_pod_reads):
        with patch("src.k8s.kubernetes.find_k8s_resources", side_effect=self._find_side_effects()):
            create_analysis_deployment("my-dep", "harbor.test/image:latest", env=self._ENV)

        mock_k8s_clients.networking_v1.create_namespaced_network_policy.assert_called_once()

    def test_returns_pod_names(self, mock_k8s_clients, _setup_pod_reads):
        with patch("src.k8s.kubernetes.find_k8s_resources", side_effect=self._find_side_effects()):
            result = create_analysis_deployment("my-dep", "harbor.test/image:latest", env=self._ENV)

        assert isinstance(result, list)
        assert result == ["analysis-my-dep-0-pod"]

    def test_custom_namespace_propagated(self, mock_k8s_clients, _setup_pod_reads):
        with patch("src.k8s.kubernetes.find_k8s_resources", side_effect=self._find_side_effects()):
            create_analysis_deployment(
                "my-dep", "harbor.test/image:latest", env=self._ENV, namespace="flame-ns"
            )

        all_namespaces = [
            c[1].get("namespace") or c[0][0] if c[0] else c[1].get("namespace")
            for c in mock_k8s_clients.apps_v1.create_namespaced_deployment.call_args_list
        ]
        for ns in all_namespaces:
            assert ns == "flame-ns"


# ─── delete_deployment ───────────────────────────────────────────────────────

class TestDeleteDeployment:
    def test_deletes_analysis_and_nginx_deployments(self, mock_k8s_clients):
        delete_deployment("analysis-123-0")

        calls = mock_k8s_clients.apps_v1.delete_namespaced_deployment.call_args_list
        names = [c[1]["name"] for c in calls]
        assert "analysis-123-0" in names
        assert "nginx-analysis-123-0" in names

    def test_deletes_analysis_and_nginx_services(self, mock_k8s_clients):
        delete_deployment("analysis-123-0")

        calls = mock_k8s_clients.core_v1.delete_namespaced_service.call_args_list
        names = [c[1]["name"] for c in calls]
        assert "analysis-123-0" in names
        assert "nginx-analysis-123-0" in names

    def test_deletes_network_policy(self, mock_k8s_clients):
        delete_deployment("analysis-123-0")

        mock_k8s_clients.networking_v1.delete_namespaced_network_policy.assert_called_once_with(
            name="nginx-to-analysis-123-0-policy", namespace="default"
        )

    def test_deletes_config_map(self, mock_k8s_clients):
        delete_deployment("analysis-123-0")

        mock_k8s_clients.core_v1.delete_namespaced_config_map.assert_called_once_with(
            name="nginx-analysis-123-0-config", namespace="default"
        )

    def test_not_found_deployment_exception_is_silenced(self, mock_k8s_clients):
        mock_k8s_clients.apps_v1.delete_namespaced_deployment.side_effect = _not_found()
        delete_deployment("analysis-123-0")  # must not raise

    def test_not_found_network_policy_exception_is_silenced(self, mock_k8s_clients):
        mock_k8s_clients.networking_v1.delete_namespaced_network_policy.side_effect = _not_found()
        delete_deployment("analysis-123-0")  # must not raise

    def test_not_found_config_map_exception_is_silenced(self, mock_k8s_clients):
        mock_k8s_clients.core_v1.delete_namespaced_config_map.side_effect = _not_found()
        delete_deployment("analysis-123-0")  # must not raise

    def test_custom_namespace_forwarded(self, mock_k8s_clients):
        delete_deployment("analysis-123-0", namespace="flame-ns")

        calls = mock_k8s_clients.apps_v1.delete_namespaced_deployment.call_args_list
        assert all(c[1]["namespace"] == "flame-ns" for c in calls)
        mock_k8s_clients.networking_v1.delete_namespaced_network_policy.assert_called_once_with(
            name="nginx-to-analysis-123-0-policy", namespace="flame-ns"
        )


# ─── get_analysis_logs ───────────────────────────────────────────────────────

class TestGetAnalysisLogs:
    def test_returns_analysis_and_nginx_structure(self, mock_k8s_clients, mock_database):
        mock_database.get_deployment_pod_ids.return_value = ["pod-1"]
        mock_k8s_clients.core_v1.list_namespaced_pod.return_value = _make_pod_list("pod-1")
        mock_k8s_clients.core_v1.read_namespaced_pod_log.return_value = "some log line\n"

        result = get_analysis_logs({"analysis-123": "analysis-123-0"}, mock_database)

        assert "analysis" in result
        assert "nginx" in result
        assert "analysis-123" in result["analysis"]
        assert "analysis-123" in result["nginx"]

    def test_pod_id_filter_limits_analysis_logs_to_known_pods(self, mock_k8s_clients, mock_database):
        """In the analysis path, only pods in pod_ids have logs fetched.
        The nginx path has no pod_ids filter and fetches all pods, so we use an
        empty nginx pod list to isolate the assertion to the analysis path.
        """
        mock_database.get_deployment_pod_ids.return_value = ["pod-1"]
        analysis_pod_list = _make_pod_list("pod-1", "pod-2")
        nginx_pod_list = _make_pod_list()  # nginx returns nothing -> no extra reads
        mock_k8s_clients.core_v1.list_namespaced_pod.side_effect = [
            analysis_pod_list,  # analysis deployment lookup
            nginx_pod_list,     # nginx deployment lookup
        ]
        mock_k8s_clients.core_v1.read_namespaced_pod_log.return_value = "log\n"

        get_analysis_logs({"analysis-123": "analysis-123-0"}, mock_database)

        log_call_args = mock_k8s_clients.core_v1.read_namespaced_pod_log.call_args_list
        pod_names_fetched = [c[0][0] for c in log_call_args]
        assert "pod-1" in pod_names_fetched
        assert "pod-2" not in pod_names_fetched

    def test_api_exception_returns_empty_list(self, mock_k8s_clients, mock_database):
        mock_database.get_deployment_pod_ids.return_value = ["pod-1"]
        mock_k8s_clients.core_v1.list_namespaced_pod.return_value = _make_pod_list("pod-1")
        mock_k8s_clients.core_v1.read_namespaced_pod_log.side_effect = ApiException(status=500)

        result = get_analysis_logs({"analysis-123": "analysis-123-0"}, mock_database)

        assert result["analysis"]["analysis-123"] == []

    def test_multiple_analyses(self, mock_k8s_clients, mock_database):
        mock_database.get_deployment_pod_ids.return_value = []
        mock_k8s_clients.core_v1.list_namespaced_pod.return_value = _make_pod_list()

        result = get_analysis_logs(
            {"analysis-1": "dep-1", "analysis-2": "dep-2"},
            mock_database,
        )

        assert set(result["analysis"].keys()) == {"analysis-1", "analysis-2"}
        assert set(result["nginx"].keys()) == {"analysis-1", "analysis-2"}

    def test_logs_sanitised_removes_info_lines(self, mock_k8s_clients, mock_database):
        """_get_logs strips lines starting with 'INFO:' and healthz GET lines."""
        mock_database.get_deployment_pod_ids.return_value = None
        mock_k8s_clients.core_v1.list_namespaced_pod.return_value = _make_pod_list("pod-1")
        mock_k8s_clients.core_v1.read_namespaced_pod_log.return_value = (
            "INFO: should be removed\n"
            'useful log line\n'
            '"GET /healthz HTTP/1.0" 200 OK\n'
        )

        result = get_analysis_logs({"analysis-123": "analysis-123-0"}, mock_database)

        combined = "\n".join(result["analysis"]["analysis-123"])
        assert "INFO:" not in combined
        assert "useful log line" in combined
        assert "healthz" not in combined


# ─── get_pod_status ──────────────────────────────────────────────────────────

class TestGetPodStatus:
    def _make_container_status(self, ready: bool, waiting=None, terminated=None) -> MagicMock:
        cs = MagicMock()
        cs.ready = ready
        cs.state.waiting = waiting
        cs.state.terminated = terminated
        return cs

    def _make_full_pod(self, name: str, container_status: MagicMock) -> MagicMock:
        pod = MagicMock()
        pod.metadata.name = name
        pod.status.container_statuses = [container_status]
        return pod

    def test_ready_pod_returns_empty_reason_and_message(self, mock_k8s_clients):
        cs = self._make_container_status(ready=True)
        pod = self._make_full_pod("pod-1", cs)
        mock_k8s_clients.core_v1.list_namespaced_pod.return_value.items = [pod]

        result = get_pod_status("analysis-123-0")

        assert result == {
            "pod-1": {"ready": True, "reason": "", "message": ""}
        }

    def test_waiting_pod_captures_reason_and_message(self, mock_k8s_clients):
        waiting = MagicMock()
        waiting.reason = "ImagePullBackOff"
        waiting.message = "Back-off pulling image"
        cs = self._make_container_status(ready=False, waiting=waiting)
        pod = self._make_full_pod("pod-1", cs)
        mock_k8s_clients.core_v1.list_namespaced_pod.return_value.items = [pod]

        result = get_pod_status("analysis-123-0")

        assert result["pod-1"]["ready"] is False
        assert result["pod-1"]["reason"] == "ImagePullBackOff"
        assert result["pod-1"]["message"] == "Back-off pulling image"

    def test_terminated_pod_captures_reason_and_message(self, mock_k8s_clients):
        terminated = MagicMock()
        terminated.reason = "OOMKilled"
        terminated.message = "Container ran out of memory"
        cs = self._make_container_status(ready=False, waiting=None, terminated=terminated)
        pod = self._make_full_pod("pod-1", cs)
        mock_k8s_clients.core_v1.list_namespaced_pod.return_value.items = [pod]

        result = get_pod_status("analysis-123-0")

        assert result["pod-1"]["ready"] is False
        assert result["pod-1"]["reason"] == "OOMKilled"
        assert result["pod-1"]["message"] == "Container ran out of memory"

    def test_unknown_error_state_returns_unknown_error(self, mock_k8s_clients):
        cs = self._make_container_status(ready=False, waiting=None, terminated=None)
        pod = self._make_full_pod("pod-1", cs)
        mock_k8s_clients.core_v1.list_namespaced_pod.return_value.items = [pod]

        result = get_pod_status("analysis-123-0")

        assert result["pod-1"]["reason"] == "UnknownError"
        assert "unknown error state" in result["pod-1"]["message"]

    def test_no_pods_returns_none(self, mock_k8s_clients):
        mock_k8s_clients.core_v1.list_namespaced_pod.return_value.items = []

        result = get_pod_status("analysis-123-0")

        assert result is None

    def test_multiple_pods_all_in_result(self, mock_k8s_clients):
        pods = [
            self._make_full_pod("pod-1", self._make_container_status(ready=True)),
            self._make_full_pod("pod-2", self._make_container_status(ready=True)),
        ]
        mock_k8s_clients.core_v1.list_namespaced_pod.return_value.items = pods

        result = get_pod_status("analysis-123-0")

        assert set(result.keys()) == {"pod-1", "pod-2"}

    def test_custom_namespace_forwarded(self, mock_k8s_clients):
        mock_k8s_clients.core_v1.list_namespaced_pod.return_value.items = []

        get_pod_status("analysis-123-0", namespace="flame-ns")

        mock_k8s_clients.core_v1.list_namespaced_pod.assert_called_once_with(
            namespace="flame-ns", label_selector="app=analysis-123-0"
        )