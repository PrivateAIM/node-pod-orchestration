"""Tests for src/api/oauth.py and the auth objects in src/api/constants.py.

The test session runs in Authup mode: conftest sets AUTHUP_JWKS_URL and unsets
KEYCLOAK_URL before src/api/constants.py is imported, so AUTHUP_CLIENT is the
module-level _ProxiedPyJWKClient and KEYCLOAK_SCHEME / KEYCLOAK_REALM_BASE are
None. Keycloak mode is exercised by patching src.api.oauth.KEYCLOAK_URL_FOUND /
KEYCLOAK_REALM_BASE; import-time backend selection and route wiring in
Keycloak mode are tested in fresh interpreters (subprocess).
"""

import inspect
import json
import os
import subprocess
import sys

import pytest
from unittest.mock import MagicMock, patch
from fastapi import HTTPException


KEYCLOAK_REALM_BASE = "http://keycloak.test/realms/flame/protocol/openid-connect"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _credentials(token="valid.jwt.token"):
    from fastapi.security import HTTPAuthorizationCredentials
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def _run_isolated(code, **env_overrides):
    """Run ``code`` in a fresh interpreter with a controlled auth env; return its last stdout line as JSON."""
    env = {k: v for k, v in os.environ.items() if k not in ("AUTHUP_JWKS_URL", "KEYCLOAK_URL", "KEYCLOAK_REALM")}
    env.update(env_overrides)
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


# ─── valid_analysis_token (Authup) ────────────────────────────────────────────

