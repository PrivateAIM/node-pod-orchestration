import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.resources.analysis.entity import Analysis, read_db_analysis
from src.resources.analysis.constants import AnalysisStatus
from src.resources.database.entity import Database
from src.utils.kubernetes import get_logs, delete_deployment


router = APIRouter()

database = Database()


@router.post("/{analysis_id}", response_class=JSONResponse)
def create_analysis(analysis_id: str):
    analysis = Analysis(
        analysis_id=analysis_id,
        image_registry_address=os.getenv("HARBOR_URL") + analysis_id,
        name=analysis_id,
        ports=[80, 443],
    )
    analysis.start(database)
    return {"status": analysis.status}


@router.get("/{analysis_id}/logs", response_class=JSONResponse)
def get_logs(analysis_id: str):
    return {"logs": get_logs(analysis_id)}


@router.get("/{analysis_id}/status", response_class=JSONResponse)
def get_status(analysis_id: str):
    analysis = database.get_analysis(analysis_id)
    return {"status": analysis.status}


@router.get("/{analysis_id}/pods", response_class=JSONResponse)
def get_pods(analysis_id: str):
    return {"pods": database.get_pod_ids(analysis_id)}


@router.put("/{analysis_id}/stop", response_class=JSONResponse)
def stop_analysis(analysis_id: str):
    analysis = database.get_analysis(analysis_id)
    analysis.stop(database)
    return {"status": analysis.status}


@router.delete("/{analysis_id}/delete", response_class=JSONResponse)
def delete_analysis(analysis_id: str):
    database.delete_analysis(analysis_id)
    return {"status": ''}
