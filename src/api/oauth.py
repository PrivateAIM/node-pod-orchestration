"""Bearer token validation for the Pod Orchestration API.

Two FastAPI dependencies verify bearer tokens; :mod:`src.api.api` wires them
according to :data:`~src.api.constants.KEYCLOAK_URL_FOUND`:

* :func:`valid_analysis_token` verifies against the global Authup instance's
  JWKS and only accepts Authup *client* tokens (``sub_kind == "client"``).
  It always guards ``POST /po/stream_logs``, and guards every other protected
  route in Authup mode (``KEYCLOAK_URL`` unset or empty).
* :func:`valid_access_token` verifies against the local Keycloak realm. It
  guards every protected route except ``POST /po/stream_logs`` in Keycloak
  mode (``KEYCLOAK_URL`` set). It must only be wired in Keycloak mode: it
  depends on :data:`~src.api.constants.KEYCLOAK_SCHEME`, which is ``None``
  otherwise, and FastAPI cannot register a route with ``Depends(None)``.
"""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from jwt import PyJWKClient, decode
from jwt.exceptions import InvalidTokenError, PyJWKClientError, PyJWKClientConnectionError
from typing import Annotated

from src.api.constants import AUTHUP_CLIENT, AUTHUP_SCHEME, KEYCLOAK_URL_FOUND, KEYCLOAK_REALM_BASE, KEYCLOAK_SCHEME
from src.utils.po_logging import get_logger


logger = get_logger()


def valid_access_token(token: Annotated[str, Depends(KEYCLOAK_SCHEME)]) -> dict:
    """FastAPI dependency that validates a Keycloak bearer token (deprecated).

    The token is checked against the local realm's ``/certs`` endpoint
    (``{KEYCLOAK_REALM_BASE}/certs``); signature and expiration are verified,
    audience validation is intentionally disabled. Every call logs a warning
    that Keycloak authentication is scheduled for deprecation.

    Only wire this dependency in Keycloak mode (see the module docstring).

    Args:
        token: The raw bearer token extracted by
            :data:`~src.api.constants.KEYCLOAK_SCHEME`.

    Returns:
        The decoded JWT claims as a dictionary.

    Raises:
        HTTPException: 401 if the token is malformed, invalid, expired or cannot
            be matched to/verified against the realm's signing keys; 503 if the
            realm's JWKS cannot be fetched; 500 if ``KEYCLOAK_URL`` is not
            configured (only reachable by calling the function directly).
    """
    try:
        if KEYCLOAK_URL_FOUND:
            logger.warning(f"Use of keycloak authentication is scheduled to be deprecated in a later release")
            sig_key = PyJWKClient(f"{KEYCLOAK_REALM_BASE}/certs").get_signing_key_from_jwt(token)
            return decode(
                token,
                key=sig_key,
                options={"verify_signature": True, "verify_aud": False, "verify_exp": True},
            )
        else:
            logger.error(f"KEYCLOAK_URL is not configured")
            raise HTTPException(status_code=500, detail="KEYCLOAK_URL is not configured")
    except PyJWKClientConnectionError as e:
        logger.error(f"Failed to fetch JWKS: {repr(e)}")
        raise HTTPException(status_code=503, detail="JWKS unavailable") from e
    except PyJWKClientError:
        # e.g. no signing key matches the token's kid
        raise HTTPException(status_code=401, detail="Not authenticated") from None
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Not authenticated") from None



def valid_analysis_token(auth_creds: Annotated[HTTPAuthorizationCredentials, Depends(AUTHUP_SCHEME)]) -> dict:
    """FastAPI dependency that validates an Authup client bearer token.

    The token is checked against Authup's signing keys via the cached
    :data:`~src.api.constants.AUTHUP_CLIENT`; signature and expiration are
    verified (``exp`` is required), audience validation is intentionally
    disabled. The token must be an Authup *client* token
    (``sub_kind == "client"``), as minted via the client_credentials grant, e.g.
    the ``AUTHUP_TOKEN`` of an analysis or a token of the node's Hub client;
    Authup user tokens are rejected.

    Args:
        auth_creds: The bearer credentials extracted by
            :data:`~src.api.constants.AUTHUP_SCHEME`.

    Returns:
        The decoded JWT claims as a dictionary.

    Raises:
        HTTPException: 401 if the token is malformed, invalid, expired, lacks
            ``exp``, cannot be matched to/verified against Authup's signing keys
            or is not a client token; 503 if Authup's JWKS cannot be fetched; 500
            if ``AUTHUP_JWKS_URL`` is not configured.
    """
    if AUTHUP_CLIENT is None:
        logger.error(f"AUTHUP_JWKS_URL is not configured")
        raise HTTPException(status_code=500, detail="AUTHUP_JWKS_URL is not configured")
    try:
        credentials = auth_creds.credentials
        sig_key = AUTHUP_CLIENT.get_signing_key_from_jwt(credentials)
        claims = decode(
            credentials,
            key=sig_key,
            options={
                "verify_signature": True,
                "verify_aud": False,
                "verify_exp": True,
                "require": ["exp"],
            },
        )
        if claims.get("sub_kind") != "client":
            raise HTTPException(status_code=401, detail="Not authenticated")
        return claims
    except PyJWKClientConnectionError as e:
        logger.error(f"Failed to fetch AUTHUP JWKS: {repr(e)}")
        raise HTTPException(status_code=503, detail="AUTHUP JWKS unavailable") from e
    except PyJWKClientError:
        # e.g. no signing key matches the token's kid
        raise HTTPException(status_code=401, detail="Not authenticated") from None
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Not authenticated") from None
