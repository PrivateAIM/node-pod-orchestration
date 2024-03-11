from kong_admin_client import Configuration, ApiClient, ConsumersApi, ACLsApi, KeyAuthsApi
from kong_admin_client.rest import ApiException
from kong_admin_client.models.create_consumer_request import CreateConsumerRequest
from kong_admin_client.models.create_acl_for_consumer_request import (
    CreateAclForConsumerRequest,
)
from kong_admin_client.models.create_key_auth_for_consumer_request import (
    CreateKeyAuthForConsumerRequest,
)


def create_tokens(analysis_id: str, project_id: str = "project1") -> dict[str, str]:
    return {'DATA_SOURCE_TOKEN': _get_kong_token(analysis_id, project_id),
            'MESSAGE_BROKER_TOKEN': "def567"}


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
