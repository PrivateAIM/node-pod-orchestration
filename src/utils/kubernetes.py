from typing import Optional
import os
import time
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
    try:
        core_client.create_namespaced_secret(namespace=namespace, body=secret)
    except client.exceptions.ApiException as e:
        if e.reason != 'Conflict':
            raise e


def create_analysis_deployment(name: str,
                               image: str,
                               ports: list[int],
                               env: dict[str, str] = {},
                               namespace: str = 'default') -> list[str]:
    app_client = client.AppsV1Api()
    containers = []

    liveness_probe = client.V1Probe(http_get=client.V1HTTPGetAction(path="/healthz", port=8000),
                                    initial_delay_seconds=15,
                                    period_seconds=20,
                                    failure_threshold=1,
                                    timeout_seconds=5)
    container1 = client.V1Container(name=name, image=image, image_pull_policy="Always",
                                    ports=[client.V1ContainerPort(port) for port in ports],
                                    env=[client.V1EnvVar(name=key, value=val) for key, val in env.items()],
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
    time.sleep(.1)

    #_create_analysis_network_policy()

    _create_analysis_service(name, ports=[80], target_ports=ports, namespace=namespace)

    return _get_pods(name)


def _create_analysis_service(name: str, ports: list[int], target_ports: list[int], namespace: str = 'default') -> None:
    core_client = client.CoreV1Api()
    service_spec = client.V1ServiceSpec(selector={'app': name},
                                        # ports=[client.V1ServicePort(port=80, target_port=8000)])
                                        ports=[client.V1ServicePort(port=port, target_port=target_port)
                                               for port, target_port in zip(ports, target_ports)])
    service_body = client.V1Service(metadata=client.V1ObjectMeta(name=f'service-{name}'), spec=service_spec)
    core_client.create_namespaced_service(body=service_body, namespace=namespace)


def _create_analysis_network_policy(namespace: str = 'default') -> None:
    network_client = client.NetworkingV1Api()

    egress = [client.V1NetworkPolicyEgressRule(
        to=[client.V1NetworkPolicyPeer(pod_selector=client.V1LabelSelector(match_labels={'app': 'po-nginx'}))],
        ports=[client.V1NetworkPolicyPort(port=5555, protocol='TCP')]
    )]
    ingress = [client.V1NetworkPolicyIngressRule(
        _from=[client.V1NetworkPolicyPeer(pod_selector=client.V1LabelSelector(match_labels={'app': 'po-nginx'}))],
        ports=[client.V1NetworkPolicyPort(end_port=5555, protocol='TCP')])]

    policy_types = ['Ingress', 'Egress']
    pod_selector = client.V1LabelSelector(client.V1LabelSelector(match_labels={'mode': 'analysis'}))
    network_spec = client.V1NetworkPolicySpec(pod_selector=pod_selector,
                                              policy_types=policy_types,
                                              ingress=ingress,
                                              egress=egress)
    network_metadata = client.V1ObjectMeta(name='po-analysis-network-policy', namespace=namespace)
    network_body = client.V1NetworkPolicy(api_version='networking.k8s.io/v1',
                                          kind='NetworkPolicy',
                                          metadata=network_metadata,
                                          spec=network_spec)

    network_client.create_namespaced_network_policy(namespace=namespace, body=network_body)


def delete_deployment(name: str, namespace: str = 'default') -> None:
    app_client = client.AppsV1Api()
    app_client.delete_namespaced_deployment(async_req=False, name=name, namespace=namespace)
    _delete_service(name, namespace)


def _delete_service(name: str, namespace: str = 'default') -> None:
    core_client = client.CoreV1Api()
    core_client.delete_namespaced_service(async_req=False, name=name, namespace=namespace)


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
