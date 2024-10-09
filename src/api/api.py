import ast
import uvicorn
from pydantic import BaseModel
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.resources.database.entity import Database
from src.resources.analysis.entity import Analysis, CreateAnalysis, read_db_analysis
from src.resources.analysis.constants import AnalysisStatus
from src.k8s.kubernetes import create_harbor_secret, get_analysis_logs
from src.utils.token import delete_keycloak_client


class PodOrchestrationAPI:
    def __init__(self, database: Database):
        self.database = database

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
        router.add_api_route("/", self.create_analysis, methods=["POST"], response_class=JSONResponse)
        router.add_api_route("/{analysis_id}/history", self.retrieve_history, methods=["GET"], response_class=JSONResponse)
        router.add_api_route("/{analysis_id}/logs", self.retrieve_logs, methods=["GET"], response_class=JSONResponse)
        router.add_api_route("/{analysis_id}/status", self.get_status, methods=["GET"], response_class=JSONResponse)
        router.add_api_route("/{analysis_id}/pods", self.get_pods, methods=["GET"], response_class=JSONResponse)
        router.add_api_route("/{analysis_id}/stop", self.stop_analysis, methods=["PUT"], response_class=JSONResponse)
        router.add_api_route("/{analysis_id}/delete", self.delete_analysis, methods=["DELETE"], response_class=JSONResponse)
        router.add_api_route("/healthz", self.health, methods=["GET"], response_class=JSONResponse)

        app.include_router(
            router,
            prefix="/po",
        )

        uvicorn.run(app, host="0.0.0.0", port=8000)


    def create_analysis(self, body: CreateAnalysis):
        create_harbor_secret(body.registry_url, body.registry_user, body.registry_password)

        analysis = Analysis(
            analysis_id=body.analysis_id,
            project_id=body.project_id,
            image_registry_address=body.image_url,
            ports=[8000],
        )
        analysis.start(self.database)

        return {"status": analysis.status}


    def retrieve_history(self, analysis_id: str):
        """
        Retrieve the history of logs for a given analysis
        :param analysis_id:
        :return:
        """
        deployments = [read_db_analysis(deployment) for deployment in self.database.get_deployments(analysis_id)
                       if deployment.status == AnalysisStatus.STOPPED.value]
        analysis_logs, nginx_logs = ({}, {})
        for deployment in deployments:
            log = ast.literal_eval(deployment.log)
            analysis_logs[deployment.deployment_name] = log["analysis"][deployment.deployment_name]
            nginx_logs[f"nginx-{deployment.deployment_name}"] = log["nginx"][f"nginx-{deployment.deployment_name}"]

        return {"analysis": analysis_logs, "nginx": nginx_logs}


    def retrieve_logs(self, analysis_id: str):
        deployment_names = [read_db_analysis(deployment).deployment_name
                            for deployment in self.database.get_deployments(analysis_id)
                            if deployment.status == AnalysisStatus.RUNNING.value]
        return get_analysis_logs(deployment_names, database=self.database)


    def get_status(self, analysis_id: str):
        deployments = [read_db_analysis(deployment) for deployment in self.database.get_deployments(analysis_id)]
        return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}


    def get_pods(self, analysis_id: str):
        return {"pods": self.database.get_analysis_pod_ids(analysis_id)}


    def stop_analysis(self, analysis_id: str):
        deployments = [read_db_analysis(deployment) for deployment in self.database.get_deployments(analysis_id)
                       if deployment.status == AnalysisStatus.RUNNING.value]
        for deployment in deployments:
            log = str(get_analysis_logs([deployment.deployment_name], database=self.database))
            deployment.stop(self.database, log)
        return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}


    def delete_analysis(self, analysis_id: str):
        deployments = [read_db_analysis(deployment) for deployment in self.database.get_deployments(analysis_id)]

        for deployment in deployments:
            if deployment.status != AnalysisStatus.STOPPED.value:
                deployment.stop(self.database)
                deployment.status = AnalysisStatus.STOPPED.value
        delete_keycloak_client(analysis_id)
        self.database.delete_analysis(analysis_id)
        return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}


    def health(self):
        return {"status": "ok"}
