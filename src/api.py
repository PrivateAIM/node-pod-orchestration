from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from .resources.analysis.entity import AnalysisCreate
from .resources.database.entity import Database
from ..tobedeleted.run.utils import get_deployment_logs, delete_deployment


router = APIRouter()

database = Database()


@router.post("/start/{analysis_id}", response_class=JSONResponse)
def create_analysis(analysis_id: str, reg_address: str):
    name = analysis_id  # TODO: Generate expressive names
    analysis = AnalysisCreate(
        analysis_id=analysis_id,
        container_registry_address=reg_address,
        name=name,
        port=[80, 443],
        database=database,
    )
    return {"status": analysis.status}


@router.get("/logs/{analysis_id}", response_class=JSONResponse)
def get_logs(analysis_id: str):  # TODO: Rework similar to create_analysis()
    logs = get_deployment_logs(analysis_id)
    if logs is None:
        raise HTTPException(status_code=404, detail="Logs not found")

    json_logs = {"logs": logs}
    return json_logs


@router.put("/stop/{analysis_id}", response_class=JSONResponse)
def stop_analysis(analysis_id: str):  # TODO: Rework similar to create_analysis()
    delete_deployment(analysis_id)
    return {"status": ''}
