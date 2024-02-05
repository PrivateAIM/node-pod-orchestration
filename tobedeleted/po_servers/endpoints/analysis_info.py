from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/status/all/current", response_class=JSONResponse)
def get_all_current_status():
    return {"status": "Test"}


@router.get("/status/finished/failed", response_class=JSONResponse)
def get_finished_failed_status():
    return {"status": "Test"}


@router.get("/status/failed", response_class=JSONResponse)
def get_failed_status():
    return {"status": "Test"}


@router.get("/status/stopped", response_class=JSONResponse)
def get_stopped_status():
    return {"status": "Test"}
