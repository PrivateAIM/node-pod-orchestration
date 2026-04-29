import ast
import time
from typing import Union

from fastapi import HTTPException
from flame_hub import CoreClient

from src.resources.database.entity import Database
from src.resources.analysis.entity import Analysis, CreateAnalysis, read_db_analysis
from src.resources.log.entity import CreateLogEntity
from src.status.constants import AnalysisStatus
from src.k8s.kubernetes import create_harbor_secret, get_analysis_logs
from src.k8s.utils import get_current_namespace, find_k8s_resources, delete_k8s_resource
from src.utils.token import _get_all_keycloak_clients
from src.utils.token import delete_keycloak_client
from src.utils.hub_client import (init_hub_client_and_update_hub_status_with_client,
                                  update_hub_status,
                                  get_node_analysis_id)
from src.utils.other import resource_name_to_analysis
from src.utils.po_logging import get_logger
from src.utils.other import is_uuid


logger = get_logger()


def create_analysis(body: Union[CreateAnalysis, str], database: Database) -> dict[str, str]:
    """Create and start a new analysis deployment.

    Validates the UUIDs, provisions the Harbor pull secret, constructs the
    :class:`Analysis` model, deploys it, and pushes the ``STARTED`` status to
    the FLAME Hub.

    Args:
        body: Either a :class:`CreateAnalysis` payload or an analysis id used
            to rebuild the payload from the database (restart case).
        database: Database wrapper used for persistence.

    Returns:
        Mapping ``{analysis_id: status}`` for the newly started deployment.
        When the analysis id cannot be resolved from the database, returns
        ``{'status': 'Analysis ID not found in database.'}``.

    Raises:
        HTTPException: 400 if ``analysis_id`` or ``project_id`` is not a UUID.
    """
    namespace = get_current_namespace()

    if isinstance(body, str):
        body = database.extract_analysis_body(body)
        if body is None:
            return {'status': "Analysis ID not found in database."}
        else:
            body = CreateAnalysis(**body)

    if not(is_uuid(body.analysis_id) or is_uuid(body.project_id)):
        logger.error(f"Received request to create analysis with ID {body.analysis_id} for project {body.project_id}")
        raise HTTPException(status_code=400, detail="Analysis ID and Project ID must be valid UUIDs.")

    create_harbor_secret(body.registry_url, body.registry_user, body.registry_password, namespace=namespace)

    analysis = Analysis(
        analysis_id=body.analysis_id,
        project_id=body.project_id,
        registry_url=body.registry_url,
        image_url=body.image_url,
        registry_user=body.registry_user,
        registry_password=body.registry_password,
        namespace=namespace,
        kong_token=body.kong_token,
        restart_counter=body.restart_counter + 1,
        progress=body.progress
    )
    analysis.start(database=database, namespace=namespace)

    # update hub status
    init_hub_client_and_update_hub_status_with_client(body.analysis_id, AnalysisStatus.STARTED.value)

    return {body.analysis_id: analysis.status}


def retrieve_history(analysis_id_str: str, database: Database) -> dict[str, dict[str, list[str]]]:
    """Return the persisted analysis and nginx logs for terminated analyses.

    Only deployments in ``STOPPED``, ``EXECUTED``, or ``FAILED`` are included.
    The stored log column is parsed back into a dictionary via ``ast.literal_eval``.

    Args:
        analysis_id_str: Specific analysis id or the literal string ``"all"``.
        database: Database wrapper used for the lookup.

    Returns:
        Nested mapping ``{'analysis': {analysis_id: [...]},
        'nginx': {analysis_id: [...]}}``.
    """
    if analysis_id_str == 'all':
        analysis_ids = database.get_analysis_ids()
    else:
        analysis_ids = [analysis_id_str]

    deployments = {}
    for analysis_id in analysis_ids:
        deployment = database.get_latest_deployment(analysis_id)
        if deployment is not None:
            if deployment.status in [AnalysisStatus.STOPPED.value,
                                     AnalysisStatus.EXECUTED.value,
                                     AnalysisStatus.FAILED.value]:
                deployments[analysis_id] = read_db_analysis(deployment)

    analysis_logs, nginx_logs = ({}, {})
    for analysis_id, deployment in deployments.items():
        # interpret log string as a dictionary
        log = ast.literal_eval(deployment.log)
        analysis_logs[analysis_id] = log['analysis'][analysis_id]
        nginx_logs[analysis_id] = log['nginx'][analysis_id]

    return {'analysis': analysis_logs, 'nginx': nginx_logs}


