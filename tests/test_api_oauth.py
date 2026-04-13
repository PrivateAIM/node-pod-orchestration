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
            result = anyio.run(valid_access_token, fake_token)

        assert result == fake_payload

    def test_invalid_token_raises_401(self):
        import jwt as jwt_lib
        from src.api.oauth import valid_access_token

        mock_jwks_client = MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.side_effect = jwt_lib.exceptions.InvalidTokenError("bad token")

        with patch("src.api.oauth.PyJWKClient", return_value=mock_jwks_client):
            with pytest.raises(HTTPException) as exc_info:
                anyio.run(valid_access_token, "bad.token.here")

        assert exc_info.value.status_code == 401
        assert "Not authenticated" in exc_info.value.detail