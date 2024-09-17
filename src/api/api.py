import ast
from pydantic import BaseModel
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.resources.analysis.entity import Analysis, read_db_analysis
from src.resources.analysis.constants import AnalysisStatus
from src.resources.database.entity import Database
from src.k8s.kubernetes import create_harbor_secret, get_analysis_logs
from src.utils.token import delete_keycloak_client

router = APIRouter()

database = Database()


class CreateAnalysis(BaseModel):
    analysis_id: str = 'analysis_id'
    project_id: str = 'project_id'
    registry_url: str = 'harbor.privateaim'
    image_url: str = 'harbor.privateaim/node_id/analysis_id'
    registry_user: str = 'robot_user'
    registry_password: str = 'default_pw'


@router.post("/", response_class=JSONResponse)
def create_analysis(body: CreateAnalysis):
    create_harbor_secret(body.registry_url, body.registry_user, body.registry_password)

    analysis = Analysis(
        analysis_id=body.analysis_id,
        project_id=body.project_id,
        image_registry_address=body.image_url,
        ports=[8000],
    )
    analysis.start(database)

    return {"status": analysis.status}


@router.get("/{analysis_id}/history", response_class=JSONResponse)
def retrieve_history(analysis_id: str):
    """
    Retrieve the history of logs for a given analysis
    :param analysis_id:
    :return:
    """
    deployments = [read_db_analysis(deployment) for deployment in database.get_deployments(analysis_id)
                   if deployment.status == AnalysisStatus.STOPPED.value]
    analysis_logs, nginx_logs = ({}, {})
    for deployment in deployments:
        log = ast.literal_eval(deployment.log)
        analysis_logs[deployment.deployment_name] = log["analysis"][deployment.deployment_name]
        nginx_logs[f"nginx-{deployment.deployment_name}"] = log["nginx"][f"nginx-{deployment.deployment_name}"]

    return {"analysis": analysis_logs, "nginx": nginx_logs}


@router.get("/{analysis_id}/logs", response_class=JSONResponse)
def retrieve_logs(analysis_id: str):
    deployment_names = [read_db_analysis(deployment).deployment_name
                        for deployment in database.get_deployments(analysis_id)
                        if deployment.status == AnalysisStatus.RUNNING.value]
    return get_analysis_logs(deployment_names, database=database)

@router.get("/{analysis_id}/status", response_class=JSONResponse)
def get_status(analysis_id: str):
    deployments = [read_db_analysis(deployment) for deployment in database.get_deployments(analysis_id)]
    return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}


@router.get("/{analysis_id}/pods", response_class=JSONResponse)
def get_pods(analysis_id: str):
    return {"pods": database.get_analysis_pod_ids(analysis_id)}


@router.put("/{analysis_id}/stop", response_class=JSONResponse)
def stop_analysis(analysis_id: str):
    deployments = [read_db_analysis(deployment) for deployment in database.get_deployments(analysis_id)
                   if deployment.status == AnalysisStatus.RUNNING.value]
    for deployment in deployments:
        log = str(get_analysis_logs([deployment.deployment_name], database=database))
        deployment.stop(database, log)
    return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}


@router.delete("/{analysis_id}/delete", response_class=JSONResponse)
def delete_analysis(analysis_id: str):
    deployments = [read_db_analysis(deployment) for deployment in database.get_deployments(analysis_id)]

    for deployment in deployments:
        if deployment.status != AnalysisStatus.STOPPED.value:
            deployment.stop(database)
            deployment.status = AnalysisStatus.STOPPED.value
    delete_keycloak_client(analysis_id)
    database.delete_analysis(analysis_id)
    return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}


@router.get("/healthz", response_class=JSONResponse)
def health():
    return {"status": "ok"}
