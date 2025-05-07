import uvicorn
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.resources.database.entity import Database
from src.resources.analysis.entity import CreateAnalysis
from src.resources.utils import (create_analysis,
                                 retrieve_history,
                                 retrieve_logs,
                                 get_status,
                                 get_pods,
                                 stop_analysis,
                                 delete_analysis)


class PodOrchestrationAPI:
    def __init__(self, database: Database, namespace: str = 'default'):
        self.database = database
        self.namespace = namespace
        app = FastAPI(title="FLAME PO",
                      docs_url="/api/docs",
                      redoc_url="/api/redoc",
                      openapi_url="/api/v1/openapi.json", )

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
        router.add_api_route("/", self.create_analysis_call, methods=["POST"],
                             response_class=JSONResponse)
        router.add_api_route("/{analysis_id}/history", self.retrieve_history_call, methods=["GET"],
                             response_class=JSONResponse)
        router.add_api_route("/{analysis_id}/logs", self.retrieve_logs_call, methods=["GET"],
                             response_class=JSONResponse)
        router.add_api_route("/{analysis_id}/status", self.get_status_call, methods=["GET"],
                             response_class=JSONResponse)
        router.add_api_route("/{analysis_id}/pods", self.get_pods_call, methods=["GET"],
                             response_class=JSONResponse)
        router.add_api_route("/{analysis_id}/stop", self.stop_analysis_call, methods=["PUT"],
                             response_class=JSONResponse)
        router.add_api_route("/{analysis_id}/delete", self.delete_analysis_call, methods=["DELETE"],
                             response_class=JSONResponse)
        router.add_api_route("/healthz", self.health_call, methods=["GET"],
                             response_class=JSONResponse)

        app.include_router(
            router,
            prefix="/po",
        )

        uvicorn.run(app, host="0.0.0.0", port=8000)

    def create_analysis_call(self, body: CreateAnalysis, namespace: str = 'default'):
        return create_analysis(body, self.database, self.namespace)

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

    def health_call(self):
        return {"status": "ok"}
