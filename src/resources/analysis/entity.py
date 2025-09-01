import json
from typing import Optional

from pydantic import BaseModel

from src.k8s.kubernetes import create_analysis_deployment, delete_deployment
from src.utils.token import create_analysis_tokens
from src.resources.database.db_models import AnalysisDB
from src.resources.database.entity import Database
from src.status.constants import AnalysisStatus


class Analysis(BaseModel):
    analysis_id: str
    project_id: str
    registry_url: str
    image_url: str
    registry_user: str
    registry_password: str
    namespace: str = 'default'
    kong_token: str

    deployment_name: str = ''
    tokens: Optional[dict[str, str]] = None
    analysis_config: Optional[dict[str, str]] = None
    status: str = AnalysisStatus.STARTING.value
    log: Optional[str] = None
    pod_ids: Optional[list[str]] = None

    def start(self, database: Database, namespace: str = 'default') -> None:
        self.status = AnalysisStatus.STARTED.value
        self.deployment_name = "analysis-" + self.analysis_id + "-" + str(len(database.get_deployments(self.analysis_id)) + 1)
        self.tokens = create_analysis_tokens(kong_token=self.kong_token, analysis_id=self.analysis_id)
        self.analysis_config = self.tokens
        self.analysis_config['ANALYSIS_ID'] = self.analysis_id
        self.analysis_config['PROJECT_ID'] = self.project_id
        self.analysis_config['DEPLOYMENT_NAME'] = self.deployment_name
        self.namespace = namespace
        self.pod_ids = create_analysis_deployment(name=self.deployment_name,
                                                  image=self.image_url,
                                                  env=self.analysis_config,
                                                  namespace=namespace)

        database.create_analysis(analysis_id=self.analysis_id,
                                 deployment_name=self.deployment_name,
                                 project_id=self.project_id,
                                 pod_ids=self.pod_ids,
                                 status=self.status,
                                 registry_url=self.registry_url,
                                 image_url=self.image_url,
                                 registry_user=self.registry_user,
                                 registry_password=self.registry_user,
                                 namespace=self.namespace,
                                 kong_token=self.kong_token)

    def stop(self,
             database: Database,
             log: Optional[str] = None,
             status: str = AnalysisStatus.STOPPED.value) -> None:
        if log is not None:
            self.log = log
        self.status = status
        # Delete the deployment from Kubernetes
        delete_deployment(self.deployment_name, namespace=self.namespace)
        # Update the database
        database.update_deployment(self.deployment_name, status=self.status)
        database.update_deployment(self.deployment_name, log=self.log)


def read_db_analysis(analysis: AnalysisDB) -> Analysis:
    return Analysis(analysis_id=analysis.analysis_id,
                    deployment_name=analysis.deployment_name,
                    project_id=analysis.project_id,
                    registry_url=analysis.registry_url,
                    image_url=analysis.image_url,
                    registry_user=analysis.registry_user,
                    registry_password=analysis.registry_password,
                    status=analysis.status,
                    pod_ids=json.loads(analysis.pod_ids),
                    log=analysis.log,
                    namespace=analysis.namespace,
                    kong_token=analysis.kong_token)


class CreateAnalysis(BaseModel):
    analysis_id: str = 'analysis_id'
    project_id: str = 'project_id'
    registry_url: str = 'harbor.privateaim'
    image_url: str = 'harbor.privateaim/node_id/analysis_id'
    registry_user: str = 'robot_user'
    registry_password: str = 'default_pw'
    kong_token: str = 'default_kong_token'
