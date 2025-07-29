import os
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2AuthorizationCodeBearer

from jwt import PyJWKClient
import jwt
from typing import Annotated

oauth2_scheme = OAuth2AuthorizationCodeBearer(
    tokenUrl=os.getenv("KEYCLOAK_URL") + "/realms/flame/protocol/openid-connect/token",
    authorizationUrl=os.getenv("KEYCLOAK_URL") + "/realms/flame/protocol/openid-connect/auth",
    refreshUrl=os.getenv("KEYCLOAK_URL") + "/realms/flame/protocol/openid-connect/token",
)


async def valid_access_token(token: Annotated[str, Depends(oauth2_scheme)]) -> dict:
    url = os.getenv("KEYCLOAK_URL") + "/realms/flame/protocol/openid-connect/certs"
    jwks_client = PyJWKClient(url)

    try:
        sig_key = jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(token,
                          key=sig_key,
                          options={"verify_signature": True, "verify_aud": False, "exp": True})
    except jwt.exceptions.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Not authenticated")