def retrieve_logs(analysis_id_str: str, database: Database) -> dict[str, dict[str, list[str]]]:
    """Return live pod logs for analyses currently in ``EXECUTING``.

    Args:
        analysis_id_str: Specific analysis id or the literal string ``"all"``.
        database: Database wrapper used to resolve deployment names.

    Returns:
        Nested mapping ``{'analysis': {...}, 'nginx': {...}}`` returned by
        :func:`get_analysis_logs`.
    """
    if analysis_id_str == 'all':
        analysis_ids = database.get_analysis_ids()
    else:
        analysis_ids = [analysis_id_str]

    deployment_names = {}
    for analysis_id in analysis_ids:
        deployment = database.get_latest_deployment(analysis_id)
        if deployment is not None:
            if deployment.status in [AnalysisStatus.EXECUTING.value]:
                deployment_names[analysis_id] = read_db_analysis(deployment).deployment_name

    return get_analysis_logs(deployment_names, database=database)


def get_status_and_progress(analysis_id_str: str, database: Database) -> dict[str, dict[str, str]]:
    """Return the latest status and progress for one or all analyses.

    Args:
        analysis_id_str: Specific analysis id or the literal string ``"all"``.
        database: Database wrapper used for the lookup.

    Returns:
        Mapping ``{analysis_id: {'status': str, 'progress': int}}``.
    """
    if analysis_id_str == 'all':
        analysis_ids = database.get_analysis_ids()
    else:
        analysis_ids = [analysis_id_str]

    deployments = {}
    for analysis_id in analysis_ids:
        deployment = database.get_latest_deployment(analysis_id)
        if deployment is not None:
            deployments[analysis_id] = read_db_analysis(deployment)

    return {analysis_id: {'status': deployment.status, 'progress': deployment.progress}
            for analysis_id, deployment in deployments.items()}


def get_pods(analysis_id_str: str, database: Database) -> dict[str, list[str]]:
    """Return the recorded pod ids for one or all analyses.

    Args:
        analysis_id_str: Specific analysis id or the literal string ``"all"``.
        database: Database wrapper used for the lookup.

    Returns:
        Mapping ``{analysis_id: [pod_id, ...]}``.
    """
    if analysis_id_str == 'all':
        analysis_ids = database.get_analysis_ids()
    else:
        analysis_ids = [analysis_id_str]
    return {analysis_id: database.get_analysis_pod_ids(analysis_id) for analysis_id in analysis_ids}


def stop_analysis(analysis_id_str: str, database: Database) -> dict[str, str]:
    """Stop one or all analyses, persisting logs and forwarding status to the Hub.

    For each analysis:

    * snapshots the current logs into the DB (so they are still retrievable
      via ``/po/history``);
    * deletes the Kubernetes deployment;
    * preserves a terminal status (``FAILED``/``EXECUTED``/``STARTED``) if one
      is already recorded, otherwise transitions to ``STOPPED``;
    * pushes the final status to the FLAME Hub.

    Args:
        analysis_id_str: Specific analysis id or the literal string ``"all"``.
        database: Database wrapper used for persistence.

    Returns:
        Mapping ``{analysis_id: final_status}``.
    """
    if analysis_id_str == 'all':
        analysis_ids = database.get_analysis_ids()
    else:
        analysis_ids = [analysis_id_str]

    deployments = {}
    for analysis_id in analysis_ids:
        deployment = database.get_latest_deployment(analysis_id)
        if deployment is not None:
            deployments[analysis_id] = read_db_analysis(deployment)

    for analysis_id, deployment in deployments.items():
        # save logs as string to database (will be read as dict in retrieve_history)
        log = str(get_analysis_logs({analysis_id: deployment.deployment_name}, database=database))
        if deployment.status in [AnalysisStatus.FAILED.value,
                                 AnalysisStatus.EXECUTED.value,
                                 AnalysisStatus.STARTED.value]:
            deployment.stop(database, log=log, status=deployment.status)
        else:
            deployment.stop(database, log=log)

        # update hub status
        init_hub_client_and_update_hub_status_with_client(analysis_id, deployment.status)

    return {analysis_id: deployment.status for analysis_id, deployment in deployments.items()}


