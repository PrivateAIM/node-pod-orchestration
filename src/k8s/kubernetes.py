import time
import json
import base64
from typing import Optional

from kubernetes import client, config

from src.utils.other import get_element_by_substring


def load_cluster_config():
    config.load_incluster_config()


def create_harbor_secret(host_address: str,
                         user: str,
                         password: str,
                         name: str = 'flame-harbor-credentials',
                         namespace: str = 'default') -> None:
    core_client = client.CoreV1Api()
    secret_metadata = client.V1ObjectMeta(name=name, namespace=namespace)
    secret = client.V1Secret(metadata=secret_metadata,
                             type='kubernetes.io/dockerconfigjson',
                             string_data={'docker-server': host_address,
                                          'docker-username': user.replace('$', '\$'),
                                          'docker-password': password,
                                          '.dockerconfigjson': json.dumps({"auths":
                                                                               {host_address:
                                                                                    {"username": user,
                                                                                     "password": password,
                                                                                     "auth": base64.b64encode(f'{user}:{password}'.encode("ascii")).decode("ascii")}}})}
                             )
    try:
        core_client.create_namespaced_secret(namespace=namespace, body=secret)
    except client.exceptions.ApiException:
        try:
            core_client.delete_namespaced_secret(name=name, namespace=namespace)
            core_client.create_namespaced_secret(namespace=namespace, body=secret)
        except client.exceptions.ApiException as e:
            if e.reason != 'Conflict':
                raise e
            else:
                print('Conflict remains unresolved!')
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
    container1 = client.V1Container(name=name, image=image, image_pull_policy="IfNotPresent",
                                    ports=[client.V1ContainerPort(port) for port in ports],
                                    env=[client.V1EnvVar(name=key, value=val) for key, val in env.items()],
                                    )#liveness_probe=liveness_probe)
    containers.append(container1)

    depl_metadata = client.V1ObjectMeta(name=name, namespace=namespace)
    depl_pod_metadata = client.V1ObjectMeta(labels={'app': name, 'mode': 'analysis'})
    depl_selector = client.V1LabelSelector(match_labels={'app': name, 'mode': 'analysis'})
    depl_pod_spec = client.V1PodSpec(containers=containers,
                                     image_pull_secrets=[
                                         client.V1LocalObjectReference(name="flame-harbor-credentials"),
                                     ])
    depl_template = client.V1PodTemplateSpec(metadata=depl_pod_metadata, spec=depl_pod_spec)

    depl_spec = client.V1DeploymentSpec(selector=depl_selector, template=depl_template)
    depl_body = client.V1Deployment(api_version='apps/v1', kind='Deployment', metadata=depl_metadata, spec=depl_spec)

    app_client.create_namespaced_deployment(async_req=False, namespace=namespace, body=depl_body)
    time.sleep(.1)

    service_ports = [80]
    analysis_service_name = _create_service(name, ports=service_ports, target_ports=ports, namespace=namespace)

    nginx_name, _ = _create_analysis_nginx_deployment(name, analysis_service_name, service_ports, env, namespace)
    time.sleep(.1)
    _create_analysis_network_policy(name, nginx_name, namespace)  # TODO: tie analysis deployment together with nginx deployment

    return _get_pods(name)


def _create_analysis_nginx_deployment(analysis_name: str,
                                      analysis_service_name: str,
                                      analysis_service_ports: list[int],
                                      analysis_env: dict[str, str] = {},
                                      namespace: str = 'default') -> tuple[str, str]:
    app_client = client.AppsV1Api()
    containers = []
    nginx_name = f"nginx-{analysis_name}"

    config_map_name = _create_nginx_config_map(analysis_name,
                                               analysis_service_name,
                                               nginx_name,
                                               analysis_service_ports,
                                               analysis_env,
                                               namespace)

    liveness_probe = client.V1Probe(http_get=client.V1HTTPGetAction(path="/healthz", port=80),
                                    initial_delay_seconds=15,
                                    period_seconds=20,
                                    failure_threshold=1,
                                    timeout_seconds=5)

    cf_vol = client.V1Volume(
        name="nginx-vol",
        config_map=client.V1ConfigMapVolumeSource(name=config_map_name,
                                                  items=[
                                                      client.V1KeyToPath(
                                                          key="nginx.conf",
                                                          path="nginx.conf"
                                                      )
                                                  ])
    )

    vol_mount = client.V1VolumeMount(
        name="nginx-vol",
        mount_path="/etc/nginx/nginx.conf",
        sub_path="nginx.conf"
    )

    container1 = client.V1Container(name=nginx_name, image="nginx:latest", image_pull_policy="Always",
                                    ports=[client.V1ContainerPort(port) for port in analysis_service_ports],
                                    liveness_probe=liveness_probe,
                                    volume_mounts=[vol_mount])
    containers.append(container1)

    depl_metadata = client.V1ObjectMeta(name=nginx_name, namespace=namespace)
    depl_pod_metadata = client.V1ObjectMeta(labels={'app': nginx_name})
    depl_selector = client.V1LabelSelector(match_labels={'app': nginx_name})
    depl_pod_spec = client.V1PodSpec(containers=containers,
                                     volumes=[cf_vol])
    depl_template = client.V1PodTemplateSpec(metadata=depl_pod_metadata, spec=depl_pod_spec)

    depl_spec = client.V1DeploymentSpec(selector=depl_selector, template=depl_template)
    depl_body = client.V1Deployment(api_version='apps/v1', kind='Deployment', metadata=depl_metadata, spec=depl_spec)

    app_client.create_namespaced_deployment(async_req=False, namespace=namespace, body=depl_body)

    nginx_service_name = _create_service(nginx_name,
                                         ports=analysis_service_ports,
                                         target_ports=analysis_service_ports,
                                         namespace=namespace)

    return nginx_name, nginx_service_name


