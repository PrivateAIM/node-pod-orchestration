import os
import requests
from kong_admin_client import Configuration, ApiClient, ConsumersApi, ACLsApi, KeyAuthsApi
from kong_admin_client.rest import ApiException
from kong_admin_client.models.create_consumer_request import CreateConsumerRequest
from kong_admin_client.models.create_acl_for_consumer_request import (
    CreateAclForConsumerRequest,
)
from kong_admin_client.models.create_key_auth_for_consumer_request import (
    CreateKeyAuthForConsumerRequest,
)


def create_tokens(analysis_id: str, project_id: str) -> dict[str, str]:
    return {'DATA_SOURCE_TOKEN': _get_kong_token(analysis_id, project_id),
            'KEYCLOAK_TOKEN': _get_keycloak_token(analysis_id, project_id)}




def _get_keycloak_token(analysis_id: str, project_id: str) -> str:
    #TODO create client in keycloak
    # curl -q -X POST -d "grant_type=client_credentials&client_id=service1&client_secret=9dd01665c2f3f02f93c32d03bd854569f03cd62f439ccf9f0861c141b9d6330e" http://keycloak-service:8080/realms/flame/protocol/openid-connect/token
    client = os.getenv('RESULT_CLIENT_ID')
    client_secret = os.getenv('RESULT_CLIENT_SECRET')

    keycloak_url = os.getenv('KEYCLOAK_URL') + "/realms/flame/protocol/openid-connect/token"

    data = {"grant_type": "client_credentials", "client_id": client, "client_secret": client_secret}

    # get token from keycloak like in the above curl command
    try:
        response = requests.post(keycloak_url, data=data)
        response.raise_for_status()
        return response.json()['access_token']
    except requests.exceptions.RequestException as e:
        print(e)
        return None


def _get_kong_token(analysis_id: str, project_id: str) -> str:
    kong_admin_url = "kong-kong-admin"
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