def delete_analysis(analysis_id_str: str, database: Database) -> dict[str, None]:
    """Stop and permanently remove one or all analyses.

    In addition to :func:`stop_analysis`, this deletes the matching Keycloak
    client and removes the analysis rows from the database.

    Args:
        analysis_id_str: Specific analysis id or the literal string ``"all"``.
        database: Database wrapper used for persistence.

    Returns:
        Mapping ``{analysis_id: None}`` acknowledging the deletions.
    """
    if analysis_id_str == 'all':
        analysis_ids = database.get_analysis_ids()
    else:
        analysis_ids = [analysis_id_str]

    deployments = {}
    for analysis_id in analysis_ids:
        deployment = database.get_latest_deployment(analysis_id)
        if deployment is not None:
            deployments[analysis_id] = read_db_analysis(deployment)

    for analysis_id, deployment in deployments.items():
        deployment.stop(database, log='')
        delete_keycloak_client(analysis_id)
        database.delete_analysis(analysis_id)

    return {analysis_id: None for analysis_id, deployment in deployments.items()}


def unstuck_analysis_deployments(analysis_id: str, database: Database) -> None:
    """Stop and restart an analysis to recover from a stuck/slow state.

    Waits 10 seconds between stop and recreate to let Kubernetes settle, then
    prunes historical deployment rows so only the latest one remains.
    """
    if database.get_latest_deployment(analysis_id) is not None:
        stop_analysis(analysis_id, database)
        success = False
        for i in range(_MAX_UNSTUCK_REATTEMPTS):
            try:
                time.sleep(10)  # wait for k8s to update status
                create_analysis(analysis_id, database)
                database.delete_old_deployments_from_db(analysis_id)
                success = True
                break
            except Exception as e:
                logger.warning(f"Failed to stop analysis {analysis_id} ({repr(e)}) "
                               f"-> Reattempting unstuck ({i + 1} of {_MAX_UNSTUCK_REATTEMPTS})")
        if not success:
            logger.error(f"Failed to unstuck analysis {analysis_id} after max reattempts.")
            database.update_deployment_status(deployment.deployment_name, AnalysisStatus.FAILED.value)
            stop_analysis(analysis_id, database)


def cleanup(cleanup_type: str,
            database: Database,
            namespace: str = 'default') -> dict[str, str]:
    """Run one or more targeted cleanup passes.

    Supported selectors (comma-separated allowed):

    * ``all`` — resets the database and reinitializes message broker, storage
      service, and Keycloak clients.
    * ``analyzes`` — resets the analysis database.
    * ``services`` / ``mb`` / ``rs`` — restart FLAME helper pods.
    * ``keycloak`` — delete Keycloak clients without a matching analysis.

    :func:`clean_up_the_rest` is always appended under the ``zombies`` key.

    Args:
        cleanup_type: Selector or comma-separated selectors.
        database: Database wrapper used for persistence.
        namespace: Namespace to search in.

    Returns:
        Mapping ``{selector: summary_string}``.
    """
    cleanup_types = cleanup_type.split(',') if ',' in cleanup_type else [cleanup_type]

    response_content = {}
    for cleanup_type in cleanup_types:
        if cleanup_type in ['all', 'analyzes', 'services', 'mb', 'rs', 'keycloak']:
            # Analysis cleanup
            if cleanup_type in ['all', 'analyzes']:
                # cleanup all analysis deployments, associated services, policies and configmaps
                response_content[cleanup_type] = f"Deleted {len(database.get_analysis_ids())} analysis deployments " + \
                                                 f"and associated resources from database ({database.get_analysis_ids()})"
                database.reset_db()
            # Service cleanup/reinit
            if cleanup_type in ['all', 'services', 'mb']:
                # reinitialize message-broker pod
                message_broker_pod_name = find_k8s_resources('pod',
                                                             'label',
                                                             "component=flame-message-broker",
                                                             namespace=namespace)[0]
                delete_k8s_resource(message_broker_pod_name, 'pod', namespace)
                response_content[cleanup_type] = "Reset message broker"
            if cleanup_type in ['all', 'services', 'rs']:
                # reinitialize storage-service pod
                storage_service_name = find_k8s_resources('pod',
                                                         'label',
                                                         "component=flame-storage-service",
                                                         namespace=namespace)[0]
                delete_k8s_resource(storage_service_name, 'pod', namespace)
                response_content[cleanup_type] = "Reset storage service"
            if cleanup_type in ['all', 'keycloak']:
                # cleanup keycloak clients without corresponding analysis
                # if all is all flame clients are deleted because ther are no analyzes in the db
                analysis_ids = database.get_analysis_ids()
                for client in _get_all_keycloak_clients():
                    if (client['clientId'] not in analysis_ids) and client['name'].startswith('flame-'):
                        delete_keycloak_client(client['clientId'])

        else:
            response_content[cleanup_type] = f"Unknown cleanup type: {cleanup_type} (known types: 'zombies', 'all', " +\
                                             "'analyzes', 'keycloak', 'services', 'mb', and 'rs')"
    response_content['zombies'] = clean_up_the_rest(database, namespace)
    return response_content


