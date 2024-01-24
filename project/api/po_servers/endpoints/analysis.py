from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/start/{train_id}", response_class=JSONResponse)
def start_analysis(analysis_id: str):
    return {"status": analysis_id}


@router.get("/logs/{analysis_id}", response_class=JSONResponse)
def get_logs(analysis_id: str):
    return {"status": analysis_id}


@router.put("/stop/{analysis_id}", response_class=JSONResponse)
def stop_analysis(analysis_id: str):
    return {"status": analysis_id}
