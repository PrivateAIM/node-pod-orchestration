import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.resources.analysis.entity import Analysis
from src.resources.database.entity import Database
from src.utils.kubernetes import get_logs


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
    analysis.create(database)
    return {"status": analysis.status}


@router.get("/{analysis_id}/logs", response_class=JSONResponse)
def get_logs(analysis_id: str):
    return {"logs": get_logs(analysis_id)}





@router.put("/stop/{analysis_id}", response_class=JSONResponse)
def stop_analysis(analysis_id: str):  # TODO: Rework similar to create_analysis()
    return {"status": ''}
