"""Bearer token validation for the Pod Orchestration API.

Every protected route verifies its bearer token against the global Authup
instance's JWKS (``AUTHUP_JWKS_URL``):

* :func:`valid_access_token` guards every route except ``POST /po/stream_logs``.
  It accepts any Authup-issued token, since the Hub Adapter forwards both user
  tokens and tokens minted for the node's Hub client.
* :func:`valid_analysis_token` guards ``POST /po/stream_logs``, which analysis
  containers call directly. It additionally requires an Authup *client* token.
"""

import os
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError, PyJWKClientError
import jwt
from httpx2 import HTTPError
from typing import Annotated, Any

from src.utils.hub_client import init_proxied_http_client
from src.utils.po_logging import get_logger


logger = get_logger()


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
# requests, instead of fetching Authup's JWKS on every call.
_authup_jwks_client = _ProxiedPyJWKClient(_AUTHUP_JWKS_URL) if _AUTHUP_JWKS_URL else None
_bearer_scheme = HTTPBearer()


def _verify_authup_token(token: str) -> dict:
    """Verify an Authup-issued JWT and return its claims.

    Checks the signature against Authup's signing keys and the expiration
    (``exp`` is required). Audience validation is intentionally disabled.

    Raises:
        HTTPException: 401 if the token is invalid, expired, lacks ``exp`` or
            cannot be matched to/verified against Authup's signing keys; 503 if
            Authup's JWKS cannot be fetched; 500 if ``AUTHUP_JWKS_URL`` is not
            configured.
    """
    if _authup_jwks_client is None:
        raise HTTPException(status_code=500, detail="AUTHUP_JWKS_URL is not configured")
    try:
        sig_key = _authup_jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            key=sig_key,
            options={
                "verify_signature": True,
                "verify_aud": False,
                "verify_exp": True,
                "require": ["exp"],
            },
        )
    except PyJWKClientConnectionError as e:
        logger.error(f"Failed to fetch Authup JWKS: {repr(e)}")
        raise HTTPException(status_code=503, detail="Authup JWKS unavailable") from e
    except PyJWKClientError:
        # e.g. no signing key matches the token's kid
        raise HTTPException(status_code=401, detail="Not authenticated") from None
    except jwt.exceptions.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Not authenticated") from None


def valid_access_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)]
) -> dict:
    """FastAPI dependency that validates an Authup-issued bearer token.

    Accepts user and client tokens alike: the Hub Adapter forwards the user's
    own token, or one minted for the node's Hub client (e.g. for autostart).

    Args:
        credentials: The bearer token extracted from the ``Authorization``
            header.

    Returns:
        The decoded JWT claims as a dictionary.

    Raises:
        HTTPException: see :func:`_verify_authup_token`.
    """
    return _verify_authup_token(credentials.credentials)


def valid_analysis_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer_scheme)]
) -> dict:
    """FastAPI dependency that validates an Authup-issued analysis bearer token.

    Analysis containers call ``POST /po/stream_logs`` directly (via their
    nginx sidecar) using the ``AUTHUP_TOKEN`` minted for them against the
    global Authup instance. On top of :func:`_verify_authup_token`, the token
    must be an Authup *client* token (``sub_kind == "client"``), as minted via
    the client_credentials grant for an analysis; Authup user tokens are
    rejected.

    Args:
        credentials: The bearer token extracted from the ``Authorization``
            header.

    Returns:
        The decoded JWT claims as a dictionary.

    Raises:
        HTTPException: 401 if the token is not a client token, otherwise see
            :func:`_verify_authup_token`.
    """
    claims = _verify_authup_token(credentials.credentials)
    if claims.get("sub_kind") != "client":
        raise HTTPException(status_code=401, detail="Not authenticated")
    return claims
