import os
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2AuthorizationCodeBearer

from jwt import PyJWKClient
import jwt
from typing import Annotated


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
        return jwt.decode(token,
                          key=sig_key,
                          options={'verify_signature': True, 'verify_aud': False, 'verify_exp': True})
    except jwt.exceptions.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Not authenticated")
