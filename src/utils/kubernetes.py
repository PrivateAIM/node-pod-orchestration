from typing import Optional

from kubernetes import client, config


def create_deployment(name: str, image: str, ports: list[int], namespace: str = 'default') -> list[str]:
    config.load_kube_config()
    v1 = client.AppsV1Api()

    # TODO: Container will be given -> to be changed
    containers = []
    container1 = client.V1Container(name=name, image=image, image_pull_policy="Never",
                                    ports=[client.V1ContainerPort(port) for port in ports])
    containers.append(container1)

    depl_metadata = client.V1ObjectMeta(name=name, namespace=namespace)
    depl_pod_metadata = client.V1ObjectMeta(labels={'app': name})
    depl_selector = client.V1LabelSelector(match_labels={'app': name})
    depl_pod_spec = client.V1PodSpec(containers=containers)
    depl_template = client.V1PodTemplateSpec(metadata=depl_pod_metadata, spec=depl_pod_spec)

    depl_spec = client.V1DeploymentSpec(selector=depl_selector, template=depl_template)
    depl_body = client.V1Deployment(api_version='apps/v1', kind='Deployment', metadata=depl_metadata, spec=depl_spec)

    v1.create_namespaced_deployment(namespace=namespace, body=depl_body)

    return _get_pods(name)


def delete_deployment(name: str, namespace: str = 'default') -> None:
    config.load_kube_config()
    api_client = client.AppsV1Api()

    api_client.delete_namespaced_deployment(name=name, namespace=namespace)


def get_log(name: str, pod_id: Optional[str], namespace: str = 'default') -> str:
    config.load_kube_config()
    api_client = client.CoreV1Api()
    # get pods in deployment
    pods = api_client.list_namespaced_pod(namespace=namespace, label_selector=f'app={name}')
    if pod_id is not None:
        for pod in pods.items:
            if pod.metadata.uid == pod_id:
                return api_client.read_namespaced_pod_log(pod.metadata.name, namespace)

    return api_client.read_namespaced_pod_log(pods.items[0].metadata.name, namespace)


def _get_pods(name: str, namespace: str = 'default') -> list[str]:
    config.load_kube_config()
    api_client = client.CoreV1Api()

    return api_client.list_namespaced_pod(namespace=namespace, label_selector=f'app={name}')
