from kubernetes import client, config
import docker

def run_process(image: str, registry_address: str, httpclient, docker_client) -> None:
    """
      Pulls the image from the docker hub and prepares it for deployment
    sotres it in the local registry
    - pull
    - ceck
    - add tokens
    - add servise
    - tag
    :param command:
    :return:
    """
    _pull_image(image, registry_address)
    if _check_image(image, registry_address):
        _add_tokens(image, httpclient)
        _add_service(image, docker_client)
        image = _push_image(image, "latest")
        _create_deployment(" ", image, [80, 443])
    else:
        raise Exception("Image not correct")
    return image


def _pull_image(image: str, registry_at_rest) -> str:
    """

    Pulls the image from the harbor
    :param image:
    :param client:
    :return:
    TODO
    """
    return ""


def _check_image(image: str, registry_address: str) -> bool:
    """
    TOTDO
    :param image:
    :return:
    """
    return True


def _add_tokens(image: str, client_api, docker_client) -> None:
    """

    :param image:
    :param client_api:
    :param docker_client:
    :return:
    """



def _add_service(name: str, target_port: int , ports: int, namespace: str = 'default') -> None:
    """

    :param image:
    :param docker_client:
    :return:
    """

    # Load Kubernetes configuration from default location
    config.load_kube_config()

    # Instantiate Kubernetes API client
    api_instance = client.CoreV1Api()

    # Define service specification
    service = client.V1Service(
        api_version="v1",
        kind="Service",
        metadata=client.V1ObjectMeta(name=f'{name}service'),
        spec=client.V1ServiceSpec(
            selector={"app": name},
            ports=[client.V1ServicePort(protocol="TCP", port=ports, target_port=target_port)],
            type="LoadBalancer"
        )
    )

    # Create the service
    api_instance.create_namespaced_service(namespace=namespace, body=service)



def _push_image(image: str, tag) -> str:
    """

    :param image:
    :param tag:
    :return:
    """
    pass


def _create_deployment(name: str, image: str, ports: list[int], namespace: str = 'default',
                       kind: str = 'Deployment') -> None:
    config.load_kube_config()
    v1 = client.AppsV1Api()

    containers = []
    container1 = client.V1Container(name=name, image=image, image_pull_policy="Never", ports=[client.V1ContainerPort(port) for port in ports])
    containers.append(container1)
    depl_metadata = client.V1ObjectMeta(name=name, namespace=namespace)
    depl_pod_metadata = client.V1ObjectMeta(labels={'app': name})
    depl_selector = client.V1LabelSelector(match_labels={'app': name})
    depl_pod_spec = client.V1PodSpec(containers=containers)
    depl_template = client.V1PodTemplateSpec(metadata=depl_pod_metadata, spec=depl_pod_spec)

    depl_spec = client.V1DeploymentSpec(selector=depl_selector, template=depl_template)
    depl_body = client.V1Deployment(api_version='apps/v1', kind=kind, metadata=depl_metadata, spec=depl_spec)

    v1.create_namespaced_deployment(namespace=namespace, body=depl_body)



def delete_deployment(name: str, namespace: str = 'default') -> None:
    config.load_kube_config()
    api_client = client.AppsV1Api()

    api_client.delete_namespaced_deployment(namespace=namespace, name=name)


def get_deployment_status(name_deployment: str, namespace: str = 'default') -> str:
    config.load_kube_config()
    api_client = client.AppsV1Api()

    deployment = api_client.read_namespaced_deployment(name=name_deployment, namespace=namespace)
    return deployment.status


def _get_deployment_logs(name_deployment: str, namespace: str = 'default') -> str:
    config.load_kube_config()
    api_client = client.CoreV1Api()
    # get pods in deployment
    pods = api_client.list_namespaced_pod(namespace=namespace, label_selector=f'app={name_deployment}')
    pod_name = pods.items[0].metadata.name
    api_response = _get_pod_logs(pod_name, namespace)

    return api_response

def _get_pod_logs( name_pod: str, namespace: str = 'default') -> str:
    config.load_kube_config()
    api_client = client.CoreV1Api()
    api_response = api_client.read_namespaced_pod_log(name_pod, namespace)
    return api_response


def _copy_file_to_image(image: str, file_path_local: str, file_path_container: str) -> None:
    """

    :param image:
    :param file_path_local:
    :param file_path_container:
    :return:
    """
    docker_client = docker.from_env()
    container = docker_client.containers.create(image, command="sleep infinity")
    container.start()
    container.put_archive(file_path_container, file_path_local)
    container.commit(image)
    container.stop()
    container.remove()
