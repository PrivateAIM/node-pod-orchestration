import ast

from src.resources.database.entity import Database
from src.resources.analysis.entity import Analysis, CreateAnalysis, read_db_analysis
from src.status.constants import AnalysisStatus
from src.k8s.kubernetes import create_harbor_secret, get_analysis_logs
from src.utils.token import delete_keycloak_client


def create_analysis(body: CreateAnalysis, database: Database, namespace: str = 'default'):
    create_harbor_secret(body.registry_url, body.registry_user, body.registry_password, namespace=namespace)

    analysis = Analysis(
        analysis_id=body.analysis_id,
        project_id=body.project_id,
        image_registry_address=body.image_url,
        ports=[8000],
        namespace=namespace,
    )
    analysis.start(database=database, kong_token=body.kong_token, namespace=namespace)

    return {"status": analysis.status}


def retrieve_history(analysis_id: str, database: Database):
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
        log = ast.literal_eval(deployment.log)
        analysis_logs[deployment.deployment_name] = log["analysis"][deployment.deployment_name]
        nginx_logs[f"nginx-{deployment.deployment_name}"] = log["nginx"][f"nginx-{deployment.deployment_name}"]

    return {"analysis": analysis_logs, "nginx": nginx_logs}


def retrieve_logs(analysis_id: str, database: Database):
    deployment_names = [read_db_analysis(deployment).deployment_name
                        for deployment in database.get_deployments(analysis_id)
                        if deployment.status == AnalysisStatus.RUNNING.value]
    return get_analysis_logs(deployment_names, database=database)


def get_status(analysis_id: str, database: Database):
    deployments = [read_db_analysis(deployment) for deployment in database.get_deployments(analysis_id)]
    return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}


def get_pods(analysis_id: str, database: Database):
    return {"pods": database.get_analysis_pod_ids(analysis_id)}


def stop_analysis(analysis_id: str, database: Database):
    deployments = [read_db_analysis(deployment) for deployment in database.get_deployments(analysis_id)]

    for deployment in deployments:
        log = str(get_analysis_logs([deployment.deployment_name], database=database))
        print(f"log to be saved in stop_analysis for {deployment.deployment_name}: {log[:10]}...")
        if deployment.status in [AnalysisStatus.FAILED.value, AnalysisStatus.FINISHED.value]:
            deployment.stop(database, log=log, status=deployment.status)
        else:
            deployment.stop(database, log=log)
    return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}


def delete_analysis(analysis_id: str, database: Database):
    deployments = [read_db_analysis(deployment) for deployment in database.get_deployments(analysis_id)]

    for deployment in deployments:
        if deployment.status != AnalysisStatus.STOPPED.value:
            deployment.stop(database, log='')
            deployment.status = AnalysisStatus.STOPPED.value
    delete_keycloak_client(analysis_id)
    database.delete_analysis(analysis_id)
    return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}
