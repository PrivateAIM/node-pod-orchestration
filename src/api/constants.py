"""Authentication backend selection and shared auth objects for the API.

The backend for the regular API routes is chosen once at import time:

* Authup (default): if ``KEYCLOAK_URL`` is unset or empty
  (:data:`KEYCLOAK_URL_FOUND` is ``False``), every protected route is
  verified against the global Authup instance's JWKS (``AUTHUP_JWKS_URL``).
* Keycloak (deprecated): if ``KEYCLOAK_URL`` is set and non-empty, the regular
  routes are verified against the local Keycloak realm
  (``KEYCLOAK_URL`` / ``KEYCLOAK_REALM``), while ``POST /po/stream_logs``
  still uses Authup, as analysis tokens are always minted by Authup.

Module-level objects used by :mod:`src.api.oauth` and :mod:`src.api.api`:

* :data:`AUTHUP_CLIENT`: cached :class:`_ProxiedPyJWKClient` for Authup's
  JWKS, or ``None`` if ``AUTHUP_JWKS_URL`` is unset or empty. Always built,
  independent of the selected backend.
* :data:`AUTHUP_SCHEME`: ``HTTPBearer`` yielding
  ``HTTPAuthorizationCredentials``; always built.
* :data:`KEYCLOAK_REALM_BASE`: base URL of the realm's OpenID Connect
  endpoints (``.../protocol/openid-connect``); ``None`` in Authup mode.
* :data:`KEYCLOAK_SCHEME`: ``OAuth2AuthorizationCodeBearer`` yielding the raw
  token string (also drives the OpenAPI docs' login flow); ``None`` in Authup
  mode.
"""

import os
from typing import Any

from jwt import PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError
from httpx2 import HTTPError
from fastapi.security import HTTPBearer, OAuth2AuthorizationCodeBearer

from src.utils.hub_client import init_proxied_http_client


KEYCLOAK_URL_FOUND = "KEYCLOAK_URL" in os.environ and bool(os.getenv("KEYCLOAK_URL")) # False -> strictly verify against global Authup, True -> allow local Keycloak

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
AUTHUP_CLIENT = _ProxiedPyJWKClient(_AUTHUP_JWKS_URL) if _AUTHUP_JWKS_URL else None
AUTHUP_SCHEME = HTTPBearer()  # Extracts the raw bearer token from the Authorization header


if KEYCLOAK_URL_FOUND:
    _KEYCLOAK_URL = os.getenv("KEYCLOAK_URL")
    # Base URL of the realm's OpenID Connect endpoints (token, auth, certs)
    KEYCLOAK_REALM_BASE = f"{_KEYCLOAK_URL}/realms/{os.getenv('KEYCLOAK_REALM', 'flame')}/protocol/openid-connect"
    # Authorization code flow against the local Keycloak realm (also used by the OpenAPI docs)
    KEYCLOAK_SCHEME = OAuth2AuthorizationCodeBearer(
        tokenUrl=f"{KEYCLOAK_REALM_BASE}/token",
        authorizationUrl=f"{KEYCLOAK_REALM_BASE}/auth",
        refreshUrl=f"{KEYCLOAK_REALM_BASE}/token",
    )
else:
    KEYCLOAK_REALM_BASE, KEYCLOAK_SCHEME = None, None
