import json
from typing import Optional

from pydantic import BaseModel

from src.k8s.kubernetes import create_analysis_deployment, delete_deployment, get_logs
from src.utils.token import create_tokens
from src.resources.database.db_models import AnalysisDB
from src.resources.database.entity import Database
from src.resources.analysis.constants import AnalysisStatus
import random


class Analysis(BaseModel):
    analysis_id: str
    deployment_name: Optional[str] = None
    project_id: str
    image_registry_address: str
    ports: list[int]
    tokens: Optional[dict[str, str]] = None
    analysis_config: Optional[dict[str, str]] = None
    status: Optional[str] = None
    log: Optional[str] = None
    pod_ids: Optional[list[str]] = None

    def start(self, database: Database) -> None:
        self.status = AnalysisStatus.CREATED.value
        self.deployment_name = self.analysis_id + str(random.randint(0, 10000))
        # TODO: solution for some analyis that have to be started multiple times
        self.tokens = create_tokens(self.deployment_name, self.analysis_id, self.project_id)
        self.analysis_config = self.tokens
        self.analysis_config['ANALYSIS_ID'] = self.analysis_id
        self.analysis_config['PROJECT_ID'] = self.project_id
        self.analysis_config['DEPLOYMENT_NAME'] = self.deployment_name
        self.pod_ids = create_analysis_deployment(name=self.deployment_name,
                                                  image=self.image_registry_address,
                                                  ports=self.ports,
                                                  env=self.analysis_config)
        self.status = AnalysisStatus.RUNNING.value
        database.create_analysis(analysis_id=self.analysis_id,
                                 deployment_name=self.deployment_name,
                                 project_id=self.project_id,
                                 pod_ids=self.pod_ids,
                                 status=self.status,
                                 log=self.log,
                                 ports=self.ports,
                                 image_registry_address=self.image_registry_address)

    def stop(self, database: Database) -> None:
        logs = get_logs(self.deployment_name, database.get_deployment_pod_ids(self.deployment_name))
        # TODO: save final logs
        delete_deployment(self.deployment_name)
        self.status = AnalysisStatus.STOPPED.value
        database.stop_analysis(self.deployment_name)


def read_db_analysis(analysis: AnalysisDB) -> Analysis:
    return Analysis(analysis_id=analysis.analysis_id,
                    deployment_name=analysis.deployment_name,
                    project_id=analysis.project_id,
                    image_registry_address=analysis.image_registry_address,
                    ports=json.loads(analysis.ports),
                    status=analysis.status,
                    pod_ids=json.loads(analysis.pod_ids))
