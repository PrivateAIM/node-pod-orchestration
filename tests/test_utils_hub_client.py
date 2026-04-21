import ssl
from json import JSONDecodeError
from unittest.mock import MagicMock, patch, call

import pytest
from httpx import HTTPStatusError, ConnectError, ConnectTimeout


# ─── TestInitHubClientWithClient ─────────────────────────────────────────────

class TestInitHubClientWithClient:
    def test_success_returns_core_client(self):
        mock_core_client = MagicMock()
        mock_ssl_ctx = MagicMock()

        with (
            patch("src.utils.hub_client.get_ssl_context", return_value=mock_ssl_ctx),
            patch("src.utils.hub_client.Client") as mock_httpx_client,
            patch("src.utils.hub_client.flame_hub.auth.ClientAuth") as mock_auth,
            patch("src.utils.hub_client.flame_hub.CoreClient", return_value=mock_core_client),
        ):
            from src.utils.hub_client import init_hub_client_with_client
            result = init_hub_client_with_client(
                client_id="cid",
                client_secret="csec",
                hub_url_core="http://core:3000",
                hub_auth="http://auth:3001",
                http_proxy="",
                https_proxy="",
            )

        assert result is mock_core_client

    def test_exception_returns_none(self):
        with (
            patch("src.utils.hub_client.get_ssl_context", return_value=MagicMock()),
            patch("src.utils.hub_client.Client", side_effect=Exception("conn failed")),
        ):
            from src.utils.hub_client import init_hub_client_with_client
            result = init_hub_client_with_client(
                client_id="cid",
                client_secret="csec",
                hub_url_core="http://core:3000",
                hub_auth="http://auth:3001",
                http_proxy="",
                https_proxy="",
            )

        assert result is None

    def test_with_proxies_creates_http_transports(self):
        mock_ssl_ctx = MagicMock()
        mock_transport = MagicMock()

        with (
            patch("src.utils.hub_client.get_ssl_context", return_value=mock_ssl_ctx),
            patch("src.utils.hub_client.HTTPTransport", return_value=mock_transport) as mock_transport_cls,
            patch("src.utils.hub_client.Client") as mock_httpx_client,
            patch("src.utils.hub_client.flame_hub.auth.ClientAuth"),
            patch("src.utils.hub_client.flame_hub.CoreClient"),
        ):
            from src.utils.hub_client import init_hub_client_with_client
            init_hub_client_with_client(
                client_id="cid",
                client_secret="csec",
                hub_url_core="http://core:3000",
                hub_auth="http://auth:3001",
                http_proxy="http://proxy:8080",
                https_proxy="https://proxy:8443",
            )

        assert mock_transport_cls.call_count == 2
        # HTTP transport gets just proxy
        mock_transport_cls.assert_any_call(proxy="http://proxy:8080")
        # HTTPS transport gets proxy + verify
        mock_transport_cls.assert_any_call(proxy="https://proxy:8443", verify=mock_ssl_ctx)

    def test_without_proxies_passes_none_mounts(self):
        """When proxy strings are empty, mounts=None is passed to Client."""
        mock_ssl_ctx = MagicMock()

        with (
            patch("src.utils.hub_client.get_ssl_context", return_value=mock_ssl_ctx),
            patch("src.utils.hub_client.Client") as mock_httpx_client,
            patch("src.utils.hub_client.flame_hub.auth.ClientAuth"),
            patch("src.utils.hub_client.flame_hub.CoreClient"),
        ):
            from src.utils.hub_client import init_hub_client_with_client
            init_hub_client_with_client(
                client_id="cid",
                client_secret="csec",
                hub_url_core="http://core:3000",
                hub_auth="http://auth:3001",
                http_proxy="",
                https_proxy="",
            )

        first_call_kwargs = mock_httpx_client.call_args_list[0][1]
        assert first_call_kwargs["mounts"] is None


# ─── TestGetSslContext ────────────────────────────────────────────────────────

