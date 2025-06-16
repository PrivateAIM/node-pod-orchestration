from httpx import AsyncClient
import asyncio


def _add_slash(string: str) -> str:
    return string + ('' if string.endswith('/') else '/')


def get_project_data_source(keycloak_token, project_id, hub_adapter_service_name, namespace="default") -> dict:
    """
    Get data sources for a project from the node hub adapter service using the keycloak token

    :param keycloak_token:
    :param project_id:
    :param hub_adapter_service_name:
    :param namespace:
    :return:
    """
    client = AsyncClient(base_url=f"http://{hub_adapter_service_name}:5000",
                         headers={"Authorization": f"Bearer {keycloak_token}",
                                  "accept": "application/json"})
    return asyncio.run(call_sources(client, project_id))


def get_element_by_substring(data: list[str], substring: str) -> str:  # TODO: Better solution for this
    """
    Get the smallest element in a list that contains a substring
    :param data:
    :param substring:
    :return:
    """
    matching_elements = [element for element in data if (substring in element) and ('-db-' not in element)]  # TODO: '-db-'- hack for messagebroker
    return min(matching_elements, key=len) if matching_elements else None


def split_logs(logs: str) -> dict:
    """

    :param logs:
    :return:
    """
    logs = [tuple(line.rsplit('!suff!', 1)) for line in logs.split('\n') if line]
    pass


async def call_sources(client, project_id) -> list[dict[str, str]]:
    response = await client.get(f"/kong/datastore?project_id={project_id}")
    response.raise_for_status()
    return response.json()
