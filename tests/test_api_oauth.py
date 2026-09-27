"""Tests for src/api/oauth.py.

Drives async functions via anyio.run() (no pytest-asyncio required).
Patches module-level env reads (oauth.py reads KEYCLOAK_URL at import time).
"""

import anyio
import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException


# ─── TestValidAccessToken ─────────────────────────────────────────────────────

class TestValidAccessToken:
    def test_valid_token_returns_decoded_payload(self):
        from src.api.oauth import valid_access_token

        fake_token = "valid.jwt.token"
        fake_payload = {"sub": "user-id", "preferred_username": "testuser"}

        mock_signing_key = MagicMock()
        mock_signing_key.key = "fake-key"

        mock_jwks_client = MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.return_value = mock_signing_key

        with (
            patch("src.api.oauth.PyJWKClient", return_value=mock_jwks_client),
            patch("src.api.oauth.jwt.decode", return_value=fake_payload),
        ):
            result = valid_access_token(fake_token)

        assert result == fake_payload

    def test_invalid_token_raises_401(self):
        import jwt as jwt_lib
        from src.api.oauth import valid_access_token

        mock_jwks_client = MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.side_effect = jwt_lib.exceptions.InvalidTokenError("bad token")

        with patch("src.api.oauth.PyJWKClient", return_value=mock_jwks_client):
            with pytest.raises(HTTPException) as exc_info:
                valid_access_token("bad.token.here")

        assert exc_info.value.status_code == 401
        assert "Not authenticated" in exc_info.value.detail


# ─── TestValidAnalysisToken ───────────────────────────────────────────────────

class TestValidAnalysisToken:
    def test_valid_token_returns_decoded_payload(self):
        from fastapi.security import HTTPAuthorizationCredentials
        from src.api.oauth import valid_analysis_token

        fake_credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid.jwt.token")
        fake_payload = {"sub": "analysis-client-id"}

        mock_signing_key = MagicMock()
        mock_signing_key.key = "fake-key"

        mock_jwks_client = MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.return_value = mock_signing_key

        with (
            patch("src.api.oauth._authup_jwks_client", mock_jwks_client),
            patch("src.api.oauth.jwt.decode", return_value=fake_payload),
        ):
            result = valid_analysis_token(fake_credentials)

        assert result == fake_payload

    def test_invalid_token_raises_401(self):
        import jwt as jwt_lib
        from fastapi.security import HTTPAuthorizationCredentials
        from src.api.oauth import valid_analysis_token

        fake_credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="bad.token.here")

        mock_jwks_client = MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.side_effect = jwt_lib.exceptions.InvalidTokenError("bad token")

        with patch("src.api.oauth._authup_jwks_client", mock_jwks_client):
            with pytest.raises(HTTPException) as exc_info:
                valid_analysis_token(fake_credentials)

        assert exc_info.value.status_code == 401
        assert "Not authenticated" in exc_info.value.detail

    def test_client_is_reused_across_calls(self):
        from fastapi.security import HTTPAuthorizationCredentials
        from src.api.oauth import valid_analysis_token

        fake_credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid.jwt.token")
        mock_jwks_client = MagicMock()

        with (
            patch("src.api.oauth._authup_jwks_client", mock_jwks_client),
            patch("src.api.oauth.PyJWKClient") as mock_ctor,
            patch("src.api.oauth.jwt.decode", return_value={"sub": "x"}),
        ):
            valid_analysis_token(fake_credentials)
            valid_analysis_token(fake_credentials)

        mock_ctor.assert_not_called()
        assert mock_jwks_client.get_signing_key_from_jwt.call_count == 2

    def test_unconfigured_jwks_url_raises_500(self):
        from fastapi.security import HTTPAuthorizationCredentials
        from src.api.oauth import valid_analysis_token

        fake_credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="valid.jwt.token")

        with patch("src.api.oauth._authup_jwks_client", None):
            with pytest.raises(HTTPException) as exc_info:
                valid_analysis_token(fake_credentials)

        assert exc_info.value.status_code == 500

# ─── _ProxiedPyJWKClient ──────────────────────────────────────────────────────

class TestProxiedPyJWKClient:
    @staticmethod
    def _ctor(response=None, side_effect=None):
        http_client = MagicMock()
        http_client.__enter__.return_value = http_client
        if side_effect is not None:
            http_client.get.side_effect = side_effect
        else:
            http_client.get.return_value = response
        return MagicMock(return_value=http_client), http_client

    def test_fetches_jwks_through_proxied_client_and_caches(self):
        from src.api.oauth import _ProxiedPyJWKClient

        response = MagicMock()
        response.json.return_value = {"keys": []}
        ctor, http_client = self._ctor(response)
        client = _ProxiedPyJWKClient("https://authup.test/realms/master/jwks")

        with patch("src.api.oauth.init_proxied_http_client", ctor):
            assert client.fetch_data() == {"keys": []}

        ctor.assert_called_once_with(timeout=client.timeout)
        assert http_client.get.call_args.args[0] == "https://authup.test/realms/master/jwks"
        assert client.jwk_set_cache.get() == {"keys": []}

    def test_http_error_raises_connection_error(self):
        import httpx2
        from jwt.exceptions import PyJWKClientConnectionError
        from src.api.oauth import _ProxiedPyJWKClient

        ctor, _ = self._ctor(side_effect=httpx2.ConnectError("refused"))
        client = _ProxiedPyJWKClient("https://authup.test/realms/master/jwks")

        with patch("src.api.oauth.init_proxied_http_client", ctor):
            with pytest.raises(PyJWKClientConnectionError):
                client.fetch_data()
