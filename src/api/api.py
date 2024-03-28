import os
from pydantic import BaseModel
from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from src.resources.analysis.entity import Analysis, read_db_analysis
from src.resources.analysis.constants import AnalysisStatus
from src.resources.database.entity import Database
from src.utils.kubernetes import get_logs, delete_deployment
from src.utils.other import create_image_address

router = APIRouter()

database = Database()


class CreateAnalysis(BaseModel):
    analysis_id: str = 'flame-test'
    project_id: str = 'project1'


@router.post("/", response_class=JSONResponse)
def create_analysis(body: CreateAnalysis):
    analysis = Analysis(
        analysis_id=body.analysis_id,
        project_id=body.project_id,
        image_registry_address=create_image_address(body.analysis_id),
        ports=[8000],
    )
    analysis.start(database)
    return {"status": analysis.status}


@router.get("/{analysis_id}/logs", response_class=JSONResponse)
def retrieve_logs(analysis_id: str):
    deployments = [read_db_analysis(deployment) for deployment in database.get_deployments(analysis_id)]
    return {"logs": {deployment.deployment_name: get_logs(deployment.deployment_name,
                                                          database.get_deployment_pod_ids(deployment.deployment_name)
                                                          )
                     for deployment in deployments}}


@router.get("/{analysis_id}/status", response_class=JSONResponse)
def get_status(analysis_id: str):
    deployments = [read_db_analysis(deployment) for deployment in database.get_deployments(analysis_id)]
    return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}


@router.get("/{analysis_id}/pods", response_class=JSONResponse)
def get_pods(analysis_id: str):
    return {"pods": database.get_analysis_pod_ids(analysis_id)}


@router.put("/{analysis_id}/stop", response_class=JSONResponse)
def stop_analysis(analysis_id: str):
    deployments = [read_db_analysis(deployment) for deployment in database.get_deployments(analysis_id)]
    for deployment in deployments:
        deployment.stop(database)
    return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}


@router.delete("/{analysis_id}/delete", response_class=JSONResponse)
def delete_analysis(analysis_id: str):
    deployments = [read_db_analysis(deployment) for deployment in database.get_deployments(analysis_id)]
    for deployment in deployments:
        if deployment.status != AnalysisStatus.STOPPED.value:
            deployment.stop(database)
            deployment.status = AnalysisStatus.STOPPED.value
    database.delete_analysis(analysis_id)
    return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}


@router.get("/healthz", response_class=JSONResponse)
def health():
    return {"status": "ok"}
