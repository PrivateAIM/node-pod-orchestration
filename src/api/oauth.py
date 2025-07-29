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
        data = jwt.decode(token,
                          sig_key.key,
                          algorithms=["RS256"],
                          audience="api",
                          options={"verify_aud": True})
        return data
    except jwt.exceptions.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Not authenticated")
