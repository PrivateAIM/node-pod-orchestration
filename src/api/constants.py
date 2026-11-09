"""Authentication backend selection and shared auth objects for the API.

The identity provider is chosen once at import time: if ``AUTHUP_JWKS_URL``
is set (:data:`AUTHUP_URL_FOUND`), bearer tokens are verified against the
global Authup instance's JWKS; otherwise the module falls back to the node's
local Keycloak realm (``KEYCLOAK_URL`` / ``KEYCLOAK_REALM``).

Exactly one set of objects is populated, the other is set to ``None``:

* Authup: :data:`AUTHUP_JWKS_CLIENT` and :data:`BEARER_SCHEME`.
* Keycloak: :data:`KEYCLOAK_REALM_BASE` and :data:`OAUTH2_SCHEME`.
"""

import os
from typing import Any

from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError
from httpx2 import HTTPError
from fastapi.security import HTTPBearer, OAuth2AuthorizationCodeBearer

from src.utils.hub_client import init_proxied_http_client


AUTHUP_URL_FOUND = "AUTHUP_JWKS_URL" in os.environ  # True -> verify against global Authup, False -> local Keycloak

if AUTHUP_URL_FOUND:
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
    # requests, instead of fetching Authup's JWKS on every call. None if the
    # variable is set but empty.
    AUTHUP_JWKS_CLIENT = _ProxiedPyJWKClient(_AUTHUP_JWKS_URL) if _AUTHUP_JWKS_URL else None
    BEARER_SCHEME = HTTPBearer()  # Extracts the raw bearer token from the Authorization header

    KEYCLOAK_REALM_BASE, OAUTH2_SCHEME = (None, None)
else:
    _KEYCLOAK_URL = os.getenv("KEYCLOAK_URL")
    # Base URL of the realm's OpenID Connect endpoints (token, auth, certs)
    KEYCLOAK_REALM_BASE = f"{_KEYCLOAK_URL}/realms/{os.getenv('KEYCLOAK_REALM', 'flame')}/protocol/openid-connect"
    # Authorization code flow against the local Keycloak realm (also used by the OpenAPI docs)
    OAUTH2_SCHEME = OAuth2AuthorizationCodeBearer(
        tokenUrl=f"{KEYCLOAK_REALM_BASE}/token",
        authorizationUrl=f"{KEYCLOAK_REALM_BASE}/auth",
        refreshUrl=f"{KEYCLOAK_REALM_BASE}/token",
    )

    AUTHUP_JWKS_CLIENT, BEARER_SCHEME = (None, None)