def clean_up_the_rest(database: Database, namespace: str = 'default') -> str:
    """Delete orphaned Kubernetes resources whose analysis is no longer tracked.

    Iterates over deployments, pods, services, network policies, and config
    maps labelled as FLAME analysis resources, and removes any whose analysis
    id is not present in the database.

    Args:
        database: Database wrapper used to look up the known analysis ids.
        namespace: Namespace to search in.

    Returns:
        A human-readable newline-separated summary counting the zombies
        deleted per resource type.
    """
    known_analysis_ids = database.get_analysis_ids()

    result_str = ""
    for res, (selector_args, max_r_split) in {'deployment': (["component=flame-analysis", "component=flame-analysis-nginx"], 1),
                                              'pod': (["component=flame-analysis", "component=flame-analysis-nginx"], 2),
                                              'service': (["component=flame-analysis", "component=flame-analysis-nginx"], 1),
                                              'networkpolicy': (["component=flame-nginx-to-analysis-policy"], 2),
                                              'configmap': (["component=flame-nginx-analysis-config-map"], 2)}.items():
        for selector_arg in selector_args:
            resources = find_k8s_resources(res, 'label', selector_arg, namespace=namespace)
            zombie_resources = [r for r in resources
                                if (r is not None) and (resource_name_to_analysis(r, max_r_split) not in known_analysis_ids)]
            for z in zombie_resources:
                delete_k8s_resource(z, res, namespace=namespace)
            result_str += f"Deleted {len(zombie_resources)} zombie " + \
                          f"{'' if '-nginx' not in selector_arg else 'nginx-'}{res}s\n"
    return result_str


def stream_logs(log_entity: CreateLogEntity, node_id: str, enable_hub_logging: bool, database: Database, hub_core_client: CoreClient) -> None:
    """Persist a log line and mirror status/progress into the FLAME Hub.

    * Appends the serialized log to the analysis row in the database.
    * If ``enable_hub_logging`` is set, pushes the log to the Hub.
    * If the reported progress is newer than what is stored, updates both the
      DB progress and the Hub status+progress; otherwise only the Hub status
      is refreshed.

    Args:
        log_entity: Structured log body posted by the analysis.
        node_id: This node's id in the FLAME Hub.
        enable_hub_logging: Whether to forward logs to the Hub.
        database: Database wrapper used for persistence.
        hub_core_client: Initialized Hub core client.
    """
    try:
        database.update_analysis_log(log_entity.analysis_id, str(log_entity.to_log_entity()))
    except IndexError as e:
        logger.error(f"Failed to update analysis log in database: {repr(e)}")

    # log to hub
    if enable_hub_logging:
        hub_core_client.create_analysis_node_log(analysis_id=log_entity.analysis_id,
                                                 node_id=node_id,
                                                 status=log_entity.status,
                                                 level=log_entity.log_type,
                                                 message=log_entity.log)

    if database.progress_valid(log_entity.analysis_id, log_entity.progress):
        database.update_analysis_progress(log_entity.analysis_id, log_entity.progress)
        update_hub_status(hub_core_client,
                          get_node_analysis_id(hub_core_client, log_entity.analysis_id, node_id),
                          run_status=log_entity.status,
                          run_progress=log_entity.progress)
    else:
        update_hub_status(hub_core_client,
                          get_node_analysis_id(hub_core_client, log_entity.analysis_id, node_id),
                          run_status=log_entity.status)
