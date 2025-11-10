import time
import json
import base64
from typing import Optional
import string

from kubernetes import client, config

from src.resources.database.entity import Database
from src.k8s.utils import get_k8s_resource_names


PORTS = {'nginx': [80],
         'analysis': [8000],
         'service': [80]}


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
                                          '.dockerconfigjson': json.dumps({'auths':
                                                                               {host_address:
                                                                                    {'username': user,
                                                                                     'password': password,
                                                                                     'auth': base64.b64encode(f"{user}:{password}".encode("ascii")).decode("ascii")}}})}
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
                print("Conflict remains unresolved!")
                raise e


def create_analysis_deployment(name: str,
                               image: str,
                               env: dict[str, str] = {},
                               namespace: str = 'default') -> list[str]:
    app_client = client.AppsV1Api()
    containers = []

    liveness_probe = client.V1Probe(http_get=client.V1HTTPGetAction(path="/healthz", port=PORTS['analysis'][0]),
                                    initial_delay_seconds=15,
                                    period_seconds=20,
                                    failure_threshold=1,
                                    timeout_seconds=5)
    container1 = client.V1Container(name=name, image=image, image_pull_policy='IfNotPresent',
                                    ports=[client.V1ContainerPort(PORTS['analysis'][0])],
                                    env=[client.V1EnvVar(name=key, value=val) for key, val in env.items()],
                                    #liveness_probe=liveness_probe,
                                    )
    containers.append(container1)

    labels = {'app': name, 'component': "flame-analysis"}
    depl_metadata = client.V1ObjectMeta(name=name, namespace=namespace, labels=labels)
    depl_pod_metadata = client.V1ObjectMeta(labels=labels)
    depl_selector = client.V1LabelSelector(match_labels=labels)
    depl_pod_spec = client.V1PodSpec(containers=containers,
                                     image_pull_secrets=[
                                         client.V1LocalObjectReference(name="flame-harbor-credentials"),
                                     ])
    depl_template = client.V1PodTemplateSpec(metadata=depl_pod_metadata, spec=depl_pod_spec)

    depl_spec = client.V1DeploymentSpec(selector=depl_selector, template=depl_template)
    depl_body = client.V1Deployment(api_version='apps/v1', kind='Deployment', metadata=depl_metadata, spec=depl_spec)
    app_client.create_namespaced_deployment(async_req=False, namespace=namespace, body=depl_body)
    time.sleep(.1)

    analysis_service_name = _create_service(name,
                                            ports=PORTS['service'],
                                            target_ports=PORTS['analysis'],
                                            meta_data_labels=labels,
                                            namespace=namespace)

    nginx_name, _ = _create_analysis_nginx_deployment(name, analysis_service_name, env, namespace)

    return _get_pods(name)


