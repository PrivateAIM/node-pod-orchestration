import os
import time
import asyncio
from httpx import AsyncClient
import requests
from kong_admin_client import Configuration, ApiClient, ConsumersApi, ACLsApi, KeyAuthsApi
from kong_admin_client.models.create_acl_for_consumer_request import (
    CreateAclForConsumerRequest,
)
from kong_admin_client.models.create_consumer_request import CreateConsumerRequest
from kong_admin_client.models.create_key_auth_for_consumer_request import (
    CreateKeyAuthForConsumerRequest,
)
from kong_admin_client.rest import ApiException

_KEYCLOAK_URL = os.getenv('KEYCLOAK_URL')
_KEYCLOAK_REALM = os.getenv('KEYCLOAK_REALM')

_hub_token_dict = {}


def get_hub_token() -> dict[str, str]:
    """
    Get the token for the hub
    :return: dict with the token and the expiration time
    """
    current_time = time.time()

    if not _hub_token_dict:
        _create_new_hub_token()
    elif _hub_token_dict["hub_token_expiration"] < current_time:
        _create_new_hub_token()  # TODO: _refresh_hub_token()

    return _hub_token_dict


def _create_new_hub_token() -> dict[str, str]:
    global _hub_token_dict
    hub_url_auth, robot_id, robot_secret = (os.getenv('HUB_URL_AUTH'),
                                            os.getenv('HUB_ROBOT_USER'),
                                            os.getenv('HUB_ROBOT_SECRET'))

    response = asyncio.run(AsyncClient(base_url=hub_url_auth, headers={"accept": "application/json"})
                           .post(url="/token",
                                 data={"id": robot_id, "secret": robot_secret},
                                 headers=[('Connection', 'close')]))
    response.raise_for_status()
    token = response.json()['access_token']
    time_of_expiration = response.json()['expires_in'] + time.time()
    _hub_token_dict = {"hub_token": token, "hub_token_expiration": time_of_expiration}
    print('Hub token:', _hub_token_dict)
    return _hub_token_dict


def _refresh_hub_token() -> dict[str, str]:
    global _hub_token_dict
    # TODO
    return {}


def create_analysis_tokens(deployment_name: str, analysis_id: str, project_id: str) -> dict[str, str]:
    tokens = {'DATA_SOURCE_TOKEN': _get_kong_token(deployment_name, project_id),
              'KEYCLOAK_TOKEN': _get_keycloak_token(analysis_id)}
    return tokens


def _get_keycloak_token(analysis_id: str) -> str:
    # curl -q -X POST -d "grant_type=client_credentials&client_id=service1&client_secret=9dd01665c2f3f02f93c32d03bd854569f03cd62f439ccf9f0861c141b9d6330e" http://flame-node-keycloak-service:8080/realms/flame/protocol/openid-connect/token

    client_secret = _get_keycloak_client_secret(analysis_id)

    keycloak_url = os.getenv('KEYCLOAK_URL') + "/realms/flame/protocol/openid-connect/token"
    data = {"grant_type": "client_credentials", "client_id": analysis_id, "client_secret": client_secret}

    # get token from keycloak like in the above curl command
    try:
        response = requests.post(keycloak_url, data=data)
        response.raise_for_status()
        print('Client token:', response.json()['access_token'])

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
    # curl -X GET -H "Authorization: Bearer $token" "http://flame-node-keycloak-service:8080/admin/realms/flame/clients?clientId=service3"
    url_get_client = f"{_KEYCLOAK_URL}/admin/realms/{_KEYCLOAK_REALM}/clients?clientId={analysis_id}"
    headers = {"Authorization": f"Bearer {admin_token}"}

    response = requests.get(url_get_client, headers=headers)
    response.raise_for_status()
    print('Client secret:', response.json()[0]['secret'])

    return response.json()[0]['secret']


def _get_keycloak_admin_token() -> str:
    # curl -d "grant_type=client_credentials" -d "client_id=admin_script" -d "client_secret=RSDuBMhVIGnqEzOZjTLDjT0q5jpw5Igz" "http://flame-node-keycloak-service:8080/realms/flame/protocol/openid-connect/token"
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
    print('Admin token:', response.json()['access_token'])

    return response.json()['access_token']


