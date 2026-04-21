import pytest
from unittest.mock import patch, MagicMock
import requests


class TestCreateAnalysisTokens:
    def test_returns_both_keys(self):
        with patch("src.utils.token.get_keycloak_token", return_value="kc-token"):
            from src.utils.token import create_analysis_tokens
            result = create_analysis_tokens("kong-tok", "analysis-1")
        assert result == {"DATA_SOURCE_TOKEN": "kong-tok", "KEYCLOAK_TOKEN": "kc-token"}

    def test_data_source_token_is_kong_token(self):
        with patch("src.utils.token.get_keycloak_token", return_value="kc"):
            from src.utils.token import create_analysis_tokens
            result = create_analysis_tokens("my-kong-token", "aid")
        assert result["DATA_SOURCE_TOKEN"] == "my-kong-token"

    def test_keycloak_token_from_getter(self):
        with patch("src.utils.token.get_keycloak_token", return_value="kc-abc") as mock_get:
            from src.utils.token import create_analysis_tokens
            result = create_analysis_tokens("tok", "aid")
        mock_get.assert_called_once_with("aid")
        assert result["KEYCLOAK_TOKEN"] == "kc-abc"


class TestGetKeycloakToken:
    def test_success_returns_access_token(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "bearer-xyz"}

        with (
            patch("src.utils.token._get_keycloak_client_secret", return_value="secret-123"),
            patch("src.utils.token.requests.post", return_value=mock_response),
            patch("src.utils.token._KEYCLOAK_URL", "http://kc:8080"),
        ):
            from src.utils.token import get_keycloak_token
            result = get_keycloak_token("analysis-1")

        assert result == "bearer-xyz"

    def test_request_exception_returns_none(self):
        with (
            patch("src.utils.token._get_keycloak_client_secret", return_value="sec"),
            patch(
                "src.utils.token.requests.post",
                side_effect=requests.exceptions.RequestException("conn refused"),
            ),
            patch("src.utils.token._KEYCLOAK_URL", "http://kc:8080"),
        ):
            from src.utils.token import get_keycloak_token
            result = get_keycloak_token("analysis-1")

        assert result is None

    def test_http_error_returns_none(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("404")

        with (
            patch("src.utils.token._get_keycloak_client_secret", return_value="sec"),
            patch("src.utils.token.requests.post", return_value=mock_response),
            patch("src.utils.token._KEYCLOAK_URL", "http://kc:8080"),
        ):
            from src.utils.token import get_keycloak_token
            result = get_keycloak_token("analysis-1")

        assert result is None

    def test_url_hardcodes_flame_realm(self):
        # Note: get_keycloak_token uses _KEYCLOAK_URL but hardcodes "flame" in the
        # path rather than reading _KEYCLOAK_REALM. Verify expected URL is used.
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok"}

        with (
            patch("src.utils.token._get_keycloak_client_secret", return_value="sec"),
            patch("src.utils.token.requests.post", return_value=mock_response) as mock_post,
            patch("src.utils.token._KEYCLOAK_URL", "http://kc:8080"),
        ):
            from src.utils.token import get_keycloak_token
            get_keycloak_token("analysis-1")

        call_url = mock_post.call_args[0][0]
        assert call_url == "http://kc:8080/realms/flame/protocol/openid-connect/token"


class TestGetKeycloakAdminToken:
    def test_success_returns_access_token(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "admin-bearer"}

        with (
            patch("src.utils.token.requests.post", return_value=mock_response),
            patch("src.utils.token._KEYCLOAK_URL", "http://kc:8080"),
            patch("src.utils.token._KEYCLOAK_REALM", "flame"),
        ):
            from src.utils.token import _get_keycloak_admin_token
            result = _get_keycloak_admin_token()

        assert result == "admin-bearer"

    def test_uses_result_client_credentials(self, monkeypatch):
        monkeypatch.setenv("RESULT_CLIENT_ID", "my-result-client")
        monkeypatch.setenv("RESULT_CLIENT_SECRET", "my-result-secret")

        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok"}

        with (
            patch("src.utils.token.requests.post", return_value=mock_response) as mock_post,
            patch("src.utils.token._KEYCLOAK_URL", "http://kc:8080"),
            patch("src.utils.token._KEYCLOAK_REALM", "flame"),
        ):
            from src.utils.token import _get_keycloak_admin_token
            _get_keycloak_admin_token()

        posted_data = mock_post.call_args[1]["data"]
        assert posted_data["client_id"] == "my-result-client"
        assert posted_data["client_secret"] == "my-result-secret"
        assert posted_data["grant_type"] == "client_credentials"


class TestKeycloakClientExists:
    def test_exists_returns_true(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [{"clientId": "analysis-1", "id": "uuid-1"}]

        with (
            patch("src.utils.token.requests.get", return_value=mock_response),
            patch("src.utils.token._KEYCLOAK_URL", "http://kc:8080"),
            patch("src.utils.token._KEYCLOAK_REALM", "flame"),
        ):
            from src.utils.token import _keycloak_client_exists
            result = _keycloak_client_exists("analysis-1", "admin-token")

        assert result is True

    def test_not_exists_returns_false(self):
        mock_response = MagicMock()
        mock_response.json.return_value = []

        with (
            patch("src.utils.token.requests.get", return_value=mock_response),
            patch("src.utils.token._KEYCLOAK_URL", "http://kc:8080"),
            patch("src.utils.token._KEYCLOAK_REALM", "flame"),
        ):
            from src.utils.token import _keycloak_client_exists
            result = _keycloak_client_exists("analysis-1", "admin-token")

        assert result is False

    def test_uses_correct_url_and_auth_header(self):
        mock_response = MagicMock()
        mock_response.json.return_value = []

        with (
            patch("src.utils.token.requests.get", return_value=mock_response) as mock_get,
            patch("src.utils.token._KEYCLOAK_URL", "http://kc:8080"),
            patch("src.utils.token._KEYCLOAK_REALM", "testrealm"),
        ):
            from src.utils.token import _keycloak_client_exists
            _keycloak_client_exists("my-analysis", "my-admin-token")

        mock_get.assert_called_once_with(
            "http://kc:8080/admin/realms/testrealm/clients?clientId=my-analysis",
            headers={"Authorization": "Bearer my-admin-token"},
        )


class TestCreateKeycloakClient:
    def test_posts_correct_payload(self):
        mock_response = MagicMock()

        with (
            patch("src.utils.token.requests.post", return_value=mock_response) as mock_post,
            patch("src.utils.token._KEYCLOAK_URL", "http://kc:8080"),
            patch("src.utils.token._KEYCLOAK_REALM", "flame"),
        ):
            from src.utils.token import _create_keycloak_client
            _create_keycloak_client("admin-tok", "analysis-abc")

        mock_post.assert_called_once_with(
            "http://kc:8080/admin/realms/flame/clients",
            headers={
                "Authorization": "Bearer admin-tok",
                "Content-Type": "application/json",
            },
            json={
                "clientId": "analysis-abc",
                "name": "flame-analysis-abc",
                "serviceAccountsEnabled": "true",
            },
        )

    def test_raises_on_http_error(self):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("409")

        with (
            patch("src.utils.token.requests.post", return_value=mock_response),
            patch("src.utils.token._KEYCLOAK_URL", "http://kc:8080"),
            patch("src.utils.token._KEYCLOAK_REALM", "flame"),
        ):
            from src.utils.token import _create_keycloak_client
            with pytest.raises(requests.exceptions.HTTPError):
                _create_keycloak_client("admin-tok", "analysis-abc")


class TestGetKeycloakClientSecret:
    def test_client_exists_skips_creation(self):
        mock_get_response = MagicMock()
        mock_get_response.json.return_value = [{"secret": "my-secret"}]

        with (
            patch("src.utils.token._get_keycloak_admin_token", return_value="admin-tok"),
            patch("src.utils.token._keycloak_client_exists", return_value=True),
            patch("src.utils.token._create_keycloak_client") as mock_create,
            patch("src.utils.token.requests.get", return_value=mock_get_response),
            patch("src.utils.token._KEYCLOAK_URL", "http://kc:8080"),
            patch("src.utils.token._KEYCLOAK_REALM", "flame"),
        ):
            from src.utils.token import _get_keycloak_client_secret
            result = _get_keycloak_client_secret("analysis-1")

        mock_create.assert_not_called()
        assert result == "my-secret"

    def test_client_not_exists_creates_then_gets_secret(self):
        mock_get_response = MagicMock()
        mock_get_response.json.return_value = [{"secret": "new-secret"}]

        with (
            patch("src.utils.token._get_keycloak_admin_token", return_value="admin-tok"),
            patch("src.utils.token._keycloak_client_exists", return_value=False),
            patch("src.utils.token._create_keycloak_client") as mock_create,
            patch("src.utils.token.requests.get", return_value=mock_get_response),
            patch("src.utils.token._KEYCLOAK_URL", "http://kc:8080"),
            patch("src.utils.token._KEYCLOAK_REALM", "flame"),
        ):
            from src.utils.token import _get_keycloak_client_secret
            result = _get_keycloak_client_secret("analysis-1")

        mock_create.assert_called_once_with("admin-tok", "analysis-1")
        assert result == "new-secret"


class TestDeleteKeycloakClient:
    def test_success_deletes_by_uuid(self):
        mock_get_response = MagicMock()
        mock_get_response.json.return_value = [{"id": "uuid-abc", "clientId": "analysis-1"}]
        mock_delete_response = MagicMock()

        with (
            patch("src.utils.token._get_keycloak_admin_token", return_value="admin-tok"),
            patch("src.utils.token.requests.get", return_value=mock_get_response),
            patch(
                "src.utils.token.requests.delete", return_value=mock_delete_response
            ) as mock_delete,
            patch("src.utils.token._KEYCLOAK_URL", "http://kc:8080"),
            patch("src.utils.token._KEYCLOAK_REALM", "flame"),
        ):
            from src.utils.token import delete_keycloak_client
            delete_keycloak_client("analysis-1")

        mock_delete.assert_called_once_with(
            "http://kc:8080/admin/realms/flame/clients/uuid-abc",
            headers={"Authorization": "Bearer admin-tok"},
        )

    def test_client_not_found_skips_delete(self):
        mock_get_response = MagicMock()
        mock_get_response.json.return_value = []

        with (
            patch("src.utils.token._get_keycloak_admin_token", return_value="admin-tok"),
            patch("src.utils.token.requests.get", return_value=mock_get_response),
            patch("src.utils.token.requests.delete") as mock_delete,
            patch("src.utils.token._KEYCLOAK_URL", "http://kc:8080"),
            patch("src.utils.token._KEYCLOAK_REALM", "flame"),
        ):
            from src.utils.token import delete_keycloak_client
            result = delete_keycloak_client("analysis-1")

        mock_delete.assert_not_called()
        assert result is None

    def test_missing_id_key_returns_gracefully(self):
        # Response has entry but no 'id' key — KeyError caught, returns None
        mock_get_response = MagicMock()
        mock_get_response.json.return_value = [{"clientId": "analysis-1"}]

        with (
            patch("src.utils.token._get_keycloak_admin_token", return_value="admin-tok"),
            patch("src.utils.token.requests.get", return_value=mock_get_response),
            patch("src.utils.token.requests.delete") as mock_delete,
            patch("src.utils.token._KEYCLOAK_URL", "http://kc:8080"),
            patch("src.utils.token._KEYCLOAK_REALM", "flame"),
        ):
            from src.utils.token import delete_keycloak_client
            delete_keycloak_client("analysis-1")

        mock_delete.assert_not_called()