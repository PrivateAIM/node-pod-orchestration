import ssl
from json import JSONDecodeError
from unittest.mock import MagicMock, patch, call

import pytest
from flame_hub._exceptions import HubAPIError
from httpx2 import HTTPStatusError, ConnectError, ConnectTimeout, ReadTimeout


# ─── TestInitHubClientWithClient ─────────────────────────────────────────────

class TestInitHubClientWithClient:
    def test_success_returns_core_client(self):
        mock_core_client = MagicMock()
        mock_ssl_ctx = MagicMock()

        with (
            patch("src.utils.hub_client.get_ssl_context", return_value=mock_ssl_ctx),
            patch("src.utils.hub_client.Client") as mock_httpx_client,
            patch("src.utils.hub_client.ClientAuth") as mock_auth,
            patch("src.utils.hub_client.HubClient", return_value=mock_core_client),
        ):
            from src.utils.hub_client import init_hub_client
            result = init_hub_client(
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
            from src.utils.hub_client import init_hub_client
            result = init_hub_client(
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
            patch("src.utils.hub_client.ClientAuth"),
            patch("src.utils.hub_client.HubClient"),
        ):
            from src.utils.hub_client import init_hub_client
            init_hub_client(
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
            patch("src.utils.hub_client.ClientAuth"),
            patch("src.utils.hub_client.HubClient"),
        ):
            from src.utils.hub_client import init_hub_client
            init_hub_client(
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

class TestProxiedHttpClient:
    def test_proxy_mounts_none_without_both_proxies(self):
        from src.utils.hub_client import get_proxy_mounts
        assert get_proxy_mounts("", "", MagicMock()) is None
        assert get_proxy_mounts("http://proxy:3128", None, MagicMock()) is None

    def test_proxy_mounts_with_both_proxies(self):
        ssl_ctx = MagicMock()
        with patch("src.utils.hub_client.HTTPTransport") as mock_transport:
            from src.utils.hub_client import get_proxy_mounts
            mounts = get_proxy_mounts("http://p:1", "http://p:2", ssl_ctx)
        assert set(mounts) == {"http://", "https://"}
        mock_transport.assert_any_call(proxy="http://p:1")
        mock_transport.assert_any_call(proxy="http://p:2", verify=ssl_ctx)

    def test_init_proxied_http_client_uses_po_proxies_and_ssl_context(self, monkeypatch):
        monkeypatch.setenv("PO_HTTP_PROXY", "http://p:1")
        monkeypatch.setenv("PO_HTTPS_PROXY", "http://p:2")
        ssl_ctx = MagicMock()
        with (
            patch("src.utils.hub_client.get_ssl_context", return_value=ssl_ctx),
            patch("src.utils.hub_client.get_proxy_mounts", return_value={"m": 1}) as mock_mounts,
            patch("src.utils.hub_client.Client") as mock_client,
        ):
            from src.utils.hub_client import init_proxied_http_client
            result = init_proxied_http_client(timeout=5)
        mock_mounts.assert_called_once_with("http://p:1", "http://p:2", ssl_ctx)
        mock_client.assert_called_once_with(mounts={"m": 1}, verify=ssl_ctx, timeout=5)
        assert result is mock_client.return_value


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
        mock_hub_client.find_nodes.side_effect = HubAPIError(
            "hub error", request=MagicMock()
        )

        from src.utils.hub_client import get_node_id_by_client
        result = get_node_id_by_client(mock_hub_client, "cid")

        assert result is None


# ─── TestGetRegistryCredentials ──────────────────────────────────────────────

class TestGetRegistryCredentials:
    def test_success_returns_credentials(self, mock_hub_client):
        from src.utils.hub_client import get_registry_credentials

        result = get_registry_credentials(mock_hub_client, "node-uuid")

        mock_hub_client.get_node_registry_credentials.assert_called_once_with("node-uuid")
        assert result.host == "harbor.privateaim"
        assert result.external_name == "node_project"
        assert result.account_secret == "robot_secret"

    @pytest.mark.parametrize("hub_client, node_id", [(None, "node-uuid"), (MagicMock(), None)])
    def test_missing_client_or_node_raises(self, hub_client, node_id):
        from src.utils.hub_client import RegistryCredentialsError, get_registry_credentials

        with pytest.raises(RegistryCredentialsError):
            get_registry_credentials(hub_client, node_id)

    @pytest.mark.parametrize(
        "error",
        [
            ConnectError("down"),
            ConnectTimeout("slow"),
            ReadTimeout("slow read"),
            HTTPStatusError("502", request=MagicMock(), response=MagicMock()),
            JSONDecodeError("bad body", "", 0),
        ],
    )
    def test_transport_errors_raise(self, mock_hub_client, error):
        from src.utils.hub_client import RegistryCredentialsError, get_registry_credentials

        mock_hub_client.get_node_registry_credentials.side_effect = error

        with pytest.raises(RegistryCredentialsError):
            get_registry_credentials(mock_hub_client, "node-uuid")

    def test_hub_api_error_raises(self, mock_hub_client):
        from flame_hub._exceptions import HubAPIError

        from src.utils.hub_client import RegistryCredentialsError, get_registry_credentials

        mock_hub_client.get_node_registry_credentials.side_effect = HubAPIError(
            "The node has no registry project provisioned yet.", request=MagicMock()
        )

        with pytest.raises(RegistryCredentialsError):
            get_registry_credentials(mock_hub_client, "node-uuid")

    def test_unknown_node_raises(self, mock_hub_client):
        from src.utils.hub_client import RegistryCredentialsError, get_registry_credentials

        mock_hub_client.get_node_registry_credentials.return_value = None

        with pytest.raises(RegistryCredentialsError):
            get_registry_credentials(mock_hub_client, "node-uuid")

    @pytest.mark.parametrize(
        "host, external_name", [("", "node_project"), ("harbor.privateaim", "")]
    )
    def test_empty_host_or_project_raises(self, mock_hub_client, host, external_name):
        from flame_hub.models import NodeRegistryCredentials

        from src.utils.hub_client import RegistryCredentialsError, get_registry_credentials

        mock_hub_client.get_node_registry_credentials.return_value = NodeRegistryCredentials(
            host=host,
            externalName=external_name,
            accountName="robot$node_project",
            accountSecret="robot_secret",
        )

        with pytest.raises(RegistryCredentialsError):
            get_registry_credentials(mock_hub_client, "node-uuid")

    def test_missing_robot_account_raises(self, mock_hub_client):
        from flame_hub.models import NodeRegistryCredentials

        from src.utils.hub_client import RegistryCredentialsError, get_registry_credentials

        mock_hub_client.get_node_registry_credentials.return_value = NodeRegistryCredentials(
            host="harbor.privateaim",
            externalName="node_project",
            accountName=None,
            accountSecret=None,
        )

        with pytest.raises(RegistryCredentialsError):
            get_registry_credentials(mock_hub_client, "node-uuid")


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

    def test_empty_list_returns_empty_list(self, mock_hub_client):
        mock_hub_client.find_analysis_nodes.return_value = []

        from src.utils.hub_client import get_node_analysis_id
        result = get_node_analysis_id(mock_hub_client, "analysis-1", "node-obj-id")

        assert result == []

    def test_http_status_error_returns_none(self, mock_hub_client):
        mock_hub_client.find_analysis_nodes.side_effect = HTTPStatusError(
            "500", request=MagicMock(), response=MagicMock()
        )

        from src.utils.hub_client import get_node_analysis_id
        result = get_node_analysis_id(mock_hub_client, "analysis-1", "node-obj-id")

        assert result is None

    def test_hub_api_error_returns_none(self, mock_hub_client):
        mock_hub_client.find_analysis_nodes.side_effect = HubAPIError(
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
        mock_hub_client.update_analysis_node.side_effect = HubAPIError(
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

# ─── Broadened httpx2 error handling ─────────────────────────────────────────
# All Hub wrappers catch the HTTPError base class (plus JSONDecodeError and
# HubAPIError), so any transport failure is handled, not only the subclasses
# that used to be listed explicitly.

_TRANSPORT_ERRORS = [
    ConnectError("down"),
    ConnectTimeout("slow"),
    ReadTimeout("slow read"),
    HTTPStatusError("502", request=MagicMock(), response=MagicMock()),
    JSONDecodeError("bad body", "", 0),
]


class TestHubWrappersCatchAllTransportErrors:
    @pytest.mark.parametrize("error", _TRANSPORT_ERRORS)
    def test_get_node_id_by_client_returns_none(self, mock_hub_client, error):
        from src.utils.hub_client import get_node_id_by_client
        mock_hub_client.find_nodes.side_effect = error

        assert get_node_id_by_client(mock_hub_client, "cid") is None

    @pytest.mark.parametrize("error", _TRANSPORT_ERRORS)
    def test_get_node_analysis_id_returns_none(self, mock_hub_client, error):
        from src.utils.hub_client import get_node_analysis_id
        mock_hub_client.find_analysis_nodes.side_effect = error

        assert get_node_analysis_id(mock_hub_client, "analysis-1", "node-obj-id") is None

    @pytest.mark.parametrize("error", _TRANSPORT_ERRORS)
    def test_update_hub_status_does_not_raise(self, mock_hub_client, error):
        from src.utils.hub_client import update_hub_status
        mock_hub_client.update_analysis_node.side_effect = error

        update_hub_status(mock_hub_client, "na-id", "started")

    @pytest.mark.parametrize("error", _TRANSPORT_ERRORS)
    def test_get_analysis_node_statuses_returns_none(self, mock_hub_client, error):
        from src.utils.hub_client import get_analysis_node_statuses
        mock_hub_client.find_analysis_nodes.side_effect = error

        assert get_analysis_node_statuses(mock_hub_client, "analysis-1") is None


# ─── TestGetNodeAnalysisIdWithoutNode ─────────────────────────────────────────

class TestGetNodeAnalysisIdWithoutNode:
    def test_returns_all_analysis_node_ids(self, mock_hub_client):
        node_a, node_b = MagicMock(), MagicMock()
        node_a.id, node_b.id = "na-1", "na-2"
        mock_hub_client.find_analysis_nodes.return_value = [node_a, node_b]

        from src.utils.hub_client import get_node_analysis_id
        result = get_node_analysis_id(mock_hub_client, "analysis-1")

        assert result == ["na-1", "na-2"]
        mock_hub_client.find_analysis_nodes.assert_called_once_with(
            filter={"analysis_id": "analysis-1"}
        )


# ─── TestGetNodeAnalysisStatus ────────────────────────────────────────────────

class TestGetNodeAnalysisStatus:
    def test_returns_status_of_own_node(self, mock_hub_client):
        own, partner = MagicMock(), MagicMock()
        own.id, own.execution_status = "self-id", "executed"
        partner.id, partner.execution_status = "partner-id", "executing"
        mock_hub_client.find_analysis_nodes.return_value = [partner, own]

        from src.utils.hub_client import get_node_analysis_status
        assert get_node_analysis_status(mock_hub_client, "analysis-1", "self-id") == "executed"

    def test_unknown_node_returns_none(self, mock_hub_client):
        from src.utils.hub_client import get_node_analysis_status
        assert get_node_analysis_status(mock_hub_client, "analysis-1", "other-id") is None

    def test_no_analysis_nodes_returns_none(self, mock_hub_client):
        """The Hub returning no analysis-nodes (e.g. deleted analysis) yields None, not ''."""
        mock_hub_client.find_analysis_nodes.return_value = []

        from src.utils.hub_client import get_node_analysis_status
        assert get_node_analysis_status(mock_hub_client, "analysis-1", "self-id") is None

    def test_hub_failure_returns_none(self, mock_hub_client):
        mock_hub_client.find_analysis_nodes.side_effect = ConnectError("down")

        from src.utils.hub_client import get_node_analysis_status
        assert get_node_analysis_status(mock_hub_client, "analysis-1", "self-id") is None


# ─── TestCreateAnalysisNodeLog ────────────────────────────────────────────────

class TestCreateAnalysisNodeLog:
    def test_forwards_log_to_hub(self, mock_hub_client):
        from src.utils.hub_client import create_analysis_node_log
        create_analysis_node_log(mock_hub_client, "analysis-1", "node-1", "executing", "info", "msg")

        mock_hub_client.create_analysis_node_log.assert_called_once_with(
            analysis_id="analysis-1",
            node_id="node-1",
            status="executing",
            level="info",
            message="msg",
        )

    @pytest.mark.parametrize(
        "error", _TRANSPORT_ERRORS + [HubAPIError("err", request=MagicMock())]
    )
    def test_errors_are_logged_not_raised(self, mock_hub_client, error):
        mock_hub_client.create_analysis_node_log.side_effect = error

        from src.utils.hub_client import create_analysis_node_log
        with patch("src.utils.hub_client.logger") as mock_logger:
            create_analysis_node_log(mock_hub_client, "analysis-1", "node-1", "executing", "info", "msg")

        mock_logger.error.assert_called_once()


# ─── TestGetAnalysisClientCredentials ─────────────────────────────────────────

class TestGetAnalysisClientCredentials:
    def test_returns_credentials(self, mock_hub_client):
        creds = MagicMock(id="client-id", secret="secret")
        mock_hub_client.get_analysis_client_credentials.return_value = creds

        from src.utils.hub_client import get_analysis_client_credentials
        assert get_analysis_client_credentials(mock_hub_client, "analysis-1") is creds
        mock_hub_client.get_analysis_client_credentials.assert_called_once_with("analysis-1")

    @pytest.mark.parametrize(
        "error", _TRANSPORT_ERRORS + [HubAPIError("err", request=MagicMock())]
    )
    def test_errors_return_none(self, mock_hub_client, error):
        mock_hub_client.get_analysis_client_credentials.side_effect = error

        from src.utils.hub_client import get_analysis_client_credentials
        assert get_analysis_client_credentials(mock_hub_client, "analysis-1") is None