def _create_nginx_config_map(analysis_name: str,
                             analysis_service_name: str,
                             nginx_name: str,
                             analysis_ports: list[int],
                             analysis_env: dict[str, str] = {},
                             namespace: str = 'default') -> str:
    core_client = client.CoreV1Api()

    # extract data sources
    service_names = get_service_names(namespace)
    hub_adapter_service_name = get_element_by_substring(service_names, 'hub-adapter-service')
    # data_sources = get_project_data_source(analysis_env['KEYCLOAK_TOKEN'],
    #                                        analysis_env['PROJECT_ID'],
    #                                        hub_adapter_service_name,
    #                                        namespace)

    # get the service ip of the message broker and analysis service
    message_broker_service_name = get_element_by_substring(service_names, 'message-broker')
    message_broker_service_ip = core_client.read_namespaced_service(name=message_broker_service_name,
                                                                    namespace=namespace).spec.cluster_ip

    # wait until analysis pod receives a cluster ip
    analysis_ip = None
    while analysis_ip is None:
        pod_list_object = core_client.list_namespaced_pod(label_selector=f"app={analysis_name}",
                                                          watch=False,
                                                          namespace=namespace)
        analysis_ip = pod_list_object.items[0].status.pod_ip
        print(analysis_ip)
        time.sleep(1)

    # analysis_ip = core_client.read_namespaced_pod(name=analysis_name, namespace=namespace).spec.cluster_ip
    # analysis_service_ip = core_client.read_namespaced_service(name=analysis_service_name,
    #                                                           namespace=namespace).spec.cluster_ip
    kong_proxy_name = get_element_by_substring(service_names, 'kong-proxy')
    result_service_name = get_element_by_substring(service_names, 'result-service')
    data = {
            "nginx.conf": f"""
            worker_processes 1;
            events {{ worker_connections 1024; }}
            http {{
                sendfile on;
                
                server {{
                    listen 80;
                    
                    client_max_body_size 0;
                    chunked_transfer_encoding on;
                    
                    proxy_redirect off;
                    proxy_set_header Host $host;
                    proxy_set_header X-Real-IP $remote_addr;
                    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
                    proxy_set_header X-Forwarded-Proto $scheme;
                    
                    # health check
                    location /healthz {{
                        return 200 'healthy';
                    }}
                    # analysis deployment to kong
                    location /kong {{
                        rewrite     ^/kong(/.*) $1 break;
                        proxy_pass  http://{kong_proxy_name};
                        allow       {analysis_ip};
                        deny        all;
                    }}
                    
                    location /storage {{
                        rewrite     ^/storage(/.*) $1 break;
                        proxy_pass http://{result_service_name}:8080;
                        allow       {analysis_ip};
                        deny        all;
                    }}
                    
                    location /hub-adapter {{
                        rewrite     ^/hub-adapter(/.*) $1 break;
                        proxy_pass http://{hub_adapter_service_name}:5000;
                        allow       {analysis_ip};
                        deny        all;
                    }}
                    
                    # analysis deployment to message broker
                    location /message-broker {{
                        rewrite     ^/message-broker(/.*) $1 break;
                        proxy_pass  http://{message_broker_service_name};
                        allow       {analysis_ip};
                        deny        all;
                    }}
                    
                    # message-broker to analysis deployment
                    location /analysis {{
                        rewrite     ^/analysis(/.*) $1 break;
                        proxy_pass  http://{analysis_service_name};
                        allow       {message_broker_service_ip};
                        deny        all;
                    }}
                }}
            }}
            """
    }

    name = f"{nginx_name}-config"
    config_map = client.V1ConfigMap(
        api_version="v1",
        kind="ConfigMap",
        metadata=client.V1ObjectMeta(name=name, namespace=namespace),
        data=data
    )
    core_client.create_namespaced_config_map(namespace=namespace, body=config_map)
    return name


