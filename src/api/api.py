import uvicorn
import os
import threading
from fastapi import APIRouter, FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.utils.hub_client import init_hub_client_with_robot, get_node_id_by_robot
from src.api.oauth import valid_access_token
from src.resources.database.entity import Database
from src.resources.analysis.entity import CreateAnalysis
from src.resources.log.entity import CreateLogEntity
from src.resources.utils import (create_analysis,
                                 retrieve_history,
                                 retrieve_logs,
                                 get_status,
                                 get_pods,
                                 stop_analysis,
                                 delete_analysis,
                                 cleanup,
                                 stream_logs)


class PodOrchestrationAPI:
    def __init__(self, database: Database, namespace: str = 'default'):
        self.database = database
        robot_id, robot_secret, hub_url_core, hub_auth, http_proxy, https_proxy = (os.getenv('HUB_ROBOT_USER'),
                                                                                   os.getenv('HUB_ROBOT_SECRET'),
                                                                                   os.getenv('HUB_URL_CORE'),
                                                                                   os.getenv('HUB_URL_AUTH'),
                                                                                   os.getenv('PO_HTTP_PROXY'),
                                                                                   os.getenv('PO_HTTPS_PROXY'))

        self.hub_core_client = init_hub_client_with_robot(robot_id,
                                                          robot_secret,
                                                          hub_url_core,
                                                          hub_auth,
                                                          http_proxy,
                                                          https_proxy)
        self.node_id = get_node_id_by_robot(self.hub_core_client, robot_id) if self.hub_core_client else None
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
                             self.get_all_status_call,
                             dependencies=[Depends(valid_access_token)],
                             methods=["GET"],
                             response_class=JSONResponse)
        router.add_api_route("/status/{analysis_id}",
                             self.get_status_call,
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

        uvicorn.run(app, host="0.0.0.0", port=8000)

    def create_analysis_call(self, body: CreateAnalysis):
        try:
            return create_analysis(body, self.database)
        except Exception as e:
            print(f"Error creating analysis: {e}")

    def retrieve_all_history_call(self):
        try:
            return retrieve_history('all', self.database)
        except Exception as e:
            print(f"Error retrieving ALL history data: {e}")

    def retrieve_history_call(self, analysis_id: str):
        try:
            return retrieve_history(analysis_id, self.database)
        except Exception as e:
            print(f"Error retrieving history data: {e}")

    def retrieve_all_logs_call(self):
        try:
            return retrieve_logs('all', self.database)
        except Exception as e:
            print(f"Error retrieving ALL logs data: {e}")

    def retrieve_logs_call(self, analysis_id: str):
        try:
            return retrieve_logs(analysis_id, self.database)
        except Exception as e:
            print(f"Error retrieving logs data: {e}")

    def get_all_status_call(self):
        try:
            return get_status('all', self.database)
        except Exception as e:
            print(f"Error retrieving ALL status data: {e}")

    def get_status_call(self, analysis_id: str):
        try:
            return get_status(analysis_id, self.database)
        except Exception as e:
            print(f"Error retrieving status data: {e}")

    def get_all_pods_call(self):
        try:
            return get_pods('all', self.database)
        except Exception as e:
            print(f"Error retrieving ALL pod names: {e}")

    def get_pods_call(self, analysis_id: str):
        try:
            return get_pods(analysis_id, self.database)
        except Exception as e:
            print(f"Error retrieving pod name: {e}")

    def stop_all_analysis_call(self):
        try:
            return stop_analysis('all', self.database)
        except Exception as e:
            print(f"Error stopping ALL analyzes: {e}")

    def stop_analysis_call(self, analysis_id: str):
        try:
            return stop_analysis(analysis_id, self.database)
        except Exception as e:
            print(f"Error stopping analysis: {e}")

    def delete_all_analysis_call(self):
        try:
            return delete_analysis('all', self.database)
        except Exception as e:
            print(f"Error deleting ALL analyzes: {e}")

    def delete_analysis_call(self, analysis_id: str):
        try:
            return delete_analysis(analysis_id, self.database)
        except Exception as e:
            print(f"Error deleting analysis: {e}")

    def cleanup_call(self, cleanup_type: str):
        try:
            return cleanup(cleanup_type, self.database, self.namespace)
        except Exception as e:
            print(f"Error cleaning up: {e}")

    def stream_logs_call(self, body: CreateLogEntity):
        try:
            return stream_logs(body, self.node_id, self.database, self.hub_core_client)
        except Exception as e:
            print(f"Error streaming logs: {e}")

    def health_call(self):
        main_alive = threading.main_thread().is_alive()
        if not main_alive:
            raise RuntimeError("Main thread is not alive.")
        else:
            return {"status": "ok"}
