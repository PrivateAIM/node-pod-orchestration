import os
import time
import json
import base64
from typing import Optional
import string

from kubernetes import client

from src.resources.database.entity import Database
from src.k8s.utils import find_k8s_resources
from src.utils.po_logging import get_logger


logger = get_logger()

PORTS = {'nginx': [80],
         'analysis': [8000],
         'service': [80]}


def create_harbor_secret(host_address: str,
                         user: str,
                         password: str,
                         name: str = 'flame-harbor-credentials',
                         namespace: str = 'default') -> None:
    """Create (or recreate) the dockerconfigjson secret used to pull analysis images.

    If a secret with the same name already exists it is deleted and recreated
    to ensure the credentials are up to date.

    Args:
        host_address: Harbor registry hostname (e.g. ``harbor.example.com``).
        user: Registry username.
        password: Registry password.
        name: Name of the Kubernetes secret to create.
        namespace: Namespace in which to create the secret.

    Raises:
        Exception: If the conflict cannot be resolved or an unexpected API
            error occurs.
    """
    core_client = client.CoreV1Api()
    secret_metadata = client.V1ObjectMeta(name=name, namespace=namespace)
    secret = client.V1Secret(metadata=secret_metadata,
                             type='kubernetes.io/dockerconfigjson',
                             string_data={'docker-server': host_address,
                                          'docker-username': user.replace('$', '\\$'),
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
        logger.warning(f"Harbor secret already exists in namespace {namespace}, attempting to resolve conflict by "
                       f"deleting and recreating the secret.")
        try:
            core_client.delete_namespaced_secret(name=name, namespace=namespace)
            core_client.create_namespaced_secret(namespace=namespace, body=secret)
        except client.exceptions.ApiException as e:
            if e.reason != 'Conflict':
                logger.error(f"Unknown error during harbor secret creation: {repr(e)}")
                raise Exception(f"Unknown error during harbor secret creation (see po logs)")
            else:
                logger.error(f"Conflict in harbor secret creation remains unresolved: {repr(e)}")
                raise Exception(f"Conflict in harbor secret creation remains unresolved (see po logs)")


def create_analysis_deployment(name: str,
                               image: str,
                               env: Optional[dict[str, str]] = None,
                               namespace: str = 'default') -> list[str]:
    """Deploy an analysis pod along with its nginx sidecar, service, and network policy.

    Creates the analysis ``Deployment`` using the Harbor pull secret, exposes
    it via a ``Service``, and then provisions the companion nginx deployment
    that reverse-proxies egress to node-local services.

    Args:
        name: Deployment name (typically ``analysis-{analysis_id}-{restart_counter}``).
        image: Fully qualified container image reference.
        env: Optional environment variables to inject into the analysis
            container.
        namespace: Namespace in which to create the resources.

    Returns:
        List of pod names that belong to the new analysis deployment.
    """
    app_client = client.AppsV1Api()
    containers = []

    container = client.V1Container(name=name,
                                   image=image,
                                   image_pull_policy='IfNotPresent',
                                   ports=[client.V1ContainerPort(PORTS['analysis'][0])],
                                   env=[client.V1EnvVar(name=key, value=val) for key, val in env.items()]
                                   if env is not None else [])
    containers.append(container)

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


def delete_deployment(deployment_name: str, namespace: str = 'default') -> None:
    """Tear down an analysis and its companion nginx resources.

    Deletes both the analysis and ``nginx-{name}`` deployments with their
    services, as well as the associated network policy and nginx ConfigMap.
    Missing resources are logged and ignored.

    Args:
        deployment_name: Name of the analysis deployment to remove.
        namespace: Namespace the resources live in.
    """
    logger.action(f"Deleting deployment {deployment_name} in namespace {namespace} at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    app_client = client.AppsV1Api()
    for name in [deployment_name, f'nginx-{deployment_name}']:
        try:
            app_client.delete_namespaced_deployment(async_req=False, name=name, namespace=namespace)
            _delete_service(name, namespace)
        except client.exceptions.ApiException as e:
            if e.reason == 'Not Found':
                logger.warning(f"Could not find {name} for deletion")
            else:
                logger.error(f"Unknown error when attempting to delete {name} (reason={e.reason})")
    network_client = client.NetworkingV1Api()
    try:
        network_client.delete_namespaced_network_policy(name=f'nginx-to-{deployment_name}-policy', namespace=namespace)
    except client.exceptions.ApiException as e:
        if e.reason == 'Not Found':
            logger.error(f"Could not find nginx-to-{deployment_name}-policy for deletion")
        else:
            logger.error(f"Unknown error when attempting to delete nginx-to-{deployment_name}-policy (reason={e.reason})")
    core_client = client.CoreV1Api()
    try:
        core_client.delete_namespaced_config_map(name=f"nginx-{deployment_name}-config", namespace=namespace)
    except client.exceptions.ApiException as e:
        if e.reason == 'Not Found':
            logger.error(f"Could not find {deployment_name}-config for deletion")
        else:
            logger.error(f"Unknown error when attempting to delete {deployment_name}-config (reason={e.reason})")


def get_analysis_logs(deployment_names: dict[str, str],
                      database: Database,
                      namespace: str = 'default') -> dict[str, dict[str, list[str]]]:
    """Collect pod logs for the analysis and nginx deployments.

    Args:
        deployment_names: Mapping ``{analysis_id: deployment_name}`` to fetch
            logs for.
        database: Database wrapper used to look up recorded pod ids so that
            only pods belonging to the tracked deployment are read.
        namespace: Namespace the deployments live in.

    Returns:
        Nested mapping ``{'analysis': {analysis_id: [log, ...]},
        'nginx': {analysis_id: [log, ...]}}``.
    """
    return {'analysis': {analysis_id: _get_logs(name=deployment_name,
                                                pod_ids=database.get_deployment_pod_ids(deployment_name),
                                                namespace=namespace)
                         for analysis_id, deployment_name in deployment_names.items()},
            'nginx': {analysis_id: _get_logs(name=f"nginx-{deployment_name}",
                                             namespace=namespace)
                      for analysis_id, deployment_name in deployment_names.items()}
            }


def get_pod_status(deployment_name: str, namespace: str = 'default') -> Optional[dict[str, dict[str, str]]]:
    """Return readiness and (if not ready) failure details for each pod in a deployment.

    Args:
        deployment_name: Value of the ``app`` label selecting the deployment.
        namespace: Namespace to search in.

    Returns:
        Mapping ``{pod_name: {'ready': bool, 'reason': str, 'message': str}}``,
        or ``None`` when no pods or no container statuses are available.
    """
    core_client = client.CoreV1Api()

    # get pods in deployment
    pods = core_client.list_namespaced_pod(namespace=namespace, label_selector=f'app={deployment_name}').items

    if pods is not None:
        pod_status = {}
        for pod in pods:
            if pod is not None:
                name = pod.metadata.name
                status = pod.status.container_statuses

                if status and status[0]:
                    status = status[0]
                    pod_status[name] = {}
                    pod_status[name]['ready'] = status.ready
                    if status.ready:
                        pod_status[name]['reason'] = ''
                        pod_status[name]['message'] = ''
                    else:
                        if status.state.waiting is not None:
                            pod_status[name]['reason'] = str(status.state.waiting.reason)
                            pod_status[name]['message'] = str(status.state.waiting.message)
                        elif status.state.terminated is not None:
                            pod_status[name]['reason'] = str(status.state.terminated.reason)
                            pod_status[name]['message'] = str(status.state.terminated.message)
                        else:
                            pod_status[name]['reason'] = "UnknownError"
                            pod_status[name]['message'] = "Kubernetes fell into an unknown error state (neither terminated nor waiting)."
        if pod_status:
            return pod_status
        else:
            return None
    else:
        return None


def _build_net_stats_container() -> Optional[client.V1Container]:
    """Build the net-stats sidecar container spec, or return None if disabled.

    Controlled by the ``NET_STATS_ENABLED`` env var. Image and polling interval
    are read from ``NET_STATS_IMAGE`` and ``NET_STATS_INTERVAL_SECONDS``.
    """
    if os.getenv('NET_STATS_ENABLED', '').lower() not in ('1', 'true'):
        return None

    _NET_STATS_SCRIPT = """\
    prev_rx=0; prev_tx=0
    while true; do
      iface=$(grep -v -e lo -e 'Inter' -e 'face' /proc/net/dev | awk -F: '{print $1}' | tr -d ' ' | head -1)
      if [ -n "$iface" ]; then
        line=$(grep "${iface}:" /proc/net/dev | tr -s ' ')
        rx=$(echo $line | cut -d' ' -f2)
        tx=$(echo $line | cut -d' ' -f10)
        if [ "$prev_rx" -gt 0 ]; then
          delta_rx=$((rx - prev_rx))
          delta_tx=$((tx - prev_tx))
          printf '{"level":"info","message":"network_stats","bytes_in":%d,"bytes_out":%d,"interval_seconds":%d,"interface":"%s"}\\n' $delta_rx $delta_tx $INTERVAL "$iface"
        fi
        prev_rx=$rx; prev_tx=$tx
      fi
      sleep $INTERVAL
    done
    """

    return client.V1Container(
        name='net-stats',
        image=os.getenv('NET_STATS_IMAGE', 'busybox:1.37'),
        image_pull_policy='IfNotPresent',
        command=['/bin/sh', '-c', _NET_STATS_SCRIPT],
        env=[client.V1EnvVar(name='INTERVAL', value=os.getenv('NET_STATS_INTERVAL_SECONDS', '10'))],
    )


def _create_analysis_nginx_deployment(analysis_name: str,
                                      analysis_service_name: str,
                                      analysis_env: Optional[dict[str, str]] = None,
                                      namespace: str = 'default') -> tuple[str, str]:
    """Deploy the nginx reverse-proxy sidecar for an analysis.

    Builds the nginx ConfigMap, starts the ``nginx-{analysis_name}`` deployment
    with a liveness probe on ``/healthz``, creates its service, and installs
    the network policy locking egress/ingress to the analysis pod.

    Args:
        analysis_name: Name of the analysis deployment this nginx sidecar fronts.
        analysis_service_name: Service name of the analysis deployment used as
            the nginx upstream.
        analysis_env: Analysis config (must include ``ANALYSIS_ID`` and
            ``PROJECT_ID``) used to template the nginx config.
        namespace: Namespace in which to create the resources.

    Returns:
        Tuple ``(nginx_deployment_name, nginx_service_name)``.
    """
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
    container = client.V1Container(name=nginx_name,
                                   image=os.getenv('NGINX_IMAGE', 'nginx:1.29.8'),
                                   image_pull_policy="IfNotPresent",
                                   ports=[client.V1ContainerPort(PORTS['nginx'][0])],
                                   liveness_probe=liveness_probe,
                                   volume_mounts=[vol_mount])
    containers.append(container)

    net_stats_container = _build_net_stats_container()
    if net_stats_container is not None:
        containers.append(net_stats_container)

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
                             analysis_env: Optional[dict[str, str]] = None,
                             namespace: str = 'default') -> str:
    """Build and create the nginx ConfigMap scoped to a single analysis.

    Discovers the message broker, pod orchestration, hub adapter, kong, and
    storage services at runtime, waits until each of their pods has an IP, and
    renders an ``nginx.conf`` that whitelists the analysis pod for egress and
    the message broker / pod orchestrator for ingress.

    Args:
        analysis_name: Name of the analysis deployment.
        analysis_service_name: Upstream service for ``/analysis`` ingress.
        nginx_name: Name of the nginx deployment (used to prefix the config
            map name).
        analysis_env: Analysis config containing ``ANALYSIS_ID`` and
            ``PROJECT_ID`` used in location matches.
        namespace: Namespace in which to create the ConfigMap.

    Returns:
        Name of the created ConfigMap (``{nginx_name}-config``).

    Raises:
        ValueError: If ``analysis_env`` is ``None`` or the pod orchestration
            pod cannot be found.
    """
    if analysis_env is None:
        logger.error(f"Error creating an nginx failed since no analysis_env containing analysis and poject id was provided.")
        raise ValueError(f"Error creating an nginx failed since no analysis_env containing analysis and poject id was provided.")
    core_client = client.CoreV1Api()

    # get the service name of the message broker
    message_broker_service_name = find_k8s_resources('service',
                                                     'label',
                                                     'component=flame-message-broker',
                                                     namespace=namespace)[0]

    # await and get the pod id and name of the message broker
    message_broker_pod_name = find_k8s_resources('pod',
                                                 'label',
                                                 'component=flame-message-broker',
                                                 namespace=namespace)[0]
    message_broker_pod = None
    while message_broker_pod is None:
        message_broker_pod = core_client.read_namespaced_pod(name=message_broker_pod_name,
                                                             namespace=namespace)
        if message_broker_pod is not None:
            message_broker_ip = message_broker_pod.status.pod_ip
        time.sleep(1)

    # get the service name of the pod orchestrator
    po_service_name = find_k8s_resources('service',
                                         'label',
                                         'component=flame-po',
                                         namespace=namespace)[0]

    # await and get the pod ip and name of the pod orchestrator
    pod_orchestration_name = find_k8s_resources('pod',
                                                'label',
                                                'component=flame-po',
                                                namespace=namespace)[0]
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

    # get the name of the hub adapter, kong proxy, and storage service
    hub_adapter_service_name = find_k8s_resources('service',
                                                  'label',
                                                  'component=flame-hub-adapter',
                                                  namespace=namespace)[0]
    kong_proxy_name = find_k8s_resources('service',
                                         'label',
                                         'app.kubernetes.io/name=kong',
                                         manual_name_selector='proxy',
                                         namespace=namespace)[0]
    storage_service_name = find_k8s_resources('service',
                                             'label',
                                             'component=flame-storage-service',
                                             namespace=namespace)[0]

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
                    
                    
                    # egress: analysis deployment to kong
                    location /kong {{
                        rewrite     ^/kong(/.*) $1 break;
                        proxy_pass  http://{kong_proxy_name};
                        allow       {analysis_ip};
                        deny        all;
                    }}
                    
                    
                    # egress: analysis deployment to storage-service
                    location ~ ^/storage/(final|local|intermediate) {{
                        rewrite     ^/storage(/.*) $1 break;
                        proxy_pass http://{storage_service_name}:8080;
                        allow       {analysis_ip};
                        deny        all;
                    }}
                    
                    
                    # egress: analysis deployment to hub-adapter
                    location /hub-adapter/kong/datastore/{analysis_env['PROJECT_ID']} {{
                        rewrite     ^/hub-adapter(/.*) $1 break;
                        proxy_pass http://{hub_adapter_service_name}:5000;
                        allow       {analysis_ip};
                        deny        all;
                    }}
                    
                    
                    # egress: analysis deployment to message broker: participants
                    location ~ ^/message-broker/analyses/{analysis_env['ANALYSIS_ID']}/participants(|/self) {{
                        rewrite     ^/message-broker(/.*) $1 break;
                        proxy_pass  http://{message_broker_service_name};
                        allow       {analysis_ip};
                        deny        all;
                    }}
                    # egress: analysis deployment to message broker: analysis message
                    location ~ ^/message-broker/analyses/{analysis_env['ANALYSIS_ID']}/messages(|/subscriptions) {{
                        rewrite     ^/message-broker(/.*) $1 break;
                        proxy_pass  http://{message_broker_service_name};
                        allow       {analysis_ip};
                        deny        all;
                    }}
                    # egress: analysis deployment to message broker: healthz
                    location /message-broker/healthz {{
                        rewrite     ^/message-broker(/.*) $1 break;
                        proxy_pass  http://{message_broker_service_name};
                        allow       {analysis_ip};
                        deny        all;
                    }}
                    
                    
                    # egress: analysis deployment to po: stream logs
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
                    
                    
                    # ingress: message-broker/pod-orchestration to analysis deployment
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
    """Create a ClusterIP service selecting pods by the ``app={name}`` label.

    Args:
        name: Service and selector name.
        ports: Service-side ports.
        target_ports: Matching container-side ports (zipped with ``ports``).
        meta_data_labels: Optional metadata labels; defaults to ``{'app': name}``.
        namespace: Namespace in which to create the service.

    Returns:
        The service name (equal to ``name``).
    """
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
    """Install the network policy that isolates an analysis pod.

    Allows egress only to the nginx sidecar and kube-dns, and ingress only
    from the nginx sidecar.

    Args:
        analysis_name: Target analysis deployment (pod selector).
        nginx_name: Companion nginx deployment name used in the peer selectors.
        namespace: Namespace in which to create the policy.
    """
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
    """Delete a Kubernetes service by name.

    Args:
        name: Service name.
        namespace: Namespace the service lives in.
    """
    core_client = client.CoreV1Api()
    core_client.delete_namespaced_service(async_req=False, name=name, namespace=namespace)


def _get_logs(name: str, pod_ids: Optional[list[str]] = None, namespace: str = 'default') -> list[str]:
    """Retrieve and sanitize logs for the pods matching ``app={name}``.

    Filters out INFO lines and routine health/webhook access lines, and strips
    non-printable characters.

    Args:
        name: Value of the pods' ``app`` label.
        pod_ids: Optional allowlist; pods not in this list are skipped.
        namespace: Namespace to search in.

    Returns:
        One sanitized log string per matched pod.
    """
    core_client = client.CoreV1Api()
    # get pods in deployment
    pods = core_client.list_namespaced_pod(namespace=namespace, label_selector=f'app={name}')

    pod_logs = []
    for pod in pods.items:
        if (pod_ids is None) or (pod.metadata.name in pod_ids):
            try:
                pod_logs.append(core_client.read_namespaced_pod_log(pod.metadata.name, namespace))
            except client.exceptions.ApiException as e:
                logger.error(f"APIException while trying to retrieve pod logs for pod_name={pod.metadata.name}: "
                             f"{repr(e)}")
    # sanitize pod logs
    final_logs = []
    for log in pod_logs:
        log = ''.join(filter(lambda x: x in string.printable, log))
        log = '\n'.join([l for l in log.split('\n')
                         if not l.startswith('INFO:') and
                         not (l.endswith('"GET /healthz HTTP/1.0" 200 OK') or
                              l.endswith('"POST /webhook HTTP/1.0" 200 OK'))])
        final_logs.append(log)
    return final_logs


def _get_pods(name: str, namespace: str = 'default') -> list[str]:
    """Return pod names matching the ``app={name}`` label selector.

    Args:
        name: Value of the pods' ``app`` label.
        namespace: Namespace to search in.

    Returns:
        List of matching pod names.
    """
    core_client = client.CoreV1Api()
    return [pod.metadata.name
            for pod in core_client.list_namespaced_pod(namespace=namespace, label_selector=f'app={name}').items]
