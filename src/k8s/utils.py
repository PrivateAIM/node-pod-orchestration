import time
from typing import Literal, Optional, Union

from kubernetes import config, client

from src.utils.po_logging import get_logger


logger = get_logger()


def load_cluster_config():
    config.load_incluster_config()


def get_current_namespace() -> str:
    namespace_file = '/var/run/secrets/kubernetes.io/serviceaccount/namespace'
    try:
        with open(namespace_file, 'r') as file:
            return file.read().strip()
    # Handle the case where the file is not found
    except FileNotFoundError:
        # Fallback to a default namespace if the file is not found
        return 'default'


def find_k8s_resources(resource_type: str,
                       selector_type: Optional[Literal['label', 'field']] = None,
                       selector_arg: Optional[str] = None,
                       manual_name_selector: Optional[str] = None,
                       namespace: str = "default") -> list[Optional[str]]:
    if resource_type not in ['deployment', 'pod', 'service', 'networkpolicy', 'configmap', 'job']:
        raise ValueError("For k8s resource search: resource_type must be one of 'deployment', 'pod', 'service', "
                         "'networkpolicy', 'configmap', or 'job")
    if (selector_type is not None) and (selector_type not in ['label', 'field']):
        raise ValueError("For k8s resource search: selector_type must be either 'label' or 'field'")
    if (selector_type is not None) and (selector_arg is None):
        raise ValueError("For k8s resource search: if given a resource_type, selector_arg must not be None")

    kwargs = {'namespace': namespace}
    if (selector_type is not None) and isinstance(selector_arg, str):
        kwargs[f'{selector_type}_selector'] = selector_arg

    if resource_type == 'deployment':
        resources = client.AppsV1Api().list_namespaced_deployment(**kwargs)
    elif resource_type == 'networkpolicy':
        resources = client.NetworkingV1Api().list_namespaced_network_policy(**kwargs)
    elif resource_type in ['pod', 'service', 'configmap']:
        core_client = client.CoreV1Api()
        if resource_type == 'pod':
            resources = core_client.list_namespaced_pod(**kwargs)
        elif resource_type == 'service':
            resources = core_client.list_namespaced_service(**kwargs)
        elif resource_type == 'configmap':
            resources = core_client.list_namespaced_config_map(**kwargs)
        else:
            raise RuntimeError("Undefined resource")
    elif resource_type == 'job':
        resources = client.BatchV1Api().list_namespaced_job(**kwargs)
    else:
        raise ValueError(f"Uncaptured resource type discovered! Message the Devs... (found={resource_type})")
    if not resources.items:
        return [None]
    resource_names = [resource.metadata.name for resource in resources.items]
    if manual_name_selector is not None:
        resource_names = [name for name in resource_names if manual_name_selector in name]
    return resource_names


def delete_k8s_resource(name: str, resource_type: str, namespace: str = 'default') -> None:
    """
    Deletes a Kubernetes resource by name and type.
    :param name: Name of the resource to delete.
    :param resource_type: Type of the resource (e.g., 'deployment', 'service', 'pod', 'configmap', 'job').
    :param namespace: Namespace in which the resource exists.
    """
    logger.action(f"Deleting resource: {name} of type {resource_type} in namespace {namespace} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    if resource_type == 'deployment':
        try:
            app_client = client.AppsV1Api()
            app_client.delete_namespaced_deployment(name=name, namespace=namespace, propagation_policy='Foreground')
        except client.exceptions.ApiException as e:
            if e.reason != 'Not Found':
                logger.error(f"Not Found {name} deployment")
    elif resource_type == 'service':
        try:
            core_client = client.CoreV1Api()
            core_client.delete_namespaced_service(name=name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.reason != 'Not Found':
                logger.error(f"Not Found {name} service")
    elif resource_type == 'pod':
        try:
            core_client = client.CoreV1Api()
            core_client.delete_namespaced_pod(name=name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.reason != 'Not Found':
                logger.error(f"Not Found {name} pod")
    elif resource_type == 'configmap':
        try:
            core_client = client.CoreV1Api()
            core_client.delete_namespaced_config_map(name=name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.reason != 'Not Found':
                logger.error(f"Not Found {name} configmap")
    elif resource_type == 'networkpolicy':
        try:
            network_client = client.NetworkingV1Api()
            network_client.delete_namespaced_network_policy(name=name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.reason != 'Not Found':
                logger.error(f"Not Found {name} networkpolicy")
    elif resource_type == 'job':
        try:
            batch_client = client.BatchV1Api()
            batch_client.delete_namespaced_job(name=name, namespace=namespace, propagation_policy='Foreground')
        except client.exceptions.ApiException as e:
            if e.reason != 'Not Found':
                logger.error(f"Not Found {name} job")
    else:
        raise ValueError(f"Unsupported resource type: {resource_type}")
