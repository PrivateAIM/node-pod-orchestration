from httpx import AsyncClient
import asyncio


def resource_name_to_analysis(deployment_name: str, max_r_split: int = 1) -> str:
    return deployment_name.split("analysis-")[-1].rsplit('-', max_r_split)[0]


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
                         headers={'Authorization': f"Bearer {keycloak_token}",
                                  'accept': "application/json"})
    return asyncio.run(call_sources(client, project_id))


async def call_sources(client, project_id) -> list[dict[str, str]]:
    response = await client.get(f"/kong/datastore?project_id={project_id}")
    response.raise_for_status()
    return response.json()
