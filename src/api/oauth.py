"""Bearer token validation for the Pod Orchestration API.

Provides the :func:`valid_access_token` FastAPI dependency, which verifies
incoming JWTs against the Keycloak realm's JWKS endpoint and returns the
decoded claims. Injected into every protected route except
``POST /po/stream_logs``, which uses :func:`valid_analysis_token` to verify
Authup-issued analysis tokens instead.
"""

import os
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer, OAuth2AuthorizationCodeBearer

from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError
import jwt
from httpx2 import HTTPError
from typing import Annotated, Any

from src.utils.hub_client import init_proxied_http_client


_KEYCLOAK_URL = os.getenv("KEYCLOAK_URL")
_REALM = os.getenv("KEYCLOAK_REALM", "flame")
_REALM_BASE = f"{_KEYCLOAK_URL}/realms/{_REALM}/protocol/openid-connect"


_oauth2_scheme = OAuth2AuthorizationCodeBearer(
    tokenUrl=f"{_REALM_BASE}/token",
    authorizationUrl=f"{_REALM_BASE}/auth",
    refreshUrl=f"{_REALM_BASE}/token",
)


def valid_access_token(token: Annotated[str, Depends(_oauth2_scheme)]) -> dict:
    """FastAPI dependency that validates a Keycloak-issued OAuth2 bearer token.

    Fetches the Keycloak realm's signing keys via JWKS and verifies the token's
    signature and expiration. Audience validation is intentionally disabled.

    Args:
        token: The bearer token extracted from the ``Authorization`` header by
            the OAuth2 scheme.

    Returns:
        The decoded JWT claims as a dictionary.

    Raises:
        HTTPException: 401 if the token is invalid, expired, or cannot be
            verified against the realm's signing keys.
    """
    try:
        sig_key = PyJWKClient(f"{_REALM_BASE}/certs").get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            key=sig_key,
            options={"verify_signature": True, "verify_aud": False, "verify_exp": True},
        )
    except jwt.exceptions.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Not authenticated")


class _ProxiedPyJWKClient(PyJWKClient):
    """PyJWKClient that fetches the JWK set through the node's Hub proxy/CA settings.

    The global Authup instance lives next to the Hub, so it is only reachable
    the way the Hub client reaches it (``PO_HTTP(S)_PROXY`` mounts and
    ``EXTRA_CA_CERTS``); PyJWKClient's default urllib fetch honours neither.
    """

    def fetch_data(self) -> Any:
        try:
            with init_proxied_http_client(timeout=self.timeout) as http_client:
                response = http_client.get(self.uri, headers=self.headers)
                response.raise_for_status()
                jwk_set = response.json()
        except (HTTPError, ValueError) as e:
            raise PyJWKClientConnectionError(
                f'Fail to fetch data from the url, err: "{e}"'
            ) from e
        # Same cache contract as PyJWKClient.fetch_data: only cache successes.
        if self.jwk_set_cache is not None:
            self.jwk_set_cache.put(jwk_set)
        return jwk_set


_AUTHUP_JWKS_URL = os.getenv("AUTHUP_JWKS_URL")
# Created once so PyJWKClient's JWK-set cache and kid LRU persist across
# requests, instead of fetching Authup's JWKS on every /po/stream_logs call.
_authup_jwks_client = _ProxiedPyJWKClient(_AUTHUP_JWKS_URL) if _AUTHUP_JWKS_URL else None
_analysis_token_scheme = HTTPBearer()


def valid_analysis_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_analysis_token_scheme)]
) -> dict:
    """FastAPI dependency that validates an Authup-issued analysis bearer token.

    Analysis containers call ``POST /po/stream_logs`` directly (via their
    nginx sidecar) using the ``AUTHUP_TOKEN`` minted for them against the
    global Authup instance — a different issuer than the node-local Keycloak
    ``valid_access_token`` verifies against.

    Args:
        credentials: The bearer token extracted from the ``Authorization``
            header.

    Returns:
        The decoded JWT claims as a dictionary.

    Raises:
        HTTPException: 401 if the token is invalid, expired, or cannot be
            verified against Authup's signing keys; 500 if
            ``AUTHUP_JWKS_URL`` is not configured.
    """
    if _authup_jwks_client is None:
        raise HTTPException(status_code=500, detail="AUTHUP_JWKS_URL is not configured")
    try:
        sig_key = _authup_jwks_client.get_signing_key_from_jwt(credentials.credentials)
        return jwt.decode(
            credentials.credentials,
            key=sig_key,
            options={"verify_signature": True, "verify_aud": False, "verify_exp": True},
        )
    except jwt.exceptions.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Not authenticated")
