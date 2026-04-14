import uvicorn
import os
import threading
from fastapi import APIRouter, FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.utils.hub_client import init_hub_client_with_client, get_node_id_by_client
from src.utils.other import extract_hub_envs
from src.api.oauth import valid_access_token
from src.resources.database.entity import Database
from src.resources.analysis.entity import CreateAnalysis
from src.resources.log.entity import CreateLogEntity, AnalysisStoppedLog
from src.resources.utils import (create_analysis,
                                 retrieve_history,
                                 retrieve_logs,
                                 get_status_and_progress,
                                 get_pods,
                                 stop_analysis,
                                 delete_analysis,
                                 cleanup,
                                 stream_logs)
from src.utils.po_logging import get_logger

logger = get_logger()

class PodOrchestrationAPI:
    def __init__(self, database: Database, namespace: str = 'default'):
        self.database = database

        client_id, client_secret, hub_url_core, hub_auth, enable_hub_logging, http_proxy, https_proxy = extract_hub_envs()

        self.enable_hub_logging = enable_hub_logging
        self.hub_client = init_hub_client_with_client(client_id,
                                                          client_secret,
                                                          hub_url_core,
                                                          hub_auth,
                                                          http_proxy,
                                                          https_proxy)
        self.node_id = get_node_id_by_client(self.hub_client, client_id) if self.hub_client else None
        self.namespace = namespace
        app = FastAPI(title="FLAME PO",
                      docs_url="/api/docs",
                      redoc_url="/api/redoc",
                      openapi_url="/api/v1/openapi.json")

        origins = [
            "http://localhost:8080",
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
        router.add_api_route("/history",
                             self.retrieve_all_history_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["GET"],
                             response_class=JSONResponse)
        router.add_api_route("/history/{analysis_id}",
                             self.retrieve_history_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["GET"],
                             response_class=JSONResponse)
        router.add_api_route("/logs",
                             self.retrieve_all_logs_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["GET"],
                             response_class=JSONResponse)
        router.add_api_route("/logs/{analysis_id}",
                             self.retrieve_logs_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["GET"],
                             response_class=JSONResponse)
        router.add_api_route("/status",
                             self.get_all_status_and_progress_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["GET"],
                             response_class=JSONResponse)
        router.add_api_route("/status/{analysis_id}",
                             self.get_status_and_progress_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["GET"],
                             response_class=JSONResponse)
        router.add_api_route("/pods",
                             self.get_all_pods_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["GET"],
                             response_class=JSONResponse)
        router.add_api_route("/pods/{analysis_id}",
                             self.get_pods_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["GET"],
                             response_class=JSONResponse)
        router.add_api_route("/stop",
                             self.stop_all_analysis_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["PUT"],
                             response_class=JSONResponse)
        router.add_api_route("/stop/{analysis_id}",
                             self.stop_analysis_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["PUT"],
                             response_class=JSONResponse)
        router.add_api_route("/delete",
                             self.delete_all_analysis_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["DELETE"],
                             response_class=JSONResponse)
        router.add_api_route("/delete/{analysis_id}",
                             self.delete_analysis_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["DELETE"],
                             response_class=JSONResponse)
        router.add_api_route("/cleanup/{cleanup_type}",
                             self.cleanup_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["DELETE"],
                             response_class=JSONResponse)
        router.add_api_route("/stream_logs",
                             self.stream_logs_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["POST"],
                             response_class=JSONResponse)
        router.add_api_route("/healthz",
                             self.health_call,
                             methods=["GET"],
                             response_class=JSONResponse)

        app.include_router(
            router,
            prefix="/po",
        )

        uvicorn.run(app, host="0.0.0.0", port=8000, log_config=None)

    def create_analysis_call(self, body: CreateAnalysis):
        try:
            return create_analysis(body, self.database)
        except Exception as e:
            logger.error(f"Error creating analysis: {repr(e)}")
            raise HTTPException(status_code=500, detail=f"Error creating analysis (see po logs).")

    def retrieve_all_history_call(self):
        try:
            return retrieve_history('all', self.database)
        except Exception as e:
            logger.error(f"Eerr retrieving ALL history data: {repr(e)}")
            raise HTTPException(status_code=500, detail=f"Error retrieving ALL history data (see po logs).")

    def retrieve_history_call(self, analysis_id: str):
        try:
            return retrieve_history(analysis_id, self.database)
        except Exception as e:
            logger.error(f"Error retrieving history data: {repr(e)}")
            raise HTTPException(status_code=500, detail=f"Error retrieving history data (see po logs).")

    def retrieve_all_logs_call(self):
        try:
            return retrieve_logs('all', self.database)
        except Exception as e:
            logger.error(f"Error retrieving ALL logs data: {repr(e)}")
            raise HTTPException(status_code=500, detail=f"Error retrieving ALL logs data (see po logs).")

    def retrieve_logs_call(self, analysis_id: str):
        try:
            return retrieve_logs(analysis_id, self.database)
        except Exception as e:
            logger.error(f"Error retrieving logs data: {repr(e)}")
            raise HTTPException(status_code=500, detail=f"Error retrieving logs data (see po logs).")

    def get_all_status_and_progress_call(self):
        try:
            return get_status_and_progress('all', self.database)
        except Exception as e:
            logger.error(f"eror retrieving ALL status data: {repr(e)}")
            raise HTTPException(status_code=500, detail=f"Error retrieving ALL status data (see po logs).")

    def get_status_and_progress_call(self, analysis_id: str):
        try:
            return get_status_and_progress(analysis_id, self.database)
        except Exception as e:
            logger.error(f"Error retrieving status data: {repr(e)}")
            raise HTTPException(status_code=500, detail=f"Error retrieving status data (see po logs).")

    def get_all_pods_call(self):
        try:
            return get_pods('all', self.database)
        except Exception as e:
            logger.error(f"Error retrieving ALL pod names: {repr(e)}")
            raise HTTPException(status_code=500, detail=f"Error retrieving ALL pod names (see po logs).")

    def get_pods_call(self, analysis_id: str):
        try:
            return get_pods(analysis_id, self.database)
        except Exception as e:
            logger.error(f"Error retrieving pod name: {repr(e)}")
            raise HTTPException(status_code=500, detail=f"Error retrieving pod name (see po logs).")

    def stop_all_analysis_call(self):
        try:
            response = stop_analysis('all', self.database)
            for analysis_id in self.database.get_analysis_ids():
                stream_logs(AnalysisStoppedLog(analysis_id),
                            self.node_id,
                            self.enable_hub_logging,
                            self.database,
                            self.hub_client)
            return response
        except Exception as e:
            logger.error(f"Error stopping ALL analyzes: {repr(e)}")
            raise HTTPException(status_code=500, detail=f"Error stopping ALL analyzes (see po logs).")

    def stop_analysis_call(self, analysis_id: str):
        try:
            response = stop_analysis(analysis_id, self.database)
            stream_logs(AnalysisStoppedLog(analysis_id),
                        self.node_id,
                        self.enable_hub_logging,
                        self.database,
                        self.hub_client)
            return response
        except Exception as e:
            logger.error(f"Error stopping analysis: {repr(e)}")
            raise HTTPException(status_code=500, detail=f"Error stopping analysis (see po logs).")

    def delete_all_analysis_call(self):
        try:
            return delete_analysis('all', self.database)
        except Exception as e:
            logger.error(f"Error deleting ALL analyzes: {repr(e)}")
            raise HTTPException(status_code=500, detail=f"Error deleting ALL analyzes (see po logs).")

    def delete_analysis_call(self, analysis_id: str):
        try:
            return delete_analysis(analysis_id, self.database)
        except Exception as e:
            logger.error(f"Error deleting analysis: {repr(e)}")
            raise HTTPException(status_code=500, detail=f"Error deleting analysis (see po logs).")

    def cleanup_call(self, cleanup_type: str):
        try:
            return cleanup(cleanup_type, self.database, self.namespace)
        except Exception as e:
            logger.error(f"Error cleaning up: {repr(e)}")
            raise HTTPException(status_code=500, detail=f"Error cleaning up (see po logs).")

    def stream_logs_call(self, body: CreateLogEntity):
        try:
            return stream_logs(body, self.node_id, self.enable_hub_logging, self.database, self.hub_client)
        except Exception as e:
            logger.error(f"Error streaming logs: {repr(e)}")
            raise HTTPException(status_code=500, detail=f"Error streaming logs (see po logs).")

    def health_call(self):
        main_alive = threading.main_thread().is_alive()
        if not main_alive:
            raise RuntimeError("Main thread is not alive.")
        else:
            return {'status': "ok"}
