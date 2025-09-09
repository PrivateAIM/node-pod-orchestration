import os
import requests
from typing import Optional

_KEYCLOAK_URL = os.getenv('KEYCLOAK_URL')
_KEYCLOAK_REALM = os.getenv('KEYCLOAK_REALM')


def create_analysis_tokens(kong_token: str, analysis_id: str) -> dict[str, str]:
    tokens = {'DATA_SOURCE_TOKEN': kong_token,
              'KEYCLOAK_TOKEN': get_keycloak_token(analysis_id)}
    return tokens


def get_keycloak_token(analysis_id: str) -> Optional[str]:
    client_secret = _get_keycloak_client_secret(analysis_id)

    keycloak_url = f"{_KEYCLOAK_URL}/realms/flame/protocol/openid-connect/token"
    data = {"grant_type": "client_credentials", "client_id": analysis_id, "client_secret": client_secret}

    # get token from keycloak like in the above curl command
    try:
        response = requests.post(keycloak_url, data=data)
        response.raise_for_status()

        return response.json()['access_token']
    except requests.exceptions.RequestException as e:
        print(e)
        return None


def _get_keycloak_client_secret(analysis_id: str) -> str:
    admin_token = _get_keycloak_admin_token()

    if not _keycloak_client_exists(analysis_id, admin_token):
        # create client
        _create_keycloak_client(admin_token, analysis_id)

    # get client secret
    url_get_client = f"{_KEYCLOAK_URL}/admin/realms/{_KEYCLOAK_REALM}/clients?clientId={analysis_id}"
    headers = {"Authorization": f"Bearer {admin_token}"}

    response = requests.get(url_get_client, headers=headers)
    response.raise_for_status()

    return response.json()[0]['secret']


def _get_keycloak_admin_token() -> str:
    keycloak_admin_client_id = os.getenv('RESULT_CLIENT_ID')
    keycloak_admin_client_secret = os.getenv('RESULT_CLIENT_SECRET')

    # get admin token
    url_admin_access_token = f"{_KEYCLOAK_URL}/realms/{_KEYCLOAK_REALM}/protocol/openid-connect/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": keycloak_admin_client_id,
        "client_secret": keycloak_admin_client_secret
    }
    response = requests.post(url_admin_access_token, data=data)
    response.raise_for_status()

    return response.json()['access_token']


def _keycloak_client_exists(analysis_id: str, admin_token: str) -> bool:
    url_get_client = f"{_KEYCLOAK_URL}/admin/realms/{_KEYCLOAK_REALM}/clients?clientId={analysis_id}"
    headers = {"Authorization": f"Bearer {admin_token}"}

    response = requests.get(url_get_client, headers=headers)
    response.raise_for_status()

    return bool(response.json())


def _create_keycloak_client(admin_token: str, analysis_id: str) -> None:
    url_create_client = f"{_KEYCLOAK_URL}/admin/realms/{_KEYCLOAK_REALM}/clients"
    headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
    client_data = {"clientId": f"flame-{analysis_id}", "serviceAccountsEnabled": "true"}

    response = requests.post(url_create_client, headers=headers, json=client_data)
    response.raise_for_status()

def _get_all_keycloak_clients() -> list[dict]:
    admin_token = _get_keycloak_admin_token()
    url_get_clients = f"{_KEYCLOAK_URL}/admin/realms/{_KEYCLOAK_REALM}/clients"
    headers = {"Authorization": f"Bearer {admin_token}"}

    response = requests.get(url_get_clients, headers=headers)
    response.raise_for_status()

    return response.json()

def delete_keycloak_client(analysis_id: str) -> None:
    admin_token = _get_keycloak_admin_token()

    # get client uuid
    url_get_client = f"{_KEYCLOAK_URL}/admin/realms/{_KEYCLOAK_REALM}/clients?clientId=flame-{analysis_id}"
    headers = {"Authorization": f"Bearer {admin_token}"}

    response = requests.get(url_get_client, headers=headers)
    response.raise_for_status()
    try:
        uuid = response.json()[0]['id']
    except (KeyError, IndexError):
        print('keycloak Client not found')
        return

    url_delete_client = f"{_KEYCLOAK_URL}/admin/realms/{_KEYCLOAK_REALM}/clients/{uuid}"
    headers = {"Authorization": f"Bearer {admin_token}"}

    response = requests.delete(url_delete_client, headers=headers)
    response.raise_for_status()

