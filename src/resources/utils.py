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
                                delete_deployment,
                                delete_analysis_pods,
                                delete_resource)
from src.k8s.utils import get_current_namespace, get_all_analysis_deployment_names, get_k8s_resource_names
from src.utils.token import delete_keycloak_client
from src.utils.hub_client import init_hub_client_and_update_hub_status_with_robot
from src.utils.other import resource_name_to_analysis


def create_analysis(body: Union[CreateAnalysis, str], database: Database) -> dict[str, str]:
    namespace = get_current_namespace()

    if type(body) == str:
        body = database.extract_analysis_body(body)
        if not hasattr(body, 'registry_url'):
            return {"status": "Analysis ID not found in database."}
    create_harbor_secret(body.registry_url, body.registry_user, body.registry_password, namespace=namespace)

    analysis = Analysis(
        analysis_id=body.analysis_id,
        project_id=body.project_id,
        registry_url=body.registry_url,
        image_url=body.image_url,
        registry_user=body.registry_user,
        registry_password=body.registry_password,
        namespace=namespace,
        kong_token=body.kong_token
    )
    analysis.start(database=database, namespace=namespace)

    # update hub status
    init_hub_client_and_update_hub_status_with_robot(body.analysis_id, AnalysisStatus.STARTED.value)

    return {"status": analysis.status}


def retrieve_history(analysis_id: str, database: Database) -> dict[str, dict[str, list[str]]]:
    """
    Retrieve the history of logs for a given analysis
    :param analysis_id:
    :param database:
    :return:
    """
    deployments = [read_db_analysis(deployment) for deployment in database.get_deployments(analysis_id)
                   if deployment.status in [AnalysisStatus.STOPPED.value,
                                            AnalysisStatus.FINISHED.value,
                                            AnalysisStatus.FAILED.value]]
    analysis_logs, nginx_logs = ({}, {})
    for deployment in deployments:
        # interpret log string as a dictionary
        log = ast.literal_eval(deployment.log)
        analysis_logs[deployment.deployment_name] = log["analysis"][deployment.deployment_name]
        nginx_logs[f"nginx-{deployment.deployment_name}"] = log["nginx"][f"nginx-{deployment.deployment_name}"]

    return {"analysis": analysis_logs, "nginx": nginx_logs}


def retrieve_logs(analysis_id: str, database: Database) -> dict[str, dict[str, list[str]]]:
    deployment_names = [read_db_analysis(deployment).deployment_name
                        for deployment in database.get_deployments(analysis_id)
                        if deployment.status == AnalysisStatus.RUNNING.value]
    return get_analysis_logs(deployment_names, database=database)


def get_status(analysis_id: str, database: Database) -> dict[str, dict[str, str]]:
    deployments = [read_db_analysis(deployment) for deployment in database.get_deployments(analysis_id)]
    return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}


def get_pods(analysis_id: str, database: Database) -> dict[str, list[str]]:
    return {"pods": database.get_analysis_pod_ids(analysis_id)}


def stop_analysis(analysis_id: str, database: Database) -> dict[str, dict[str, str]]:
    deployments = [read_db_analysis(deployment) for deployment in database.get_deployments(analysis_id)]
    final_status = None

    for deployment in deployments:
        # save logs as string to database (will be read as dict in retrieve_history)
        log = str(get_analysis_logs([deployment.deployment_name], database=database))
        print(f"log to be saved in stop_analysis for {deployment.deployment_name}: {log[:10]}...")
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

    return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}


def delete_analysis(analysis_id: str, database: Database) -> dict[str, dict[str, str]]:
    deployments = [read_db_analysis(deployment) for deployment in database.get_deployments(analysis_id)]
    for deployment in deployments:
        if deployment.status != AnalysisStatus.STOPPED.value:
            deployment.stop(database, log='')
            deployment.status = AnalysisStatus.STOPPED.value

    delete_keycloak_client(analysis_id)
    database.delete_analysis(analysis_id)

    return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}


def unstuck_analysis_deployments(analysis_id: str, database: Database) -> bool:
    deployments = [read_db_analysis(deployment) for deployment in database.get_deployments(analysis_id)]

    for deployment in deployments:
        if deployment.status == AnalysisStatus.STUCK.value:
            #delete_analysis_pods(deployment.deployment_name, deployment.project_id, get_current_namespace())
            stop_analysis(analysis_id, database)
            time.sleep(10)  # wait for k8s to update status
            create_analysis(analysis_id, database)
            database.delete_old_deployments_db(analysis_id)
            database.update_deployment_status(deployment.deployment_name, AnalysisStatus.STARTED.value)
            return True
    return False


def cleanup(cleanup_type: str,
            database: Database,
            namespace: str = "default") -> dict[str, str]:
    #TODO: Clean keycloak clients

    cleanup_types = set(cleanup_type.split(',')) if ',' in cleanup_type else [cleanup_type]

    response_content = {}
    for cleanup_type in cleanup_types:
        if cleanup_type in ['all', 'analyzes', 'services', 'mb', 'rs']:
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
        else:
            response_content[cleanup_type] = f"Unknown cleanup type: {cleanup_type} (known types: 'all', " + \
                                             "'analyzes', 'services', 'mb', and 'rs')"
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


def stream_logs(log_entity: CreateLogEntity, database: Database, hub_core_client: CoreClient) -> None:
    database.update_analysis_log(log_entity.analysis_id, str(log_entity.to_log_entity()))
    print(f"sending logs to hub client")
    # log to hub
    print(f"analysis_id: {log_entity.analysis_id}, node_id: {log_entity.node_id}, ")
    print(f"status: {log_entity.status}, level: {log_entity.log_type}, message: {log_entity.log}")

    hub_core_client.create_analysis_node_log(analysis_id=log_entity.analysis_id,
                                             node_id=log_entity.node_id,
                                             status=log_entity.status,
                                             level=log_entity.log_type,
                                             message=log_entity.log)
    print(f"sent logs to hub client")
