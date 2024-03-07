import os

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from src.resources.analysis.entity import Analysis, read_db_analysis
from src.resources.analysis.constants import AnalysisStatus
from src.resources.database.entity import Database
from src.utils.kubernetes import get_logs, delete_deployment
from src.utils.other import create_image_address

router = APIRouter()

database = Database()


@router.post("/{analysis_id}", response_class=JSONResponse)
def create_analysis(analysis_id: str):
    analysis = Analysis(
        analysis_id=analysis_id,
        image_registry_address=create_image_address(analysis_id),
        ports=[80, 443],
    )
    analysis.start(database)
    return {"status": analysis.status}


@router.get("/{analysis_id}/logs", response_class=JSONResponse)
def retrieve_logs(analysis_id: str):
    return {"logs": get_logs(analysis_id, database.get_pod_ids(analysis_id))}


@router.get("/{analysis_id}/status", response_class=JSONResponse)
def get_status(analysis_id: str):
    analysis = database.get_analysis(analysis_id)
    return {"status": analysis.status}


@router.get("/{analysis_id}/pods", response_class=JSONResponse)
def get_pods(analysis_id: str):
    return {"pods": database.get_pod_ids(analysis_id)}


@router.put("/{analysis_id}/stop", response_class=JSONResponse)
def stop_analysis(analysis_id: str):
    analysis = read_db_analysis(database.get_analysis(analysis_id))
    analysis.stop(database)
    return {"status": analysis.status}


@router.delete("/{analysis_id}/delete", response_class=JSONResponse)
def delete_analysis(analysis_id: str):
    analysis = read_db_analysis(database.get_analysis(analysis_id))
    if analysis.status != AnalysisStatus.STOPPED.value:
        analysis.stop(database)
        analysis.status = AnalysisStatus.STOPPED.value
    database.delete_analysis(analysis_id)
    return {"status": analysis.status}


@router.get("/healthz", response_class=JSONResponse)
def health():
    return {"status": "ok"}
