import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.resources.analysis.entity import AnalysisCreate
from src.resources.database.entity import Database
#from tobedeleted.run.utils import get_deployment_logs, delete_deployment


router = APIRouter()

database = Database()


@router.post("/start/{analysis_id}", response_class=JSONResponse)
def create_analysis(analysis_id: str):
    name = analysis_id  # TODO: Generate expressive names
    analysis = AnalysisCreate(
        analysis_id=analysis_id,
        registry_address=os.getenv("HARBOR_URL"),
        name=name,
        port=[80, 443],
        database=database,
    )
    return {"status": analysis.status}


@router.get("/logs/{analysis_id}", response_class=JSONResponse)
def get_logs(analysis_id: str):  # TODO: Rework similar to create_analysis()
    #logs = get_deployment_logs(analysis_id)
    #if logs is None:
    #    raise HTTPException(status_code=404, detail="Logs not found")

    json_logs = {"logs": "log"}
    return json_logs

@router.get("/status/{analysis_id}", response_class=JSONResponse)
def get_status(analysis_id: str): #TODO: Rework similar to create_analysis()
    return {"status": ''}


@router.put("/stop/{analysis_id}", response_class=JSONResponse)
def stop_analysis(analysis_id: str):  # TODO: Rework similar to create_analysis()
    #delete_deployment(analysis_id)
    return {"status": ''}

