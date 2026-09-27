"""Analysis auth-token minting via the FLAME Hub and the global Authup instance.

Fetches an analysis's OAuth2 client credentials from the Hub Core API (the
Hub owns the Authup client for the analysis's whole lifecycle) and exchanges
them for an access token, then assembles the token environment injected into
an analysis container.
"""

import os
from typing import Optional

from httpx2 import ConnectError, ConnectTimeout, HTTPError, HTTPStatusError

import flame_hub

from src.utils.hub_client import init_hub_client, init_proxied_http_client
from src.utils.other import extract_hub_envs
from src.utils.po_logging import get_logger


logger = get_logger()

_AUTHUP_TOKEN_URL = os.getenv("AUTHUP_TOKEN_URL")


class AnalysisTokenError(RuntimeError):
    """Raised when no Authup access token could be minted for an analysis."""


def create_analysis_tokens(kong_token: str, analysis_id: str) -> dict[str, str]:
    """Assemble the token env dict injected into the analysis container.

    Args:
        kong_token: Opaque Kong token minted for the analysis by the node.
        analysis_id: Analysis id used to look up its Hub-managed Authup client.

    Returns:
        Dict with ``DATA_SOURCE_TOKEN`` (the Kong token) and ``AUTHUP_TOKEN``
        (a freshly minted access token for the analysis's Authup client).
        ``AUTHUP_TOKEN`` is ``None`` if minting failed; callers deploying an
        analysis must treat that as fatal (see ``Analysis.start``).
    """
    tokens = {
        "DATA_SOURCE_TOKEN": kong_token,
        "AUTHUP_TOKEN": get_analysis_token(analysis_id),
    }
    return tokens


def get_analysis_token(analysis_id: str) -> Optional[str]:
    """Obtain a client-credentials access token for an analysis's Authup client.

    Rotates and fetches the analysis's OAuth2 client credentials from the Hub
    Core API (``update_analysis_client_credentials`` with ``secret=None``
    always returns a fresh, plaintext secret), then exchanges them for an
    access token against the global Authup instance's token endpoint, reached
    through the node's Hub proxy and CA settings.

    Args:
        analysis_id: Analysis id, used as the Hub Core API path parameter.

    Returns:
        The access token, or ``None`` on failure.
    """
    client_id, client_secret, hub_url_core, hub_auth, _, http_proxy, https_proxy = (
        extract_hub_envs()
    )
    hub_client = init_hub_client(
        client_id, client_secret, hub_url_core, hub_auth, http_proxy, https_proxy
    )
    if hub_client is None:
        logger.error(
            "Failed to initialize hub client. Cannot retrieve analysis client credentials."
        )
        return None

    try:
        credentials = hub_client.update_analysis_client_credentials(
            analysis_id, secret=None
        )
    except (
        HTTPStatusError,
        ConnectError,
        ConnectTimeout,
        flame_hub._exceptions.HubAPIError,
        AttributeError,
    ) as e:
        logger.error(
            f"Failed to rotate/retrieve analysis client credentials from Hub for {analysis_id}: {repr(e)}"
        )
        return None

    data = {
        "grant_type": "client_credentials",
        "client_id": str(credentials.id),
        "client_secret": credentials.secret,
    }

    if not _AUTHUP_TOKEN_URL:
        logger.error("AUTHUP_TOKEN_URL is not configured. Cannot retrieve analysis token.")
        return None

    # Authup lives next to the Hub, so reach it through the same proxy/CA
    # settings as the Hub client.
    try:
        with init_proxied_http_client() as http_client:
            response = http_client.post(_AUTHUP_TOKEN_URL, data=data)
            response.raise_for_status()
            return response.json()["access_token"]
    except (HTTPError, ValueError, KeyError) as e:
        logger.error(f"Failed to retrieve Authup token for analysis {analysis_id}: {repr(e)}")
        return None
