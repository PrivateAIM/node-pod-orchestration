import ast
import time
from typing import Union

from flame_hub import CoreClient

from src.resources.database.entity import Database
from src.resources.analysis.entity import Analysis, CreateAnalysis, read_db_analysis
from src.resources.log.entity import CreateLogEntity
from src.status.constants import AnalysisStatus
from src.k8s.kubernetes import (create_harbor_secret,
                                get_analysis_logs,
                                delete_resource)
from src.k8s.utils import get_current_namespace, get_k8s_resource_names
from src.utils.token import _get_all_keycloak_clients
from src.utils.token import delete_keycloak_client
from src.utils.hub_client import init_hub_client_and_update_hub_status_with_robot
from src.utils.other import resource_name_to_analysis


def create_analysis(body: Union[CreateAnalysis, str], database: Database) -> dict[str, str]:
    namespace = get_current_namespace()

    if isinstance(body, str):
        body = database.extract_analysis_body(body)
        if body is None:
            return {"status": "Analysis ID not found in database."}
        else:
            body = CreateAnalysis(**body)

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
        restart_counter=body.restart_counter + 1
    )
    analysis.start(database=database, namespace=namespace)

    # update hub status
    init_hub_client_and_update_hub_status_with_robot(body.analysis_id, AnalysisStatus.STARTED.value)

    return {body.analysis_id: analysis.status}


def retrieve_history(analysis_id_str: str, database: Database) -> dict[str, dict[str, list[str]]]:
    """
    Retrieve the history of logs for a given analysis
    :param analysis_id_str:
    :param database:
    :return:
    """
    if analysis_id_str == "all":
        analysis_ids = database.get_analysis_ids()
    else:
        analysis_ids = [analysis_id_str]

    deployments = {}
    for analysis_id in analysis_ids:
        deployment = database.get_latest_deployment(analysis_id)
        if deployment is not None:
            if deployment.status in [AnalysisStatus.STOPPED.value,
                                     AnalysisStatus.FINISHED.value,
                                     AnalysisStatus.FAILED.value]:
                deployments[analysis_id] = read_db_analysis(deployment)

    analysis_logs, nginx_logs = ({}, {})
    for analysis_id, deployment in deployments.items():
        # interpret log string as a dictionary
        log = ast.literal_eval(deployment.log)
        analysis_logs[analysis_id] = log["analysis"][deployment.deployment_name]
        nginx_logs[analysis_id] = log["nginx"][f"nginx-{deployment.deployment_name}"]

    return {"analysis": analysis_logs, "nginx": nginx_logs}


def retrieve_logs(analysis_id_str: str, database: Database) -> dict[str, dict[str, list[str]]]:
    if analysis_id_str == "all":
        analysis_ids = database.get_analysis_ids()
    else:
        analysis_ids = [analysis_id_str]

    deployment_names = {}
    for analysis_id in analysis_ids:
        deployment = database.get_latest_deployment(analysis_id)
        if deployment is not None:
            if deployment.status in [AnalysisStatus.RUNNING.value]:
                deployment_names[analysis_id] = read_db_analysis(deployment).deployment_name

    return get_analysis_logs(deployment_names, database=database)


def get_status(analysis_id_str: str, database: Database) -> dict[str, str]:
    if analysis_id_str == "all":
        analysis_ids = database.get_analysis_ids()
    else:
        analysis_ids = [analysis_id_str]

    deployments = {}
    for analysis_id in analysis_ids:
        deployment = database.get_latest_deployment(analysis_id)
        if deployment is not None:
            deployments[analysis_id] = read_db_analysis(deployment)

    return {analysis_id: deployment.status for analysis_id, deployment in deployments.items()}


def get_pods(analysis_id_str: str, database: Database) -> dict[str, list[str]]:
    if analysis_id_str == "all":
        analysis_ids = database.get_analysis_ids()
    else:
        analysis_ids = [analysis_id_str]
    return {analysis_id: database.get_analysis_pod_ids(analysis_id) for analysis_id in analysis_ids}


def stop_analysis(analysis_id_str: str, database: Database) -> dict[str, str]:
    if analysis_id_str == "all":
        analysis_ids = database.get_analysis_ids()
    else:
        analysis_ids = [analysis_id_str]

    deployments = {}
    for analysis_id in analysis_ids:
        deployment = database.get_latest_deployment(analysis_id)
        if deployment is not None:
            deployments[analysis_id] = read_db_analysis(deployment)

    final_status = None

    for analysis_id, deployment in deployments.items():
        # save logs as string to database (will be read as dict in retrieve_history)
        log = str(get_analysis_logs({analysis_id: deployment.deployment_name}, database=database))
        if deployment.status in [AnalysisStatus.FAILED.value, AnalysisStatus.FINISHED.value]:
            deployment.stop(database, log=log, status=deployment.status)

            # set final status (finished overwrites any other case)
            if deployment.status == AnalysisStatus.FINISHED.value:
                final_status = AnalysisStatus.FINISHED.value
            elif final_status != AnalysisStatus.FINISHED.value:
                final_status = AnalysisStatus.FAILED.value
        else:
            deployment.stop(database, log=log)

            # set final status (finished overwrites any other case)
            if final_status is None:
                final_status = AnalysisStatus.STOPPED.value

        # update hub status
        init_hub_client_and_update_hub_status_with_robot(analysis_id, final_status)

    return {analysis_id: deployment.status for analysis_id, deployment in deployments.items()}


