import uvicorn
import threading
from fastapi import APIRouter, FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api.oauth import valid_access_token
from src.resources.database.entity import Database
from src.resources.analysis.entity import CreateAnalysis
from src.resources.utils import (create_analysis,
                                 retrieve_history,
                                 retrieve_logs,
                                 get_status,
                                 get_pods,
                                 stop_analysis,
                                 delete_analysis,
                                 cleanup)


class PodOrchestrationAPI:
    def __init__(self, database: Database, namespace: str = 'default'):
        self.database = database
        self.namespace = namespace
        app = FastAPI(title="FLAME PO",
                      docs_url="/api/docs",
                      redoc_url="/api/redoc",
                      openapi_url="/api/v1/openapi.json")

        origins = [
            "http://localhost:8080/",
        ]

        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        router = APIRouter()
        router.add_api_route("/",
                             self.create_analysis_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["POST"],
                             response_class=JSONResponse)
        router.add_api_route("/{analysis_id}/history",
                             self.retrieve_history_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["GET"],
                             response_class=JSONResponse)
        router.add_api_route("/{analysis_id}/logs",
                             self.retrieve_logs_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["GET"],
                             response_class=JSONResponse)
        router.add_api_route("/{analysis_id}/status",
                             self.get_status_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["GET"],
                             response_class=JSONResponse)
        router.add_api_route("/{analysis_id}/pods",
                             self.get_pods_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["GET"],
                             response_class=JSONResponse)
        router.add_api_route("/{analysis_id}/stop",
                             self.stop_analysis_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["PUT"],
                             response_class=JSONResponse)
        router.add_api_route("/{analysis_id}/delete",
                             self.delete_analysis_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["DELETE"],
                             response_class=JSONResponse)
        router.add_api_route("/cleanup/{cleanup_type}",
                             self.cleanup_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["DELETE"],
                             response_class=JSONResponse)
        router.add_api_route("/healthz",
                             self.health_call,
                             methods=["GET"],
                             response_class=JSONResponse)

        app.include_router(
            router,
            prefix="/po",
        )

        uvicorn.run(app, host="0.0.0.0", port=8000)

    def create_analysis_call(self, body: CreateAnalysis):
        return create_analysis(body, self.database)

    def retrieve_history_call(self, analysis_id: str):
        return retrieve_history(analysis_id, self.database)

    def retrieve_logs_call(self, analysis_id: str):
        return retrieve_logs(analysis_id, self.database)

    def get_status_call(self, analysis_id: str):
        return get_status(analysis_id, self.database)

    def get_pods_call(self, analysis_id: str):
        return get_pods(analysis_id, self.database)

    def stop_analysis_call(self, analysis_id: str):
        return stop_analysis(analysis_id, self.database)

    def delete_analysis_call(self, analysis_id: str):
        return delete_analysis(analysis_id, self.database)

    def cleanup_call(self, cleanup_type: str):
        return cleanup(cleanup_type, self.database, self.namespace)

    def get_service_status_call(self):
        pass

    def health_call(self):
        main_alive = threading.main_thread().is_alive()
        if not main_alive:
            raise RuntimeError("Main thread is not alive.")
        else:
            return {"status": "ok"}
