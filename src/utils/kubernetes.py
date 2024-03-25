from typing import Optional
import os
from kubernetes import client, config


def load_cluster_config():
    config.load_incluster_config()


def create_harbor_secret(name: str = 'harbor-credentials', namespace: str = 'default') -> None:
    core_client = client.CoreV1Api()
    secret_metadata = client.V1ObjectMeta(name=name, namespace=namespace)
    secret = client.V1Secret(metadata=secret_metadata,
                             string_data={'docker-server': os.getenv('HARBOR_URL'),
                                          'docker-username': os.getenv('HARBOR_USER'),
                                          'docker-password': os.getenv('HARBOR_PASSWORD')}
                             )
    core_client.create_namespaced_secret(namespace=namespace, body=secret)


def create_analysis_deployment(name: str,
                               image: str,
                               ports: list[int],
                               tokens: dict[str, str] = {},
                               namespace: str = 'default') -> list[str]:
    app_client = client.AppsV1Api()
    containers = []

    liveness_probe = client.V1Probe(http_get=client.V1HTTPGetAction(path="/po/node/healthz", port=8000),
                                    initial_delay_seconds=15,
                                    period_seconds=20,
                                    failure_threshold=1,
                                    timeout_seconds=5)
    container1 = client.V1Container(name=name, image=image, image_pull_policy="Always",
                                    ports=[client.V1ContainerPort(port) for port in ports],
                                    env=[client.V1EnvVar(name=key, value=val) for key, val in tokens.items()],
                                    liveness_probe=liveness_probe)
    containers.append(container1)

    depl_metadata = client.V1ObjectMeta(name=name, namespace=namespace)
    depl_pod_metadata = client.V1ObjectMeta(labels={'app': name, 'mode': 'analysis'})
    depl_selector = client.V1LabelSelector(match_labels={'app': name, 'mode': 'analysis'})
    depl_pod_spec = client.V1PodSpec(containers=containers,
                                     image_pull_secrets=[
                                         client.V1LocalObjectReference(name="harbor-credentials"),
                                     ])
    depl_template = client.V1PodTemplateSpec(metadata=depl_pod_metadata, spec=depl_pod_spec)

    depl_spec = client.V1DeploymentSpec(selector=depl_selector, template=depl_template)
    depl_body = client.V1Deployment(api_version='apps/v1', kind='Deployment', metadata=depl_metadata, spec=depl_spec)

    app_client.create_namespaced_deployment(async_req=False, namespace=namespace, body=depl_body)

    return _get_pods(name)


def delete_deployment(name: str, namespace: str = 'default') -> None:
    app_client = client.AppsV1Api()
    app_client.delete_namespaced_deployment(async_req=False, name=name, namespace=namespace)


def get_logs(name: str, pod_ids: Optional[list[str]], namespace: str = 'default') -> list[str]:
    core_client = client.CoreV1Api()
    # get pods in deployment
    pods = core_client.list_namespaced_pod(namespace=namespace, label_selector=f'app={name}')
    if pod_ids is not None:
        return [core_client.read_namespaced_pod_log(pod.metadata.name, namespace)
                for pod in pods.items if pod.metadata.uid in pod_ids]

    return [core_client.read_namespaced_pod_log(pod.metadata.name, namespace)
            for pod in pods.items]


def _get_pods(name: str, namespace: str = 'default') -> list[str]:
    core_client = client.CoreV1Api()

    return [pod.metadata.name
            for pod in core_client.list_namespaced_pod(namespace=namespace, label_selector=f'app={name}').items]
