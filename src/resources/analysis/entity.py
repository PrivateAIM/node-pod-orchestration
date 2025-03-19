import random
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
    deployment_name: str = ''
    project_id: str
    image_registry_address: str
    ports: list[int]
    tokens: Optional[dict[str, str]] = None
    analysis_config: Optional[dict[str, str]] = None
    status: str = AnalysisStatus.STARTING.value
    log: Optional[str] = None
    pod_ids: Optional[list[str]] = None

    def start(self, database: Database) -> None:
        self.status = AnalysisStatus.STARTED.value
        self.deployment_name = "analysis-" + self.analysis_id + str(random.randint(0, 10000))
        # TODO: solution for some analyzes that have to be started multiple times
        self.tokens = create_analysis_tokens(self.deployment_name, self.analysis_id, self.project_id)
        self.analysis_config = self.tokens
        self.analysis_config['ANALYSIS_ID'] = self.analysis_id
        self.analysis_config['PROJECT_ID'] = self.project_id
        self.analysis_config['DEPLOYMENT_NAME'] = self.deployment_name
        self.pod_ids = create_analysis_deployment(name=self.deployment_name,
                                                  image=self.image_registry_address,
                                                  ports=self.ports,
                                                  env=self.analysis_config)

        database.create_analysis(analysis_id=self.analysis_id,
                                 deployment_name=self.deployment_name,
                                 project_id=self.project_id,
                                 pod_ids=self.pod_ids,
                                 status=self.status,
                                 ports=self.ports,
                                 image_registry_address=self.image_registry_address)

    def stop(self, database: Database, log: Optional[str] = '', namespace: str = 'default') -> None:
        self.log = log
        delete_deployment(self.deployment_name, namespace=namespace)
        self.status = AnalysisStatus.STOPPED.value
        database.update_deployment(self.deployment_name, status=self.status, log=self.log)


def read_db_analysis(analysis: AnalysisDB) -> Analysis:
    return Analysis(analysis_id=analysis.analysis_id,
                    deployment_name=analysis.deployment_name,
                    project_id=analysis.project_id,
                    image_registry_address=analysis.image_registry_address,
                    ports=json.loads(analysis.ports),
                    status=analysis.status,
                    pod_ids=json.loads(analysis.pod_ids),
                    log=analysis.log)


class CreateAnalysis(BaseModel):
    analysis_id: str = 'analysis_id'
    project_id: str = 'project_id'
    registry_url: str = 'harbor.privateaim'
    image_url: str = 'harbor.privateaim/node_id/analysis_id'
    registry_user: str = 'robot_user'
    registry_password: str = 'default_pw'
