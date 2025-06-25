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


def split_logs(analysis_logs: dict[str, list[str]]) -> dict[str, str]:
    """
    Splits and collects raw logs according to line suffixes into a dictionary using the suffixes as keys
    :param analysis_logs:
    :return:
    """
    log_dict = {}

    is_multi_deployment_analysis = len(analysis_logs) > 1
    for deployment_name, raw_logs in analysis_logs.items():
        is_multi_pod_deployment = len(raw_logs) > 1
        for i, raw_log in enumerate(raw_logs):
            log_splits = [tuple(line.rsplit('!suff!', 1)) for line in raw_log.split('\n') if line]
            for line, suffix in log_splits:
                log = []
                if is_multi_deployment_analysis:
                    log.append(deployment_name)
                if is_multi_pod_deployment:
                    log.append(f"pod_{i + 1}")
                log.append(line)
                log = ' - '.join(log) + '\n'
                if suffix not in log_dict.keys():
                    log_dict[suffix] = log
                else:
                    log_dict[suffix] += log
    return log_dict


async def call_sources(client, project_id) -> list[dict[str, str]]:
    response = await client.get(f"/kong/datastore?project_id={project_id}")
    response.raise_for_status()
    return response.json()
