"""
Tests for src/k8s/utils.py

Covers:
  - load_cluster_config
  - get_current_namespace (file found / not found)
  - find_k8s_resources: all resource types, selectors, empty/single/multiple results
  - delete_k8s_resource: all types, 404 handled gracefully, unsupported type error
"""

import pytest
from unittest.mock import MagicMock, patch, mock_open

from kubernetes.client.exceptions import ApiException

from src.k8s.utils import (
    load_cluster_config,
    get_current_namespace,
    find_k8s_resources,
    delete_k8s_resource,
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _make_resource_list(names: list[str]) -> MagicMock:
    """Build a mock K8s list response with .items containing named resources."""
    result = MagicMock()
    items = []
    for name in names:
        item = MagicMock()
        item.metadata.name = name
        items.append(item)
    result.items = items
    return result


# ─── load_cluster_config ─────────────────────────────────────────────────────

class TestLoadClusterConfig:
    def test_delegates_to_incluster_config(self):
        with patch("src.k8s.utils.config.load_incluster_config") as mock_load:
            load_cluster_config()
            mock_load.assert_called_once_with()


# ─── get_current_namespace ───────────────────────────────────────────────────

class TestGetCurrentNamespace:
    def test_reads_namespace_from_file(self):
        with patch("builtins.open", mock_open(read_data="flame-namespace\n")):
            result = get_current_namespace()
        assert result == "flame-namespace"

    def test_returns_default_when_file_not_found(self):
        with patch("builtins.open", side_effect=FileNotFoundError):
            result = get_current_namespace()
        assert result == "default"

    def test_strips_whitespace_from_file_content(self):
        with patch("builtins.open", mock_open(read_data="  my-ns  \n")):
            result = get_current_namespace()
        assert result == "my-ns"


# ─── find_k8s_resources ──────────────────────────────────────────────────────

class TestFindK8sResourcesValidation:
    def test_invalid_resource_type_raises(self):
        with pytest.raises(ValueError, match="resource_type must be one of"):
            find_k8s_resources("unknown")

    def test_invalid_selector_type_raises(self):
        with pytest.raises(ValueError, match="selector_type must be either"):
            find_k8s_resources("pod", selector_type="invalid")

    def test_selector_type_without_arg_raises(self):
        with pytest.raises(ValueError, match="selector_arg must not be None"):
            find_k8s_resources("pod", selector_type="label")


class TestFindK8sResourcesResults:
    """Tests for each resource type and result-count behaviours."""

    def test_deployment_single_result(self, mock_k8s_clients):
        mock_k8s_clients.apps_v1.list_namespaced_deployment.return_value = (
            _make_resource_list(["analysis-123-0"])
        )
        result = find_k8s_resources("deployment")[0]
        print(mock_k8s_clients.apps_v1.list_namespaced_deployment.return_value, result)
        assert result == "analysis-123-0"

    def test_deployment_multiple_results(self, mock_k8s_clients):
        mock_k8s_clients.apps_v1.list_namespaced_deployment.return_value = (
            _make_resource_list(["analysis-123-0", "analysis-456-0"])
        )
        result = find_k8s_resources("deployment")
        assert result == ["analysis-123-0", "analysis-456-0"]

    def test_deployment_empty_returns_none(self, mock_k8s_clients):
        mock_k8s_clients.apps_v1.list_namespaced_deployment.return_value = (
            _make_resource_list([])
        )
        result = find_k8s_resources("deployment")
        assert result == [None]

    def test_networkpolicy_resource(self, mock_k8s_clients):
        mock_k8s_clients.networking_v1.list_namespaced_network_policy.return_value = (
            _make_resource_list(["np-analysis-123"])
        )
        result = find_k8s_resources("networkpolicy")[0]
        assert result == "np-analysis-123"

    def test_pod_resource(self, mock_k8s_clients):
        mock_k8s_clients.core_v1.list_namespaced_pod.return_value = (
            _make_resource_list(["pod-abc"])
        )
        result = find_k8s_resources("pod")[0]
        assert result == "pod-abc"

    def test_service_resource(self, mock_k8s_clients):
        mock_k8s_clients.core_v1.list_namespaced_service.return_value = (
            _make_resource_list(["svc-analysis-123"])
        )
        result = find_k8s_resources("service")[0]
        assert result == "svc-analysis-123"

    def test_configmap_resource(self, mock_k8s_clients):
        mock_k8s_clients.core_v1.list_namespaced_config_map.return_value = (
            _make_resource_list(["cm-nginx-123"])
        )
        result = find_k8s_resources("configmap")[0]
        assert result == "cm-nginx-123"

    def test_job_resource(self, mock_k8s_clients):
        mock_k8s_clients.batch_v1.list_namespaced_job.return_value = (
            _make_resource_list(["job-analysis-123"])
        )
        result = find_k8s_resources("job")[0]
        assert result == "job-analysis-123"


class TestFindK8sResourcesSelectors:
    def test_label_selector_forwarded_to_api(self, mock_k8s_clients):
        mock_k8s_clients.apps_v1.list_namespaced_deployment.return_value = (
            _make_resource_list(["dep-1"])
        )
        find_k8s_resources("deployment", selector_type="label", selector_arg="app=my-app")
        mock_k8s_clients.apps_v1.list_namespaced_deployment.assert_called_once_with(
            namespace="default", label_selector="app=my-app"
        )

    def test_field_selector_forwarded_to_api(self, mock_k8s_clients):
        mock_k8s_clients.core_v1.list_namespaced_pod.return_value = (
            _make_resource_list(["pod-1"])
        )
        find_k8s_resources("pod", selector_type="field", selector_arg="status.phase=Running")
        mock_k8s_clients.core_v1.list_namespaced_pod.assert_called_once_with(
            namespace="default", field_selector="status.phase=Running"
        )

    def test_custom_namespace_forwarded_to_api(self, mock_k8s_clients):
        mock_k8s_clients.apps_v1.list_namespaced_deployment.return_value = (
            _make_resource_list(["dep-1"])
        )
        find_k8s_resources("deployment", namespace="flame-ns")
        mock_k8s_clients.apps_v1.list_namespaced_deployment.assert_called_once_with(
            namespace="flame-ns"
        )


class TestFindK8sResourcesManualNameSelector:
    def test_filters_to_single_match(self, mock_k8s_clients):
        mock_k8s_clients.apps_v1.list_namespaced_deployment.return_value = (
            _make_resource_list(["analysis-123-dep", "analysis-456-dep", "other-dep"])
        )
        result = find_k8s_resources("deployment", manual_name_selector="analysis-123")
        assert result == "analysis-123-dep"

    def test_returns_list_when_multiple_match(self, mock_k8s_clients):
        mock_k8s_clients.apps_v1.list_namespaced_deployment.return_value = (
            _make_resource_list(["analysis-123-dep-0", "analysis-123-dep-1", "other-dep"])
        )
        result = find_k8s_resources("deployment", manual_name_selector="analysis-123")
        assert result == ["analysis-123-dep-0", "analysis-123-dep-1"]

    def test_no_match_raises_index_error(self, mock_k8s_clients):
        """Documents a bug in find_k8s_resources: when manual_name_selector matches
        none of the multi-result names, the filtered list is empty but the code still
        executes `resource_names[0]`, raising IndexError (utils.py line 63)."""
        mock_k8s_clients.apps_v1.list_namespaced_deployment.return_value = (
            _make_resource_list(["analysis-456-dep", "other-dep"])
        )
        with pytest.raises(IndexError):
            find_k8s_resources("deployment", manual_name_selector="analysis-123")


# ─── delete_k8s_resource ─────────────────────────────────────────────────────

class TestDeleteK8sResourceTypes:
    """Verify that each resource type calls the correct K8s API method."""

    def test_delete_deployment(self, mock_k8s_clients):
        delete_k8s_resource("my-dep", "deployment")
        mock_k8s_clients.apps_v1.delete_namespaced_deployment.assert_called_once_with(
            name="my-dep", namespace="default", propagation_policy="Foreground"
        )

    def test_delete_service(self, mock_k8s_clients):
        delete_k8s_resource("my-svc", "service")
        mock_k8s_clients.core_v1.delete_namespaced_service.assert_called_once_with(
            name="my-svc", namespace="default"
        )

    def test_delete_pod(self, mock_k8s_clients):
        delete_k8s_resource("my-pod", "pod")
        mock_k8s_clients.core_v1.delete_namespaced_pod.assert_called_once_with(
            name="my-pod", namespace="default"
        )

    def test_delete_configmap(self, mock_k8s_clients):
        delete_k8s_resource("my-cm", "configmap")
        mock_k8s_clients.core_v1.delete_namespaced_config_map.assert_called_once_with(
            name="my-cm", namespace="default"
        )

    def test_delete_networkpolicy(self, mock_k8s_clients):
        delete_k8s_resource("my-policy", "networkpolicy")
        mock_k8s_clients.networking_v1.delete_namespaced_network_policy.assert_called_once_with(
            name="my-policy", namespace="default"
        )

    def test_delete_job(self, mock_k8s_clients):
        delete_k8s_resource("my-job", "job")
        mock_k8s_clients.batch_v1.delete_namespaced_job.assert_called_once_with(
            name="my-job", namespace="default", propagation_policy="Foreground"
        )

    def test_custom_namespace_forwarded(self, mock_k8s_clients):
        delete_k8s_resource("my-dep", "deployment", namespace="flame-ns")
        mock_k8s_clients.apps_v1.delete_namespaced_deployment.assert_called_once_with(
            name="my-dep", namespace="flame-ns", propagation_policy="Foreground"
        )

    def test_unsupported_type_raises_value_error(self, mock_k8s_clients):
        with pytest.raises(ValueError, match="Unsupported resource type"):
            delete_k8s_resource("my-thing", "unknown")


class TestDeleteK8sResource404Handling:
    """404 ApiExceptions must be swallowed for every resource type."""

    def _not_found_exc(self):
        return ApiException(status=404, reason="Not Found")

    def test_deployment_404_is_silent(self, mock_k8s_clients):
        mock_k8s_clients.apps_v1.delete_namespaced_deployment.side_effect = (
            self._not_found_exc()
        )
        delete_k8s_resource("gone", "deployment")  # must not raise

    def test_service_404_is_silent(self, mock_k8s_clients):
        mock_k8s_clients.core_v1.delete_namespaced_service.side_effect = (
            self._not_found_exc()
        )
        delete_k8s_resource("gone", "service")

    def test_pod_404_is_silent(self, mock_k8s_clients):
        mock_k8s_clients.core_v1.delete_namespaced_pod.side_effect = (
            self._not_found_exc()
        )
        delete_k8s_resource("gone", "pod")

    def test_configmap_404_is_silent(self, mock_k8s_clients):
        mock_k8s_clients.core_v1.delete_namespaced_config_map.side_effect = (
            self._not_found_exc()
        )
        delete_k8s_resource("gone", "configmap")

    def test_networkpolicy_404_is_silent(self, mock_k8s_clients):
        mock_k8s_clients.networking_v1.delete_namespaced_network_policy.side_effect = (
            self._not_found_exc()
        )
        delete_k8s_resource("gone", "networkpolicy")

    def test_job_404_is_silent(self, mock_k8s_clients):
        mock_k8s_clients.batch_v1.delete_namespaced_job.side_effect = (
            self._not_found_exc()
        )
        delete_k8s_resource("gone", "job")