class TestGetSslContext:
    def setup_method(self):
        from src.utils.hub_client import get_ssl_context
        get_ssl_context.cache_clear()

    def teardown_method(self):
        from src.utils.hub_client import get_ssl_context
        get_ssl_context.cache_clear()

    def test_without_extra_certs_does_not_load_verify_locations(self, monkeypatch):
        monkeypatch.delenv("EXTRA_CA_CERTS", raising=False)
        mock_ctx = MagicMock(spec=ssl.SSLContext)

        with patch("src.utils.hub_client.truststore.SSLContext", return_value=mock_ctx):
            from src.utils.hub_client import get_ssl_context
            result = get_ssl_context()

        assert result is mock_ctx
        mock_ctx.load_verify_locations.assert_not_called()

    def test_with_existing_cert_path_loads_verify_locations(self, monkeypatch, tmp_path):
        cert_file = tmp_path / "ca.crt"
        cert_file.write_text("FAKE CERT")
        monkeypatch.setenv("EXTRA_CA_CERTS", str(cert_file))
        mock_ctx = MagicMock(spec=ssl.SSLContext)

        with patch("src.utils.hub_client.truststore.SSLContext", return_value=mock_ctx):
            from src.utils.hub_client import get_ssl_context
            result = get_ssl_context()

        assert result is mock_ctx
        mock_ctx.load_verify_locations.assert_called_once_with(cafile=str(cert_file))

    def test_with_nonexistent_cert_path_does_not_load(self, monkeypatch):
        monkeypatch.setenv("EXTRA_CA_CERTS", "/nonexistent/path/ca.crt")
        mock_ctx = MagicMock(spec=ssl.SSLContext)

        with patch("src.utils.hub_client.truststore.SSLContext", return_value=mock_ctx):
            from src.utils.hub_client import get_ssl_context
            result = get_ssl_context()

        assert result is mock_ctx
        mock_ctx.load_verify_locations.assert_not_called()


# ─── TestGetNodeIdByClient ────────────────────────────────────────────────────

class TestGetNodeIdByClient:
    def test_success_returns_string_id(self, mock_hub_client):
        mock_node = MagicMock()
        mock_node.id = "node-uuid-123"
        mock_hub_client.find_nodes.return_value = [mock_node]

        from src.utils.hub_client import get_node_id_by_client
        result = get_node_id_by_client(mock_hub_client, "my-client-id")

        assert result == "node-uuid-123"
        mock_hub_client.find_nodes.assert_called_once_with(filter={"client_id": "my-client-id"})

    def test_http_status_error_returns_none(self, mock_hub_client):
        mock_hub_client.find_nodes.side_effect = HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        )

        from src.utils.hub_client import get_node_id_by_client
        result = get_node_id_by_client(mock_hub_client, "cid")

        assert result is None

    def test_json_decode_error_returns_none(self, mock_hub_client):
        mock_hub_client.find_nodes.side_effect = JSONDecodeError("err", "", 0)

        from src.utils.hub_client import get_node_id_by_client
        result = get_node_id_by_client(mock_hub_client, "cid")

        assert result is None

    def test_connect_timeout_returns_none(self, mock_hub_client):
        mock_hub_client.find_nodes.side_effect = ConnectTimeout("timeout")

        from src.utils.hub_client import get_node_id_by_client
        result = get_node_id_by_client(mock_hub_client, "cid")

        assert result is None

    def test_attribute_error_returns_none(self, mock_hub_client):
        mock_hub_client.find_nodes.side_effect = AttributeError("no attr")

        from src.utils.hub_client import get_node_id_by_client
        result = get_node_id_by_client(mock_hub_client, "cid")

        assert result is None

    def test_hub_api_error_returns_none(self, mock_hub_client):
        import flame_hub
        mock_hub_client.find_nodes.side_effect = flame_hub._exceptions.HubAPIError(
            "hub error", request=MagicMock()
        )

        from src.utils.hub_client import get_node_id_by_client
        result = get_node_id_by_client(mock_hub_client, "cid")

        assert result is None


# ─── TestGetNodeAnalysisId ────────────────────────────────────────────────────

class TestGetNodeAnalysisId:
    def test_success_returns_string_id(self, mock_hub_client):
        mock_node_analysis = MagicMock()
        mock_node_analysis.id = "na-uuid-456"
        mock_hub_client.find_analysis_nodes.return_value = [mock_node_analysis]

        from src.utils.hub_client import get_node_analysis_id
        result = get_node_analysis_id(mock_hub_client, "analysis-1", "node-obj-id")

        assert result == "na-uuid-456"
        mock_hub_client.find_analysis_nodes.assert_called_once_with(
            filter={"analysis_id": "analysis-1", "node_id": "node-obj-id"}
        )

    def test_empty_list_returns_none(self, mock_hub_client):
        mock_hub_client.find_analysis_nodes.return_value = []

        from src.utils.hub_client import get_node_analysis_id
        result = get_node_analysis_id(mock_hub_client, "analysis-1", "node-obj-id")

        assert result is None

    def test_http_status_error_returns_none(self, mock_hub_client):
        mock_hub_client.find_analysis_nodes.side_effect = HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )

        from src.utils.hub_client import get_node_analysis_id
        result = get_node_analysis_id(mock_hub_client, "analysis-1", "node-obj-id")

        assert result is None

    def test_hub_api_error_returns_none(self, mock_hub_client):
        import flame_hub
        mock_hub_client.find_analysis_nodes.side_effect = flame_hub._exceptions.HubAPIError(
            "err", request=MagicMock()
        )

        from src.utils.hub_client import get_node_analysis_id
        result = get_node_analysis_id(mock_hub_client, "analysis-1", "node-obj-id")

        assert result is None

    def test_attribute_error_returns_none(self, mock_hub_client):
        mock_hub_client.find_analysis_nodes.side_effect = AttributeError("no attr")

        from src.utils.hub_client import get_node_analysis_id
        result = get_node_analysis_id(mock_hub_client, "analysis-1", "node-obj-id")

        assert result is None