def _keycloak_client_exists(analysis_id: str, admin_token: str) -> bool:
    url_get_client = f"{_KEYCLOAK_URL}/admin/realms/{_KEYCLOAK_REALM}/clients?clientId={analysis_id}"
    headers = {"Authorization": f"Bearer {admin_token}"}

    response = requests.get(url_get_client, headers=headers)
    response.raise_for_status()
    print('Does client already exist:', bool(response.json()))

    return bool(response.json())


def _create_keycloak_client(admin_token: str, analysis_id: str) -> None:
    # curl -X POST -d '{ "clientId": "service3" }' -H "Content-Type:application/json" -H "Authorization: Bearer $token" "http://flame-node-keycloak-service:8080/admin/realms/flame/clients"
    url_create_client = f"{_KEYCLOAK_URL}/admin/realms/{_KEYCLOAK_REALM}/clients"
    headers = {"Authorization": f"Bearer {admin_token}", "Content-Type": "application/json"}
    client_data = {"clientId": analysis_id, "serviceAccountsEnabled": "true"}

    response = requests.post(url_create_client, headers=headers, json=client_data)
    response.raise_for_status()


def delete_keycloak_client(analysis_id: str) -> None:
    admin_token = _get_keycloak_admin_token()

    # get client uuid
    url_get_client = f"{_KEYCLOAK_URL}/admin/realms/{_KEYCLOAK_REALM}/clients?clientId={analysis_id}"
    headers = {"Authorization": f"Bearer {admin_token}"}

    response = requests.get(url_get_client, headers=headers)
    response.raise_for_status()
    try:
        uuid = response.json()[0]['id']
    except (KeyError, IndexError):
        print('Client not found')
        return

    # curl -X DELETE -H "Authorization: Bearer $token" "http://flame-node-keycloak-service:8080/admin/realms/flame/clients/6094fabe-823f-4cce-a251-0782be5611e3"
    url_delete_client = f"{_KEYCLOAK_URL}/admin/realms/{_KEYCLOAK_REALM}/clients/{uuid}"
    headers = {"Authorization": f"Bearer {admin_token}"}

    response = requests.delete(url_delete_client, headers=headers)
    response.raise_for_status()


def _get_kong_token(analysis_id: str, project_id: str) -> str:
    kong_admin_url = "flame-node-kong-admin"
    configuration = Configuration(host=kong_admin_url)

    # Add consumer
    try:
        with ApiClient(configuration) as api_client:
            api_instance = ConsumersApi(api_client)
            api_response = api_instance.create_consumer(
                CreateConsumerRequest(
                    username=analysis_id,
                    custom_id=analysis_id,
                    tags=[project_id],
                )
            )
            print(f"Consumer added, id: {api_response.id}")
            consumer_id = api_response.id
    except ApiException as e:
        print(f"Exception when calling ConsumersApi->create_consumer: {e}\n")
    except Exception as e:
        print(f"Exception: {e}\n")

    # Configure acl plugin for consumer
    try:
        with ApiClient(configuration) as api_client:
            api_instance = ACLsApi(api_client)
            api_response = api_instance.create_acl_for_consumer(
                consumer_id,
                CreateAclForConsumerRequest(
                    group=project_id,
                    tags=[project_id],
                ),
            )
            print(
                f"ACL plugin configured for consumer, group: {api_response.group}"
            )
    except ApiException as e:
        print(f"Exception when calling ACLsApi->create_acl_for_consumer: {e}\n")
    except Exception as e:
        print(f"Exception: {e}\n")

    # Configure key-auth plugin for consumer
    try:
        with ApiClient(configuration) as api_client:
            api_instance = KeyAuthsApi(api_client)
            api_response = api_instance.create_key_auth_for_consumer(
                consumer_id,
                CreateKeyAuthForConsumerRequest(
                    tags=[project_id],
                ),
            )
            print(
                f"Key authentication plugin configured for consumer, api_key: {api_response.key}"
            )
            return api_response.key
    except ApiException as e:
        print(
            f"Exception when calling KeyAuthsApi->create_key_auth_for_consumer: {e}\n"
        )
    except Exception as e:
        print(f"Exception: {e}\n")