def delete_analysis(analysis_id_str: str, database: Database) -> dict[str, str]:
    if analysis_id_str == "all":
        analysis_ids = database.get_analysis_ids()
    else:
        analysis_ids = [analysis_id_str]

    deployments = {}
    for analysis_id in analysis_ids:
        deployment = database.get_latest_deployment(analysis_id)
        if deployment is not None:
            deployments[analysis_id] = read_db_analysis(deployment)

    for analysis_id, deployment in deployments.items():
        if deployment.status != AnalysisStatus.STOPPED.value:
            deployment.stop(database, log='')
            deployment.status = AnalysisStatus.STOPPED.value

        delete_keycloak_client(analysis_id)
        database.delete_analysis(analysis_id)

    return {analysis_id: deployment.status for analysis_id, deployment in deployments.items()}


def unstuck_analysis_deployments(analysis_id: str, database: Database) -> None:
    if database.get_latest_deployment(analysis_id) is not None:
        stop_analysis(analysis_id, database)
        time.sleep(10)  # wait for k8s to update status
        create_analysis(analysis_id, database)
        database.delete_old_deployments_from_db(analysis_id)


def cleanup(cleanup_type: str,
            database: Database,
            namespace: str = "default") -> dict[str, str]:
    cleanup_types = set(cleanup_type.split(',')) if ',' in cleanup_type else [cleanup_type]

    response_content = {}
    for cleanup_type in cleanup_types:
        if cleanup_type in ['zombies', 'all', 'analyzes', 'services', 'mb', 'rs', 'keycloak']:
            # Analysis cleanup
            if cleanup_type in ['all', 'analyzes']:
                # cleanup all analysis deployments, associated services, policies and configmaps
                response_content[cleanup_type] = f"Deleted {len(database.get_analysis_ids())} analysis deployments " + \
                                                 f"and associated resources from database ({database.get_analysis_ids()})"
                database.reset_db()
            # Service cleanup/reinit
            if cleanup_type in ['all', 'services', 'mb']:
                # reinitialize message-broker pod
                message_broker_pod_name = get_k8s_resource_names('pod',
                                                                 'label',
                                                                 'component=flame-message-broker',
                                                                 namespace=namespace)
                delete_resource(message_broker_pod_name, 'pod', namespace)
                response_content[cleanup_type] = "Reset message broker"
            if cleanup_type in ['all', 'services', 'rs']:
                # reinitialize result-service pod
                result_service_name = get_k8s_resource_names('pod',
                                                             'label',
                                                             'component=flame-result-service',
                                                             namespace=namespace)
                delete_resource(result_service_name, 'pod', namespace)
                response_content[cleanup_type] = "Reset result service"
            if cleanup_type in ['all', 'keycloak']:
                # cleanup keycloak clients without corresponding analysis
                # if all is all flame clients are deleted because ther are no analyzes in the db
                analysis_ids = database.get_analysis_ids()
                for client in _get_all_keycloak_clients():
                    if client['clientId'] not in analysis_ids and client['name'].startswith('flame-'):
                        delete_keycloak_client(client['clientId'])

        else:
            response_content[cleanup_type] = f"Unknown cleanup type: {cleanup_type} (known types: 'zombies', 'all', " +\
                                             "'analyzes', 'keycloak', 'services', 'mb', and 'rs')"
    response_content['zombies'] = clean_up_the_rest(database, namespace)
    return response_content


def clean_up_the_rest(database: Database, namespace: str = 'default') -> str:
    known_analysis_ids = database.get_analysis_ids()

    result_str = ""
    for res, (selector_args, max_r_split) in {'deployment': (['component=flame-analysis', 'component=flame-analysis-nginx'], 1),
                                              'pod': (['component=flame-analysis', 'component=flame-analysis-nginx'], 2),
                                              'service': (['component=flame-analysis', 'component=flame-analysis-nginx'], 1),
                                              'networkpolicy': (['component=flame-nginx-to-analysis-policy'], 2),
                                              'configmap': (['component=flame-nginx-analysis-config-map'], 2)}.items():
        for selector_arg in selector_args:
            resources = get_k8s_resource_names(res, 'label', selector_arg, namespace=namespace)
            resources = [resources] if type(resources) == str else resources
            if resources is not None:
                zombie_resources = [r for r in resources
                                    if resource_name_to_analysis(r, max_r_split) not in known_analysis_ids]
                for z in zombie_resources:
                    delete_resource(z, res, namespace=namespace)
                result_str += f"Deleted {len(zombie_resources)} zombie " + \
                              f"{'' if '-nginx' not in selector_arg else 'nginx-'}{res}s\n"
    return result_str


def stream_logs(log_entity: CreateLogEntity, node_id: str, database: Database, hub_core_client: CoreClient) -> None:
    try:
        database.update_analysis_log(log_entity.analysis_id, str(log_entity.to_log_entity()))
        #database.update_analysis_status(log_entity.analysis_id, log_entity.status) #TODO: Implement this?
    except IndexError as e:
        print(f"Error updating analysis log in database: {e}")

    # log to hub
    hub_core_client.create_analysis_node_log(analysis_id=log_entity.analysis_id,
                                             node_id=node_id,
                                             status=log_entity.status,
                                             level=log_entity.log_type,
                                             message=log_entity.log)