def _create_service(name: str, ports: list[int], target_ports: list[int], namespace: str = 'default') -> str:
    service_name = f"analysis-{name}"
    core_client = client.CoreV1Api()

    service_spec = client.V1ServiceSpec(selector={'app': name},
                                        ports=[client.V1ServicePort(port=port, target_port=target_port)
                                               for port, target_port in zip(ports, target_ports)])
    service_body = client.V1Service(metadata=client.V1ObjectMeta(name=service_name,
                                                                 labels={'app': service_name}),
                                    spec=service_spec)
    core_client.create_namespaced_service(body=service_body, namespace=namespace)

    # service_ip = core_client.read_namespaced_service(name=service_name, namespace=namespace).spec.cluster_ip
    return service_name


def _create_analysis_network_policy(analysis_name: str, nginx_name: str, namespace: str = 'default') -> None:
    network_client = client.NetworkingV1Api()

    # egress to nginx and kube-dns pod (kube dns' namespace has to be specified)
    # currently hardcoded for this label TODO make it work with ports and protocols
    egress = [client.V1NetworkPolicyEgressRule(
        to=[client.V1NetworkPolicyPeer(
            pod_selector=client.V1LabelSelector(
                match_labels={'app': nginx_name})),
            client.V1NetworkPolicyPeer(
                pod_selector=client.V1LabelSelector(
                    match_labels={'k8s-app': 'kube-dns'}),
                namespace_selector=client.V1LabelSelector(
                    match_labels={'kubernetes.io/metadata.name': 'kube-system'}))
            ]
    )]

    # ingress from nginx pod
    ingress = [client.V1NetworkPolicyIngressRule(
        _from=[client.V1NetworkPolicyPeer(pod_selector=client.V1LabelSelector(match_labels={'app': nginx_name}))]
    )]

    policy_types = ['Ingress', 'Egress']
    pod_selector = client.V1LabelSelector(match_labels={'app': analysis_name})
    network_spec = client.V1NetworkPolicySpec(pod_selector=pod_selector,
                                              policy_types=policy_types,
                                              ingress=ingress,
                                              egress=egress)
    network_metadata = client.V1ObjectMeta(name=f'nginx-to-{analysis_name}-policy', namespace=namespace)
    network_body = client.V1NetworkPolicy(api_version='networking.k8s.io/v1',
                                          kind='NetworkPolicy',
                                          metadata=network_metadata,
                                          spec=network_spec)

    network_client.create_namespaced_network_policy(namespace=namespace, body=network_body)


def delete_deployment(depl_name: str, namespace: str = 'default') -> None:
    app_client = client.AppsV1Api()
    for name in [depl_name, f'nginx-{depl_name}']:
        try:
            app_client.delete_namespaced_deployment(async_req=False, name=name, namespace=namespace)
            _delete_service(f"analysis-{name}", namespace)
        except client.exceptions.ApiException as e:
            if e.reason != 'Not Found':
                print(f"Not Found {name}")
    network_client = client.NetworkingV1Api()
    try:
        network_client.delete_namespaced_network_policy(name=f'nginx-to-{depl_name}-policy', namespace=namespace)
    except client.exceptions.ApiException as e:
        if e.reason != 'Not Found':
            print(f"Not Found nginx-to-{depl_name}-policy")
    core_client = client.CoreV1Api()
    try:
        core_client.delete_namespaced_config_map(name=f"nginx-{depl_name}-config", namespace=namespace)
    except client.exceptions.ApiException as e:
        if e.reason != 'Not Found':
            print(f"Not Found {depl_name}-config")


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


def get_service_names(namespace: str = 'default') -> list[str]:
    core_client = client.CoreV1Api()
    return [service.metadata.name for service in core_client.list_namespaced_service(namespace=namespace).items]


def _get_pods(name: str, namespace: str = 'default') -> list[str]:
    core_client = client.CoreV1Api()
    return [pod.metadata.name
            for pod in core_client.list_namespaced_pod(namespace=namespace, label_selector=f'app={name}').items]