def delete_resource(name: str, resource_type: str, namespace: str = 'default') -> None:
    """
    Deletes a Kubernetes resource by name and type.
    :param name: Name of the resource to delete.
    :param resource_type: Type of the resource (e.g., 'deployment', 'service', 'pod', 'configmap').
    :param namespace: Namespace in which the resource exists.
    """
    print(f"PO ACTION - Deleting resource: {name} of type {resource_type} in namespace {namespace} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    if resource_type == 'deployment':
        try:
            app_client = client.AppsV1Api()
            app_client.delete_namespaced_deployment(name=name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.reason != 'Not Found':
                print(f"Error: Not Found {name} deployment")
    elif resource_type == 'service':
        try:
            core_client = client.CoreV1Api()
            core_client.delete_namespaced_service(name=name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.reason != 'Not Found':
                print(f"Error: Not Found {name} service")
    elif resource_type == 'pod':
        try:
            core_client = client.CoreV1Api()
            core_client.delete_namespaced_pod(name=name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.reason != 'Not Found':
                print(f"Error: Not Found {name} pod")
    elif resource_type == 'configmap':
        try:
            core_client = client.CoreV1Api()
            core_client.delete_namespaced_config_map(name=name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.reason != 'Not Found':
                print(f"Error: Not Found {name} configmap")
    elif resource_type == 'networkpolicy':
        try:
            network_client = client.NetworkingV1Api()
            network_client.delete_namespaced_network_policy(name=name, namespace=namespace)
        except client.exceptions.ApiException as e:
            if e.reason != 'Not Found':
                print(f"Error: Not Found {name} networkpolicy")
    else:
        raise ValueError(f"Unsupported resource type: {resource_type}")


def delete_deployment(deployment_name: str, namespace: str = 'default') -> None:
    print(f"PO ACTION - Deleting deployment {deployment_name} in namespace {namespace} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    app_client = client.AppsV1Api()
    for name in [deployment_name, f'nginx-{deployment_name}']:
        try:
            app_client.delete_namespaced_deployment(async_req=False, name=name, namespace=namespace)
            _delete_service(name, namespace)
        except client.exceptions.ApiException as e:
            if e.reason != 'Not Found':
                print(f"Error: Not Found {name}")
    network_client = client.NetworkingV1Api()
    try:
        network_client.delete_namespaced_network_policy(name=f'nginx-to-{deployment_name}-policy', namespace=namespace)
    except client.exceptions.ApiException as e:
        if e.reason != 'Not Found':
            print(f"Error: Not Found nginx-to-{deployment_name}-policy")
    core_client = client.CoreV1Api()
    try:
        core_client.delete_namespaced_config_map(name=f"nginx-{deployment_name}-config", namespace=namespace)
    except client.exceptions.ApiException as e:
        if e.reason != 'Not Found':
            print(f"Error: Not Found {deployment_name}-config")


def get_analysis_logs(deployment_names: dict[str, str],
                      database: Database,
                      namespace: str = 'default') -> dict[str, dict[str, list[str]]]:
    """
    get logs for both the analysis and nginx deployment
    :param deployment_names:
    :param database:
    :param namespace:
    :return:
    """
    return {'analysis': {analysis_id: _get_logs(name=deployment_name,
                                                pod_ids=database.get_deployment_pod_ids(deployment_name),
                                                namespace=namespace)
                         for analysis_id, deployment_name in deployment_names.items()},
            'nginx': {analysis_id: _get_logs(name=f"nginx-{deployment_name}",
                                             namespace=namespace)
                      for analysis_id, deployment_name in deployment_names.items()}
            }


def delete_analysis_pods(deployment_name: str, project_id: str, namespace: str = 'default') -> None:
    print(f"PO ACTION - Deleting pods of deployment {deployment_name} in namespace {namespace} at "
          f"{time.strftime('%Y-%m-%d %H:%M:%S')}")
    core_client = client.CoreV1Api()
    # delete nginx deployment
    delete_resource(f'nginx-{deployment_name}', 'deployment', namespace)
    delete_resource(f'nginx-{deployment_name}', 'service', namespace)
    delete_resource(f'nginx-{deployment_name}-config', 'configmap', namespace)


    # get pods in deployment
    pods = core_client.list_namespaced_pod(namespace=namespace, label_selector=f'app={deployment_name}').items
    for pod in pods:
        delete_resource(pod.metadata.name, 'pod', namespace)

    # delete network policy
    delete_resource(f'nginx-to-{deployment_name}-policy', 'networkpolicy', namespace)

    # create new nginx deployment and policy
    _create_analysis_nginx_deployment(analysis_name=deployment_name,
                                      analysis_service_name=get_k8s_resource_names('service',
                                                                                   'label',
                                                                                   f'app={deployment_name}',
                                                                                   namespace=namespace),
                                      analysis_env={'PROJECT_ID': project_id,
                                                    'ANALYSIS_ID': deployment_name.split('analysis-')[-1].rsplit('-', 1)[0]},
                                      namespace=namespace)


def get_pod_status(deployment_name: str, namespace: str = 'default') -> Optional[dict[str, dict[str, str]]]:
    core_client = client.CoreV1Api()

    # get pods in deployment
    pods = core_client.list_namespaced_pod(namespace=namespace, label_selector=f'app={deployment_name}').items

    if pods is not None:
        pod_status = {}
        for pod in pods:
            if pod is not None:
                name = pod.metadata.name
                status = pod.status.container_statuses[0]

                if status is not None:
                    pod_status[name] = {}
                    pod_status[name]['ready'] = status.ready
                    if not status.ready:
                        pod_status[name]['reason'] = str(status.state.waiting.reason)
                        pod_status[name]['message'] = str(status.state.waiting.message)
                    else:
                        pod_status[name]['reason'] = ''
                        pod_status[name]['message'] = ''
        if pod_status:
            return pod_status
        else:
            return None
    else:
        return None


def _create_analysis_nginx_deployment(analysis_name: str,
                                      analysis_service_name: str,
                                      analysis_env: dict[str, str] = {},
                                      namespace: str = 'default') -> tuple[str, str]:
    app_client = client.AppsV1Api()
    containers = []
    nginx_name = f"nginx-{analysis_name}"

    config_map_name = _create_nginx_config_map(analysis_name=analysis_name,
                                               analysis_service_name=analysis_service_name,
                                               nginx_name=nginx_name,
                                               analysis_env=analysis_env,
                                               namespace=namespace)

    liveness_probe = client.V1Probe(http_get=client.V1HTTPGetAction(path="/healthz", port=PORTS['nginx'][0]),
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
                                    ports=[client.V1ContainerPort(PORTS['nginx'][0])],
                                    liveness_probe=liveness_probe,
                                    volume_mounts=[vol_mount])
    containers.append(container1)

    depl_metadata = client.V1ObjectMeta(name=nginx_name,
                                        namespace=namespace,
                                        labels={'app': nginx_name, 'component': 'flame-analysis-nginx'})
    labels = {'app': nginx_name, 'component': 'flame-analysis-nginx'}
    depl_pod_metadata = client.V1ObjectMeta(labels=labels)
    depl_selector = client.V1LabelSelector(match_labels={'app': nginx_name})
    depl_pod_spec = client.V1PodSpec(containers=containers,
                                     volumes=[cf_vol])
    depl_template = client.V1PodTemplateSpec(metadata=depl_pod_metadata, spec=depl_pod_spec)

    depl_spec = client.V1DeploymentSpec(selector=depl_selector, template=depl_template)
    depl_body = client.V1Deployment(api_version='apps/v1', kind='Deployment', metadata=depl_metadata, spec=depl_spec)

    app_client.create_namespaced_deployment(async_req=False, namespace=namespace, body=depl_body)

    nginx_service_name = _create_service(nginx_name,
                                         ports=PORTS['service'],
                                         target_ports=PORTS['service'],
                                         meta_data_labels=labels,
                                         namespace=namespace)
    time.sleep(.1)
    _create_analysis_network_policy(analysis_name, nginx_name, namespace)

    return nginx_name, nginx_service_name


def _create_nginx_config_map(analysis_name: str,
                             analysis_service_name: str,
                             nginx_name: str,
                             analysis_env: dict[str, str] = {},
                             namespace: str = 'default') -> str:
    core_client = client.CoreV1Api()

    # get the service name of the message broker
    message_broker_service_name = get_k8s_resource_names('service',
                                                         'label',
                                                         'component=flame-message-broker',
                                                         namespace=namespace)

    # await and get the pod id and name of the message broker
    message_broker_pod_name = get_k8s_resource_names('pod',
                                                     'label',
                                                     'component=flame-message-broker',
                                                     namespace=namespace)
    message_broker_pod = None
    while message_broker_pod is None:
        try:
            message_broker_pod = core_client.read_namespaced_pod(name=message_broker_pod_name,
                                                                 namespace=namespace)
        except:
            raise ValueError(f"Could not find message broker pod with name {message_broker_pod_name} in namespace {namespace}. ")
        if message_broker_pod is not None:
            message_broker_ip = message_broker_pod.status.pod_ip
        time.sleep(1)

    # get the service name of the pod orchestrator
    po_service_name = get_k8s_resource_names('service',
                                             'label',
                                             'component=flame-po',
                                             namespace=namespace)

    # await and get the pod ip and name of the pod orchestrator
    pod_orchestration_name = get_k8s_resource_names('pod',
                                                   'label',
                                                   'component=flame-po',
                                                   namespace=namespace)
    pod_orchestration_pod = None
    while pod_orchestration_pod is None:
        try:
            pod_orchestration_pod = core_client.read_namespaced_pod(name=pod_orchestration_name,
                                                                    namespace=namespace)
        except:
            raise ValueError(f"Could not find pod orchestration pod with name {pod_orchestration_name} in namespace {namespace}. ")
        if pod_orchestration_pod is not None:
            pod_orchestration_ip = pod_orchestration_pod.status.pod_ip
        time.sleep(1)

    # await and get analysis pod ip
    analysis_ip = None
    while analysis_ip is None:
        pod_list_object = core_client.list_namespaced_pod(label_selector=f"app={analysis_name}",
                                                          watch=False,
                                                          namespace=namespace)

        if len(pod_list_object.items) > 0:
            analysis_ip = pod_list_object.items[0].status.pod_ip
        time.sleep(1)

    # get the name of the hub adapter, kong proxy, and result service
    hub_adapter_service_name = get_k8s_resource_names('service',
                                                      'label',
                                                      'component=flame-hub-adapter',
                                                      namespace=namespace)
    kong_proxy_name = get_k8s_resource_names('service',
                                             'label',
                                             'app.kubernetes.io/name=kong',
                                             manual_name_selector='proxy',
                                             namespace=namespace)
    result_service_name = get_k8s_resource_names('service',
                                                 'label',
                                                 'component=flame-result-service',
                                                 namespace=namespace)

    # generate config map
    data = {
            "nginx.conf": f"""
            worker_processes 1;
            events {{ worker_connections 1024; }}
            http {{
                sendfile on;
                
                 server {{
                    listen {PORTS['nginx'][0]};
                    
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
                    
                    location ~ ^/storage/(final|local|intermediate)/ {{
                        rewrite     ^/storage(/.*) $1 break;
                        proxy_pass http://{result_service_name}:8080;
                        allow       {analysis_ip};
                        deny        all;
                    }}
                    
                    location /hub-adapter/kong/datastore/{analysis_env['PROJECT_ID']} {{
                        rewrite     ^/hub-adapter(/.*) $1 break;
                        proxy_pass http://{hub_adapter_service_name}:5000;
                        allow       {analysis_ip};
                        deny        all;
                    }}
                    
                    # analysis deployment to message broker: participants
                    location ~ ^/message-broker/analyses/{analysis_env['ANALYSIS_ID']}/participants(|/self) {{
                        rewrite     ^/message-broker(/.*) $1 break;
                        proxy_pass  http://{message_broker_service_name};
                        allow       {analysis_ip};
                        deny        all;
                    }}
                    
                     # analysis deployment to message broker: analysis message
                    location ~ ^/message-broker/analyses/{analysis_env['ANALYSIS_ID']}/messages(|/subscriptions) {{
                        rewrite     ^/message-broker(/.*) $1 break;
                        proxy_pass  http://{message_broker_service_name};
                        allow       {analysis_ip};
                        deny        all;
                    }}
                    # analysis deployment to message broker: healthz
                    location /message-broker/healthz {{
                        rewrite     ^/message-broker(/.*) $1 break;
                        proxy_pass  http://{message_broker_service_name};
                        allow       {analysis_ip};
                        deny        all;
                    }}
                    
                    # analysis deployment to po log stream
                    location /po/stream_logs {{
                        #rewrite     ^/po(/.*) $1 break;
                        proxy_pass  http://{po_service_name}:8000;
                        allow       {analysis_ip};
                        deny        all;
                        proxy_connect_timeout 10s;
                        proxy_send_timeout    120s;
                        proxy_read_timeout    120s;
                        send_timeout          120s;
                    }}
                    
                    # message-broker/pod-orchestration to analysis deployment
                    location /analysis {{
                        rewrite     ^/analysis(/.*) $1 break;
                        proxy_pass  http://{analysis_service_name};
                        allow       {message_broker_ip};
                        allow       {pod_orchestration_ip};
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
        metadata=client.V1ObjectMeta(name=name,
                                     namespace=namespace,
                                     labels={'component': 'flame-nginx-analysis-config-map'}),
        data=data
    )
    core_client.create_namespaced_config_map(namespace=namespace, body=config_map)
    return name


def _create_service(name: str,
                    ports: list[int],
                    target_ports: list[int],
                    meta_data_labels: dict[str, str] = None,
                    namespace: str = 'default') -> str:
    if meta_data_labels is None:
        meta_data_labels = {'app': name}

    core_client = client.CoreV1Api()
    service_spec = client.V1ServiceSpec(selector={'app': name},
                                        ports=[client.V1ServicePort(port=port, target_port=target_port)
                                               for port, target_port in zip(ports, target_ports)])

    service_body = client.V1Service(metadata=client.V1ObjectMeta(name=name, labels=meta_data_labels),
                                    spec=service_spec)
    core_client.create_namespaced_service(body=service_body, namespace=namespace)

    return name


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
    network_metadata = client.V1ObjectMeta(name=f'nginx-to-{analysis_name}-policy',
                                           namespace=namespace,
                                           labels={'component': 'flame-nginx-to-analysis-policy'})
    network_body = client.V1NetworkPolicy(api_version='networking.k8s.io/v1',
                                          kind='NetworkPolicy',
                                          metadata=network_metadata,
                                          spec=network_spec)

    network_client.create_namespaced_network_policy(namespace=namespace, body=network_body)


def _delete_service(name: str, namespace: str = 'default') -> None:
    core_client = client.CoreV1Api()
    core_client.delete_namespaced_service(async_req=False, name=name, namespace=namespace)


def _get_logs(name: str, pod_ids: Optional[list[str]] = None, namespace: str = 'default') -> list[str]:
    core_client = client.CoreV1Api()
    # get pods in deployment
    pods = core_client.list_namespaced_pod(namespace=namespace, label_selector=f'app={name}')

    if pod_ids is not None:
        try:
            pod_logs = [core_client.read_namespaced_pod_log(pod.metadata.name, namespace)
                        for pod in pods.items if pod.metadata.name in pod_ids]
        except client.exceptions.ApiException as e:
            print(f"Error: APIException while trying to retrieve pod logs (pod_ids in list)\n{e}")
            return []
    else:
        try:
            pod_logs = [core_client.read_namespaced_pod_log(pod.metadata.name, namespace)
                        for pod in pods.items]
        except client.exceptions.ApiException as e:
            print(f"Error: APIException while trying to retrieve pod logs (pod_ids=None)\n{e}")
            return []

    # sanitize pod logs
    return [''.join(filter(lambda x: x in string.printable, log)) for log in pod_logs]


def _get_pods(name: str, namespace: str = 'default') -> list[str]:
    core_client = client.CoreV1Api()
    return [pod.metadata.name
            for pod in core_client.list_namespaced_pod(namespace=namespace, label_selector=f'app={name}').items]
