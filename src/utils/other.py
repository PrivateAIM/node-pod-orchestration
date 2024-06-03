import os
from httpx import AsyncClient
import asyncio

def create_image_address(analysis_id: str) -> str:
    return f"{_add_slash(os.getenv('HARBOR_URL'))}"\
           f"{_add_slash(os.getenv('NODE_NAME'))}"\
           f"{analysis_id}:latest"


def _add_slash(string: str) -> str:
    return string + ('' if string.endswith('/') else '/')


def get_project_data_source(keycloak_token, project_id) -> dict:
    """
    Get data sources for a project from the node hub adapter service using the keycloak token

    :param keycloak_token:
    :param project_id:
    :return:
    """
    client = AsyncClient(base_url="http://flame-node-hub-adapter-service:5000",
                                  headers={"Authorization": f"Bearer {keycloak_token}",
                                           "accept": "application/json"})
    return asyncio.run(call_sources(client, project_id))


async def call_sources(client, project_id) -> list[dict[str, str]]:
    response = await client.get(f"/kong/datastore/{project_id}")
    response.raise_for_status()
    return response.json()
