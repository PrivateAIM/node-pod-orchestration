from unittest.mock import patch, MagicMock
import requests


class TestCreateAnalysisTokens:
    def test_returns_both_keys(self):
        with patch("src.utils.token.get_analysis_token", return_value="authup-token"):
            from src.utils.token import create_analysis_tokens
            result = create_analysis_tokens("kong-tok", "analysis-1")
        assert result == {"DATA_SOURCE_TOKEN": "kong-tok", "AUTHUP_TOKEN": "authup-token"}

    def test_data_source_token_is_kong_token(self):
        with patch("src.utils.token.get_analysis_token", return_value="kc"):
            from src.utils.token import create_analysis_tokens
            result = create_analysis_tokens("my-kong-token", "aid")
        assert result["DATA_SOURCE_TOKEN"] == "my-kong-token"

    def test_authup_token_from_getter(self):
        with patch("src.utils.token.get_analysis_token", return_value="authup-abc") as mock_get:
            from src.utils.token import create_analysis_tokens
            result = create_analysis_tokens("tok", "aid")
        mock_get.assert_called_once_with("aid")
        assert result["AUTHUP_TOKEN"] == "authup-abc"


class TestGetAnalysisToken:
    def test_success_returns_access_token(self):
        mock_hub_client = MagicMock()
        mock_creds = MagicMock(id="client-uuid-1", secret="client-secret-1")
        mock_hub_client.update_analysis_client_credentials.return_value = mock_creds

        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "bearer-xyz"}

        with (
            patch("src.utils.token.extract_hub_envs", return_value=("cid", "csec", "core", "auth", "logging", "", "")),
            patch("src.utils.token.init_hub_client", return_value=mock_hub_client),
            patch("src.utils.token.requests.post", return_value=mock_response),
            patch("src.utils.token._AUTHUP_TOKEN_URL", "http://authup:8080/realms/master/token"),
        ):
            from src.utils.token import get_analysis_token
            result = get_analysis_token("analysis-1")

        assert result == "bearer-xyz"
        mock_hub_client.update_analysis_client_credentials.assert_called_once_with("analysis-1", secret=None)

    def test_posts_correct_grant_to_authup(self):
        mock_hub_client = MagicMock()
        mock_creds = MagicMock(id="client-uuid-1", secret="client-secret-1")
        mock_hub_client.update_analysis_client_credentials.return_value = mock_creds

        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "tok"}

        with (
            patch("src.utils.token.extract_hub_envs", return_value=("cid", "csec", "core", "auth", "logging", "", "")),
            patch("src.utils.token.init_hub_client", return_value=mock_hub_client),
            patch("src.utils.token.requests.post", return_value=mock_response) as mock_post,
            patch("src.utils.token._AUTHUP_TOKEN_URL", "http://authup:8080/realms/master/token"),
        ):
            from src.utils.token import get_analysis_token
            get_analysis_token("analysis-1")

        mock_post.assert_called_once_with(
            "http://authup:8080/realms/master/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "client-uuid-1",
                "client_secret": "client-secret-1",
            },
        )

    def test_hub_client_init_failure_returns_none(self):
        with (
            patch("src.utils.token.extract_hub_envs", return_value=("cid", "csec", "core", "auth", "logging", "", "")),
            patch("src.utils.token.init_hub_client", return_value=None),
        ):
            from src.utils.token import get_analysis_token
            result = get_analysis_token("analysis-1")

        assert result is None

    def test_credential_fetch_failure_returns_none(self):
        import flame_hub

        mock_hub_client = MagicMock()
        mock_hub_client.update_analysis_client_credentials.side_effect = flame_hub._exceptions.HubAPIError(
            "not found", request=MagicMock()
        )

        with (
            patch("src.utils.token.extract_hub_envs", return_value=("cid", "csec", "core", "auth", "logging", "", "")),
            patch("src.utils.token.init_hub_client", return_value=mock_hub_client),
        ):
            from src.utils.token import get_analysis_token
            result = get_analysis_token("analysis-1")

        assert result is None

    def test_token_request_exception_returns_none(self):
        mock_hub_client = MagicMock()
        mock_creds = MagicMock(id="client-uuid-1", secret="client-secret-1")
        mock_hub_client.update_analysis_client_credentials.return_value = mock_creds

        with (
            patch("src.utils.token.extract_hub_envs", return_value=("cid", "csec", "core", "auth", "logging", "", "")),
            patch("src.utils.token.init_hub_client", return_value=mock_hub_client),
            patch(
                "src.utils.token.requests.post",
                side_effect=requests.exceptions.RequestException("conn refused"),
            ),
            patch("src.utils.token._AUTHUP_TOKEN_URL", "http://authup:8080/realms/master/token"),
        ):
            from src.utils.token import get_analysis_token
            result = get_analysis_token("analysis-1")

        assert result is None

    def test_token_http_error_returns_none(self):
        mock_hub_client = MagicMock()
        mock_creds = MagicMock(id="client-uuid-1", secret="client-secret-1")
        mock_hub_client.update_analysis_client_credentials.return_value = mock_creds

        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("401")

        with (
            patch("src.utils.token.extract_hub_envs", return_value=("cid", "csec", "core", "auth", "logging", "", "")),
            patch("src.utils.token.init_hub_client", return_value=mock_hub_client),
            patch("src.utils.token.requests.post", return_value=mock_response),
            patch("src.utils.token._AUTHUP_TOKEN_URL", "http://authup:8080/realms/master/token"),
        ):
            from src.utils.token import get_analysis_token
            result = get_analysis_token("analysis-1")

        assert result is None
