from kubernetes import client, config


def create_deployment(name: str, image: str, ports: list[int], namespace: str = 'default', kind: str = 'Deployment') -> None:
    config.load_kube_config()

    v1 = client.AppsV1Api()

    containers = []
    container1 = client.V1Container(name=name, image=image, ports=[client.V1ContainerPort(port) for port in ports])
    containers.append(container1)
    depl_metadata = client.V1ObjectMeta(name=name, namespace=namespace)
    depl_pod_metadata = client.V1ObjectMeta(labels={'app': name})
    depl_selector = client.V1LabelSelector(match_labels={'app': name})
    depl_pod_spec = client.V1PodSpec(containers=containers)
    depl_template = client.V1PodTemplateSpec(metadata=depl_pod_metadata, spec=depl_pod_spec)

    depl_spec = client.V1DeploymentSpec(selector=depl_selector, template=depl_template)
    depl_body = client.V1Deployment(api_version='apps/v1', kind=kind, metadata=depl_metadata, spec=depl_spec)

    v1.create_namespaced_deployment(namespace=namespace, body=depl_body)

    # v1.delete_namespaced_deployment(namespace=namespace, name=name)
