from typing import Literal, Optional, Union

from kubernetes import client


def get_k8s_resource_names(resource_type: str,
                           selector_type: Optional[Literal['label', 'field']] = None,
                           selector_arg: Optional[str] = None,
                           manual_name_selector: Optional[str] = None,
                           namespace: str = "default") -> Optional[Union[str, list[str]]]:
    if resource_type not in ['deployment', 'pod', 'service', 'networkpolicy', 'configmap']:
        raise ValueError("For k8s resource search: resource_type must be one of 'deployment', 'pod', 'service', "
                         "'networkpolicy', or 'configmap'")
    if (selector_type is not None) and (selector_type not in ['label', 'field']):
        raise ValueError("For k8s resource search: selector_type must be either 'label' or 'field'")
    if (selector_type is not None) and (selector_arg is None):
        raise ValueError("For k8s resource search: if given a resource_type, selector_arg must not be None")

    kwargs = {'namespace': namespace}
    if selector_type:
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
        raise ValueError(f"Uncaptured resource type discovered! Message the Devs... (found={resource_type})")

    if not resources:
        return None
    else:
        resource_names = [resource.metadata.name for resource in resources.items]
        if len(resource_names) > 1:
            if manual_name_selector is not None:
                resource_names = [name for name in resource_names if manual_name_selector in name]
                return resource_names if len(resource_names) > 1 else resource_names[0]
            else:
                return resource_names
        else:
            if len(resource_names) == 1:
                return resource_names[0]
            else:
                return None


def get_all_analysis_deployment_names(namespace: str = 'default') -> list[str]:
    """
    Get all analysis deployments in the specified namespace.
    :param namespace: The namespace to search for deployments.
    :return: A list of deployment names.
    """
    analysis_deployment_names = get_k8s_resource_names('deployment',
                                                       'label',
                                                       'component=flame-analysis',
                                                       namespace=namespace)
    analysis_deployment_names = [analysis_deployment_names] if type(analysis_deployment_names) == str \
        else analysis_deployment_names
    return analysis_deployment_names


def get_current_namespace() -> str:
    namespace_file = '/var/run/secrets/kubernetes.io/serviceaccount/namespace'
    try:
        with open(namespace_file, 'r') as file:
            return file.read().strip()
    # Handle the case where the file is not found
    except FileNotFoundError:
        # Fallback to a default namespace if the file is not found
        return 'default'
