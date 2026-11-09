"""Bearer token validation for the Pod Orchestration API.

Every protected route depends on :func:`valid_access_token`. Which identity
provider it verifies against is decided at import time in
:mod:`src.api.constants`:

* Authup (``AUTHUP_JWKS_URL`` set): the token is verified against the global
  Authup instance's JWKS and must be an Authup *client* token
  (``sub_kind == "client"``).
* Keycloak (fallback): the token is verified against the local Keycloak
  realm's JWKS (``KEYCLOAK_URL`` / ``KEYCLOAK_REALM``).
"""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from jwt import PyJWKClient, decode
from jwt.exceptions import InvalidTokenError, PyJWKClientError, PyJWKClientConnectionError
from typing import Annotated, Union

from src.api.constants import AUTHUP_URL_FOUND, AUTHUP_JWKS_CLIENT, BEARER_SCHEME, KEYCLOAK_REALM_BASE, OAUTH2_SCHEME
from src.utils.po_logging import get_logger

logger = get_logger()


def valid_access_token(
        token: Union[Annotated[str, Depends(OAUTH2_SCHEME)], Annotated[HTTPAuthorizationCredentials, Depends(BEARER_SCHEME)]]
) -> dict:
    """FastAPI dependency that validates the request's bearer token.

    With Authup configured (:data:`~src.api.constants.AUTHUP_URL_FOUND`), the
    token is checked against Authup's signing keys via the cached
    :data:`~src.api.constants.AUTHUP_JWKS_CLIENT`; the signature and
    expiration are verified (``exp`` is required) and the token must be an
    Authup client token (``sub_kind == "client"``), as minted via the
    client_credentials grant. Without Authup, the token is checked against
    the local Keycloak realm's ``/certs`` endpoint (signature and expiration).
    Audience validation is intentionally disabled in both cases.

    Args:
        token: The bearer token. With Authup, the
            :class:`~fastapi.security.HTTPAuthorizationCredentials` extracted
            by :data:`~src.api.constants.BEARER_SCHEME`; with Keycloak, the
            raw token string extracted by
            :data:`~src.api.constants.OAUTH2_SCHEME`.

    Returns:
        The decoded JWT claims as a dictionary.

    Raises:
        HTTPException: 401 if the token is invalid, expired, cannot be
            matched to/verified against the provider's signing keys or (Authup
            only) lacks ``exp`` or is not a client token; 503 if Authup's JWKS
            cannot be fetched; 500 if ``AUTHUP_JWKS_URL`` is set but empty.
    """
    if AUTHUP_URL_FOUND:
        credentials = token.credentials
        if AUTHUP_JWKS_CLIENT is None:
            raise HTTPException(status_code=500, detail="AUTHUP_JWKS_URL is not configured")
        try:
            sig_key = AUTHUP_JWKS_CLIENT.get_signing_key_from_jwt(credentials)
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
        except PyJWKClientConnectionError as e:
            logger.error(f"Failed to fetch Authup JWKS: {repr(e)}")
            raise HTTPException(status_code=503, detail="Authup JWKS unavailable") from e
        except PyJWKClientError:
            # e.g. no signing key matches the token's kid
            raise HTTPException(status_code=401, detail="Not authenticated") from None
        except InvalidTokenError:
            raise HTTPException(status_code=401, detail="Not authenticated") from None

        if claims.get("sub_kind") != "client":
            raise HTTPException(status_code=401, detail="Not authenticated")
        return claims
    else:
        try:
            sig_key = PyJWKClient(f"{KEYCLOAK_REALM_BASE}/certs").get_signing_key_from_jwt(token)
            return decode(
                token,
                key=sig_key,
                options={"verify_signature": True, "verify_aud": False, "verify_exp": True},
            )
        except InvalidTokenError:
            raise HTTPException(status_code=401, detail="Not authenticated")
