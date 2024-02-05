from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from tobedeleted.run.utils import get_deployment_logs , delete_deployment, _create_deployment
router = APIRouter()


@router.post("/start/{train_id}", response_class=JSONResponse)
def start_analysis(analysis_id: str):
    # TODO get corect image name
    status = _create_deployment(analysis_id, "karthequian/helloworld:latest", [80, 443])
    return {"status": status}


@router.get("/logs/{analysis_id}", response_class=JSONResponse)
def get_logs(analysis_id: str):
    logs = get_deployment_logs(analysis_id)
    if logs is None:
        raise HTTPException(status_code=404, detail="Logs not found")

    json_logs = {"logs": logs}
    return json_logs



@router.put("/stop/{analysis_id}", response_class=JSONResponse)
def stop_analysis(analysis_id: str):
    status = delete_deployment(analysis_id)
    return {"status": status}

