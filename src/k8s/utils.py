from typing import Literal

from kubernetes import client
from src.utils.other import get_element_by_substring


def get_cluster_name_by_substring(substring: str,
                                  resource_type: Literal['pod', 'service'],
                                  namespace: str = 'default') -> str:
    if resource_type == 'pod':
        cluster_names = get_pod_names(namespace)
    elif resource_type == 'service':
        cluster_names = get_service_names(namespace)
    else:
        raise ValueError("resource_type must be 'pod' or 'service'")
    return get_element_by_substring(cluster_names, substring)


def get_service_names(namespace: str = 'default') -> list[str]:
    core_client = client.CoreV1Api()
    return [service.metadata.name for service in core_client.list_namespaced_service(namespace=namespace).items]


def get_pod_names(namespace: str = 'default') -> list[str]:
    core_client = client.CoreV1Api()
    return [pod.metadata.name for pod in core_client.list_namespaced_pod(namespace=namespace).items]


def get_current_namespace() -> str:
    namespace_file = '/var/run/secrets/kubernetes.io/serviceaccount/namespace'
    try:
        with open(namespace_file, 'r') as file:
            return file.read().strip()
    # Handle the case where the file is not found
    except FileNotFoundError:
        # Fallback to a default namespace if the file is not found
        return 'default'
