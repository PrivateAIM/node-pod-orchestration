import os
import requests
from typing import Optional

from src.utils.po_logging import get_logger


logger = get_logger()

_KEYCLOAK_URL = os.getenv('KEYCLOAK_URL')
_KEYCLOAK_REALM = os.getenv('KEYCLOAK_REALM')


def create_analysis_tokens(kong_token: str, analysis_id: str) -> dict[str, str]:
    """Assemble the token env dict injected into the analysis container.

    Args:
        kong_token: Opaque Kong token minted for the analysis by the node.
        analysis_id: Analysis id used as the Keycloak client id.

    Returns:
        Dict with ``DATA_SOURCE_TOKEN`` (the Kong token) and
        ``KEYCLOAK_TOKEN`` (a freshly minted service-account token).
    """
    tokens = {'DATA_SOURCE_TOKEN': kong_token,
              'KEYCLOAK_TOKEN': get_keycloak_token(analysis_id)}
    return tokens


def get_keycloak_token(analysis_id: str) -> Optional[str]:
    """Obtain a client-credentials access token for an analysis's Keycloak client.

    Creates the Keycloak client on demand if it does not already exist.

    Args:
        analysis_id: Analysis id used as the Keycloak client id.

    Returns:
        The access token, or ``None`` on HTTP failure.
    """
    client_secret = _get_keycloak_client_secret(analysis_id)

    keycloak_url = f"{_KEYCLOAK_URL}/realms/flame/protocol/openid-connect/token"
    data = {'grant_type': 'client_credentials',
            'client_id': analysis_id,
            'client_secret': client_secret}

    # get token from keycloak like in the above curl command
    try:
        response = requests.post(keycloak_url, data=data)
        response.raise_for_status()

        return response.json()['access_token']
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to retrieve keycloak token: {repr(e)}")
        return None


def _get_keycloak_client_secret(analysis_id: str) -> str:
    """Return the client secret for an analysis, creating the client if needed."""
    admin_token = _get_keycloak_admin_token()

    if not _keycloak_client_exists(analysis_id, admin_token):
        # create client
        _create_keycloak_client(admin_token, analysis_id)

    # get client secret
    url_get_client = f"{_KEYCLOAK_URL}/admin/realms/{_KEYCLOAK_REALM}/clients?clientId={analysis_id}"
    headers = {'Authorization': f"Bearer {admin_token}"}

    response = requests.get(url_get_client, headers=headers)
    response.raise_for_status()

    return response.json()[0]['secret']


def _get_keycloak_admin_token() -> str:
    """Mint an admin access token using the ``RESULT_CLIENT_*`` service account."""
    keycloak_admin_client_id = os.getenv('RESULT_CLIENT_ID')
    keycloak_admin_client_secret = os.getenv('RESULT_CLIENT_SECRET')

    # get admin token
    url_admin_access_token = f"{_KEYCLOAK_URL}/realms/{_KEYCLOAK_REALM}/protocol/openid-connect/token"
    data = {
        'grant_type': 'client_credentials',
        'client_id': keycloak_admin_client_id,
        'client_secret': keycloak_admin_client_secret
    }
    response = requests.post(url_admin_access_token, data=data)
    response.raise_for_status()

    return response.json()['access_token']


def _keycloak_client_exists(analysis_id: str, admin_token: str) -> bool:
    """Return True if a Keycloak client with the given ``analysis_id`` exists."""
    url_get_client = f"{_KEYCLOAK_URL}/admin/realms/{_KEYCLOAK_REALM}/clients?clientId={analysis_id}"
    headers = {'Authorization': f"Bearer {admin_token}"}

    response = requests.get(url_get_client, headers=headers)
    response.raise_for_status()

    return bool(response.json())


def _create_keycloak_client(admin_token: str, analysis_id: str) -> None:
    """Create a service-account Keycloak client named ``flame-{analysis_id}``."""
    url_create_client = f"{_KEYCLOAK_URL}/admin/realms/{_KEYCLOAK_REALM}/clients"
    headers = {'Authorization': f"Bearer {admin_token}",
               'Content-Type': "application/json"}
    client_data = {'clientId': f"{analysis_id}",
                   'name': f"flame-{analysis_id}",
                   'serviceAccountsEnabled': 'true'}

    response = requests.post(url_create_client, headers=headers, json=client_data)
    response.raise_for_status()

def _get_all_keycloak_clients() -> list[dict]:
    """Return every Keycloak client in the configured realm as raw JSON dicts."""
    admin_token = _get_keycloak_admin_token()
    url_get_clients = f"{_KEYCLOAK_URL}/admin/realms/{_KEYCLOAK_REALM}/clients"
    headers = {'Authorization': f"Bearer {admin_token}"}

    response = requests.get(url_get_clients, headers=headers)
    response.raise_for_status()

    return response.json()

def delete_keycloak_client(analysis_id: str) -> None:
    """Delete the Keycloak client associated with an analysis.

    Logs and returns silently if the client cannot be located.
    """
    admin_token = _get_keycloak_admin_token()

    # get client uuid
    url_get_client = f"{_KEYCLOAK_URL}/admin/realms/{_KEYCLOAK_REALM}/clients?clientId={analysis_id}"
    headers = {'Authorization': f"Bearer {admin_token}"}

    response = requests.get(url_get_client, headers=headers)
    response.raise_for_status()
    try:
        uuid = response.json()[0]['id']
    except (KeyError, IndexError) as e:
        logger.error(f"Failed to retrieve keycloak client: {repr(e)}")
        return

    url_delete_client = f"{_KEYCLOAK_URL}/admin/realms/{_KEYCLOAK_REALM}/clients/{uuid}"
    headers = {'Authorization': f"Bearer {admin_token}"}

    response = requests.delete(url_delete_client, headers=headers)
    response.raise_for_status()