class TestValidAnalysisToken:
    def test_client_token_returns_decoded_payload(self):
        from src.api.oauth import valid_analysis_token

        payload = {"sub": "analysis-client", "sub_kind": "client", "exp": 1}
        mock_jwks_client = MagicMock()
        with (
            patch("src.api.oauth.AUTHUP_CLIENT", mock_jwks_client),
            patch("src.api.oauth.decode", return_value=payload) as mock_decode,
        ):
            assert valid_analysis_token(_credentials()) == payload

        mock_jwks_client.get_signing_key_from_jwt.assert_called_once_with("valid.jwt.token")
        assert mock_decode.call_args.args[0] == "valid.jwt.token"
        options = mock_decode.call_args.kwargs["options"]
        assert options["require"] == ["exp"]
        assert options["verify_signature"] is True
        assert options["verify_exp"] is True
        assert options["verify_aud"] is False

    def test_user_token_raises_401(self):
        from src.api.oauth import valid_analysis_token

        with (
            patch("src.api.oauth.AUTHUP_CLIENT", MagicMock()),
            patch("src.api.oauth.decode", return_value={"sub": "u", "sub_kind": "user", "exp": 1}),
        ):
            with pytest.raises(HTTPException) as exc_info:
                valid_analysis_token(_credentials())

        assert exc_info.value.status_code == 401
        assert "Not authenticated" in exc_info.value.detail

    def test_token_without_sub_kind_raises_401(self):
        from src.api.oauth import valid_analysis_token

        with (
            patch("src.api.oauth.AUTHUP_CLIENT", MagicMock()),
            patch("src.api.oauth.decode", return_value={"sub": "x", "exp": 1}),
        ):
            with pytest.raises(HTTPException) as exc_info:
                valid_analysis_token(_credentials())

        assert exc_info.value.status_code == 401

    def test_invalid_token_raises_401(self):
        import jwt as jwt_lib
        from src.api.oauth import valid_analysis_token

        mock_jwks_client = MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.side_effect = jwt_lib.exceptions.InvalidTokenError("bad token")

        with patch("src.api.oauth.AUTHUP_CLIENT", mock_jwks_client):
            with pytest.raises(HTTPException) as exc_info:
                valid_analysis_token(_credentials("bad.token.here"))

        assert exc_info.value.status_code == 401
        assert "Not authenticated" in exc_info.value.detail

    def test_missing_exp_claim_raises_401(self):
        import jwt as jwt_lib
        from src.api.oauth import valid_analysis_token

        with (
            patch("src.api.oauth.AUTHUP_CLIENT", MagicMock()),
            patch("src.api.oauth.decode", side_effect=jwt_lib.exceptions.MissingRequiredClaimError("exp")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                valid_analysis_token(_credentials())

        assert exc_info.value.status_code == 401

    def test_unknown_kid_raises_401(self):
        import jwt as jwt_lib
        from src.api.oauth import valid_analysis_token

        mock_jwks_client = MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.side_effect = (
            jwt_lib.exceptions.PyJWKClientError('Unable to find a signing key that matches: "x"')
        )
        with patch("src.api.oauth.AUTHUP_CLIENT", mock_jwks_client):
            with pytest.raises(HTTPException) as exc_info:
                valid_analysis_token(_credentials())

        assert exc_info.value.status_code == 401
        assert "Not authenticated" in exc_info.value.detail

    def test_jwks_connection_error_raises_503(self):
        import jwt as jwt_lib
        from src.api.oauth import valid_analysis_token

        mock_jwks_client = MagicMock()
        mock_jwks_client.get_signing_key_from_jwt.side_effect = (
            jwt_lib.exceptions.PyJWKClientConnectionError("down")
        )
        with (
            patch("src.api.oauth.AUTHUP_CLIENT", mock_jwks_client),
            patch("src.api.oauth.logger") as mock_logger,
        ):
            with pytest.raises(HTTPException) as exc_info:
                valid_analysis_token(_credentials())

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == "AUTHUP JWKS unavailable"
        mock_logger.error.assert_called_once()

    def test_unconfigured_jwks_url_raises_500(self):
        from src.api.oauth import valid_analysis_token

        with (
            patch("src.api.oauth.AUTHUP_CLIENT", None),
            patch("src.api.oauth.logger") as mock_logger,
        ):
            with pytest.raises(HTTPException) as exc_info:
                valid_analysis_token(_credentials())

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "AUTHUP_JWKS_URL is not configured"
        mock_logger.error.assert_called_once()

    def test_jwks_client_is_reused_across_calls(self):
        from src.api.oauth import valid_analysis_token

        mock_jwks_client = MagicMock()
        with (
            patch("src.api.oauth.AUTHUP_CLIENT", mock_jwks_client),
            patch("src.api.oauth.PyJWKClient") as mock_ctor,
            patch("src.api.oauth.decode", return_value={"sub": "x", "sub_kind": "client"}),
        ):
            valid_analysis_token(_credentials())
            valid_analysis_token(_credentials())

        mock_ctor.assert_not_called()
        assert mock_jwks_client.get_signing_key_from_jwt.call_count == 2


# ─── valid_access_token (Keycloak) ────────────────────────────────────────────

class TestValidAccessToken:
    @staticmethod
    def _keycloak_mode():
        return (
            patch("src.api.oauth.KEYCLOAK_URL_FOUND", True),
            patch("src.api.oauth.KEYCLOAK_REALM_BASE", KEYCLOAK_REALM_BASE),
        )

    def test_token_verified_against_realm_certs(self):
        from src.api.oauth import valid_access_token

        payload = {"sub": "user-id"}  # Keycloak tokens carry no sub_kind
        mode, realm = self._keycloak_mode()
        with (
            mode,
            realm,
            patch("src.api.oauth.PyJWKClient") as mock_ctor,
            patch("src.api.oauth.decode", return_value=payload) as mock_decode,
        ):
            assert valid_access_token("raw.jwt.token") == payload

        mock_ctor.assert_called_once_with(f"{KEYCLOAK_REALM_BASE}/certs")
        mock_ctor.return_value.get_signing_key_from_jwt.assert_called_once_with("raw.jwt.token")
        assert mock_decode.call_args.args[0] == "raw.jwt.token"
        options = mock_decode.call_args.kwargs["options"]
        assert options["verify_signature"] is True
        assert options["verify_exp"] is True
        assert options["verify_aud"] is False

    def test_logs_deprecation_warning_per_request(self):
        from src.api.oauth import valid_access_token

        mode, realm = self._keycloak_mode()
        with (
            mode,
            realm,
            patch("src.api.oauth.PyJWKClient"),
            patch("src.api.oauth.decode", return_value={"sub": "u"}),
            patch("src.api.oauth.logger") as mock_logger,
        ):
            valid_access_token("raw.jwt.token")
            valid_access_token("raw.jwt.token")

        assert mock_logger.warning.call_count == 2
        assert "deprecated" in mock_logger.warning.call_args.args[0]

    def test_called_without_keycloak_url_raises_500(self):
        from src.api.oauth import valid_access_token

        # Session default: KEYCLOAK_URL unset -> KEYCLOAK_URL_FOUND is False.
        with (
            patch("src.api.oauth.PyJWKClient") as mock_ctor,
            patch("src.api.oauth.logger") as mock_logger,
        ):
            with pytest.raises(HTTPException) as exc_info:
                valid_access_token("raw.jwt.token")

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == "KEYCLOAK_URL is not configured"
        mock_ctor.assert_not_called()
        mock_logger.warning.assert_not_called()

    def test_invalid_token_raises_401(self):
        import jwt as jwt_lib
        from src.api.oauth import valid_access_token

        mode, realm = self._keycloak_mode()
        with (
            mode,
            realm,
            patch("src.api.oauth.PyJWKClient"),
            patch("src.api.oauth.decode", side_effect=jwt_lib.exceptions.InvalidTokenError("bad")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                valid_access_token("bad.jwt.token")

        assert exc_info.value.status_code == 401

    def test_unknown_kid_raises_401(self):
        import jwt as jwt_lib
        from src.api.oauth import valid_access_token

        mode, realm = self._keycloak_mode()
        with mode, realm, patch("src.api.oauth.PyJWKClient") as mock_ctor:
            mock_ctor.return_value.get_signing_key_from_jwt.side_effect = (
                jwt_lib.exceptions.PyJWKClientError('Unable to find a signing key that matches: "x"')
            )
            with pytest.raises(HTTPException) as exc_info:
                valid_access_token("authup.signed.token")

        assert exc_info.value.status_code == 401

    def test_certs_connection_error_raises_503(self):
        import jwt as jwt_lib
        from src.api.oauth import valid_access_token

        mode, realm = self._keycloak_mode()
        with (
            mode,
            realm,
            patch("src.api.oauth.PyJWKClient") as mock_ctor,
            patch("src.api.oauth.logger"),
        ):
            mock_ctor.return_value.get_signing_key_from_jwt.side_effect = (
                jwt_lib.exceptions.PyJWKClientConnectionError("down")
            )
            with pytest.raises(HTTPException) as exc_info:
                valid_access_token("raw.jwt.token")

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == "JWKS unavailable"


# ─── Dependency / route wiring ────────────────────────────────────────────────

_PROTECTED_PATHS = {
    "/po/", "/po/history", "/po/history/{analysis_id}", "/po/logs", "/po/logs/{analysis_id}",
    "/po/status", "/po/status/{analysis_id}", "/po/pods", "/po/pods/{analysis_id}",
    "/po/stop", "/po/stop/{analysis_id}", "/po/delete", "/po/delete/{analysis_id}",
    "/po/cleanup/{cleanup_type}", "/po/stream_logs",
}


def route_auth(app):
    """Map each protected /po path to the security schemes its operations require.

    Read from the generated OpenAPI spec, so it is independent of FastAPI's
    internal route structure: ``HTTPBearer`` means valid_analysis_token
    (Authup), ``OAuth2AuthorizationCodeBearer`` means valid_access_token
    (Keycloak).
    """
    out = {}
    for path, ops in app.openapi()["paths"].items():
        if not path.startswith("/po") or path == "/po/healthz":
            continue
        out[path] = sorted({name for op in ops.values() for req in op.get("security", []) for name in req})
    return out


class TestDependencyWiring:
    def test_analysis_token_is_resolved_via_bearer_scheme(self):
        """The token must come from the Authorization header, never from query or body."""
        from fastapi.dependencies.utils import get_dependant
        from src.api.constants import AUTHUP_SCHEME
        from src.api.oauth import valid_analysis_token

        dependant = get_dependant(path="/x", call=valid_analysis_token)

        assert not dependant.body_params
        assert not dependant.query_params
        assert [d.call for d in dependant.dependencies] == [AUTHUP_SCHEME]

    def test_authup_mode_wires_analysis_token_on_every_route(self, api_test_client):
        wiring = route_auth(api_test_client.app)

        assert set(wiring) == _PROTECTED_PATHS
        assert all(schemes == ["HTTPBearer"] for schemes in wiring.values()), wiring

    def test_keycloak_mode_wiring(self):
        """In Keycloak mode only /po/stream_logs stays on Authup; the scheme comes from the header."""
        code = inspect.getsource(route_auth) + '''
import json
from unittest.mock import MagicMock, patch
from fastapi.dependencies.utils import get_dependant
from src.api import constants, oauth

captured = {}
with (
    patch("src.api.api.uvicorn.run", side_effect=lambda app, **kw: captured.setdefault("app", app)),
    patch("src.api.api.extract_hub_envs", return_value=("c", "s", "http://core", "http://auth", False, None, None)),
    patch("src.api.api.init_hub_client", return_value=MagicMock()),
    patch("src.api.api.get_node_id_by_client", return_value="node-id"),
):
    from src.api.api import PodOrchestrationAPI
    PodOrchestrationAPI(database=MagicMock(), namespace="default")

wiring = route_auth(captured["app"])
dep = get_dependant(path="/x", call=oauth.valid_access_token)
print(json.dumps({
    "wiring": wiring,
    "access_token_scheme_is_keycloak": [d.call for d in dep.dependencies] == [constants.KEYCLOAK_SCHEME],
    "access_token_query_params": [p.name for p in dep.query_params],
}))
'''
        result = _run_isolated(
            code,
            KEYCLOAK_URL="http://keycloak.test",
            AUTHUP_JWKS_URL="http://authup.test/jwks",
            POSTGRES_HOST="localhost", POSTGRES_USER="u", POSTGRES_PASSWORD="p", POSTGRES_DB="db",
        )

        wiring = result["wiring"]
        assert set(wiring) == _PROTECTED_PATHS
        assert wiring.pop("/po/stream_logs") == ["HTTPBearer"]
        assert all(schemes == ["OAuth2AuthorizationCodeBearer"] for schemes in wiring.values()), wiring
        assert result["access_token_scheme_is_keycloak"] is True
        assert result["access_token_query_params"] == []


# ─── Backend selection (src/api/constants.py) ─────────────────────────────────

class TestBackendSelection:
    """constants.py picks the backend at import time, so each case runs in a fresh interpreter."""

    _PROBE = (
        "import json; from src.api import constants as c; print(json.dumps({"
        "'keycloak': c.KEYCLOAK_URL_FOUND, "
        "'keycloak_scheme': type(c.KEYCLOAK_SCHEME).__name__, "
        "'realm_base': c.KEYCLOAK_REALM_BASE, "
        "'authup_client': type(c.AUTHUP_CLIENT).__name__, "
        "'authup_scheme': type(c.AUTHUP_SCHEME).__name__}))"
    )

    def test_authup_mode_when_keycloak_url_unset(self):
        r = _run_isolated(self._PROBE, AUTHUP_JWKS_URL="http://authup.test/jwks")
        assert r == {
            "keycloak": False, "keycloak_scheme": "NoneType", "realm_base": None,
            "authup_client": "_ProxiedPyJWKClient", "authup_scheme": "HTTPBearer",
        }

    def test_authup_mode_when_keycloak_url_empty(self):
        r = _run_isolated(self._PROBE, KEYCLOAK_URL="", AUTHUP_JWKS_URL="http://authup.test/jwks")
        assert r["keycloak"] is False
        assert r["keycloak_scheme"] == "NoneType"

    def test_keycloak_mode_keeps_authup_client(self):
        r = _run_isolated(
            self._PROBE, KEYCLOAK_URL="http://keycloak.test", KEYCLOAK_REALM="flame",
            AUTHUP_JWKS_URL="http://authup.test/jwks",
        )
        assert r == {
            "keycloak": True, "keycloak_scheme": "OAuth2AuthorizationCodeBearer", "realm_base": KEYCLOAK_REALM_BASE,
            "authup_client": "_ProxiedPyJWKClient", "authup_scheme": "HTTPBearer",
        }

    def test_keycloak_realm_defaults_to_flame(self):
        r = _run_isolated(self._PROBE, KEYCLOAK_URL="http://keycloak.test")
        assert r["realm_base"] == KEYCLOAK_REALM_BASE

    def test_no_authup_client_without_jwks_url(self):
        r = _run_isolated(self._PROBE, AUTHUP_JWKS_URL="")
        assert r["keycloak"] is False
        assert r["authup_client"] == "NoneType"


# ─── _ProxiedPyJWKClient ──────────────────────────────────────────────────────

class TestProxiedPyJWKClient:
    _JWKS = {"keys": [{"kty": "oct", "k": "c2VjcmV0", "alg": "HS256", "kid": "k1"}]}

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
        from src.api.constants import _ProxiedPyJWKClient

        response = MagicMock()
        response.json.return_value = self._JWKS
        ctor, http_client = self._ctor(response)
        client = _ProxiedPyJWKClient("https://authup.test/realms/master/jwks")

        with patch("src.api.constants.init_proxied_http_client", ctor):
            assert client.fetch_data() == self._JWKS

        ctor.assert_called_once_with(timeout=client.timeout)
        assert http_client.get.call_args.args[0] == "https://authup.test/realms/master/jwks"
        # The cache stores the parsed key set (PyJWT rejects empty key sets here).
        assert [k.key_id for k in client.jwk_set_cache.get().keys] == ["k1"]

    def test_http_error_raises_connection_error(self):
        import httpx2
        from jwt.exceptions import PyJWKClientConnectionError
        from src.api.constants import _ProxiedPyJWKClient

        ctor, _ = self._ctor(side_effect=httpx2.ConnectError("refused"))
        client = _ProxiedPyJWKClient("https://authup.test/realms/master/jwks")

        with patch("src.api.constants.init_proxied_http_client", ctor):
            with pytest.raises(PyJWKClientConnectionError):
                client.fetch_data()