# ─── TestUpdateHubStatus ──────────────────────────────────────────────────────

class TestUpdateHubStatus:
    def test_success_without_progress(self, mock_hub_client):
        from src.utils.hub_client import update_hub_status
        update_hub_status(mock_hub_client, "na-id", "started")

        mock_hub_client.update_analysis_node.assert_called_once_with(
            "na-id", execution_status="started"
        )

    def test_success_with_progress(self, mock_hub_client):
        from src.utils.hub_client import update_hub_status
        update_hub_status(mock_hub_client, "na-id", "executing", run_progress=42)

        mock_hub_client.update_analysis_node.assert_called_once_with(
            "na-id", execution_status="executing", execution_progress=42
        )

    def test_stuck_status_mapped_to_failed(self, mock_hub_client):
        from src.utils.hub_client import update_hub_status
        from src.status.constants import AnalysisStatus
        update_hub_status(mock_hub_client, "na-id", AnalysisStatus.STUCK.value)

        mock_hub_client.update_analysis_node.assert_called_once_with(
            "na-id", execution_status=AnalysisStatus.FAILED.value
        )

    def test_http_status_error_does_not_raise(self, mock_hub_client):
        mock_hub_client.update_analysis_node.side_effect = HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )

        from src.utils.hub_client import update_hub_status
        # Should not raise
        update_hub_status(mock_hub_client, "na-id", "started")

    def test_connect_error_does_not_raise(self, mock_hub_client):
        mock_hub_client.update_analysis_node.side_effect = ConnectError("conn refused")

        from src.utils.hub_client import update_hub_status
        update_hub_status(mock_hub_client, "na-id", "started")

    def test_attribute_error_does_not_raise(self, mock_hub_client):
        mock_hub_client.update_analysis_node.side_effect = AttributeError("no attr")

        from src.utils.hub_client import update_hub_status
        update_hub_status(mock_hub_client, "na-id", "started")

    def test_hub_api_error_does_not_raise(self, mock_hub_client):
        import flame_hub
        mock_hub_client.update_analysis_node.side_effect = flame_hub._exceptions.HubAPIError(
            "err", request=MagicMock()
        )

        from src.utils.hub_client import update_hub_status
        update_hub_status(mock_hub_client, "na-id", "started")


# ─── TestGetPartnerNodeStatuses ───────────────────────────────────────────────

class TestGetPartnerNodeStatuses:
    def test_self_filtered_out(self, mock_hub_client):
        node_a = MagicMock()
        node_a.id = "self-id"
        node_a.execution_status = "started"
        node_b = MagicMock()
        node_b.id = "partner-id"
        node_b.execution_status = "executing"
        mock_hub_client.find_analysis_nodes.return_value = [node_a, node_b]

        from src.utils.hub_client import get_partner_node_statuses
        result = get_partner_node_statuses(mock_hub_client, "analysis-1", "self-id")

        assert result == {"partner-id": "executing"}
        assert "self-id" not in result

    def test_all_partners_returned_when_no_self(self, mock_hub_client):
        node_a = MagicMock()
        node_a.id = "partner-a"
        node_a.execution_status = "started"
        node_b = MagicMock()
        node_b.id = "partner-b"
        node_b.execution_status = "finished"
        mock_hub_client.find_analysis_nodes.return_value = [node_a, node_b]

        from src.utils.hub_client import get_partner_node_statuses
        result = get_partner_node_statuses(mock_hub_client, "analysis-1", "self-id")

        assert result == {"partner-a": "started", "partner-b": "finished"}

    def test_returns_none_when_hub_call_fails(self, mock_hub_client):
        mock_hub_client.find_analysis_nodes.side_effect = HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )

        from src.utils.hub_client import get_partner_node_statuses
        result = get_partner_node_statuses(mock_hub_client, "analysis-1", "self-id")

        assert result is None

    def test_empty_analysis_nodes_returns_empty_dict(self, mock_hub_client):
        mock_hub_client.find_analysis_nodes.return_value = []

        from src.utils.hub_client import get_partner_node_statuses
        result = get_partner_node_statuses(mock_hub_client, "analysis-1", "self-id")

        assert result == {}