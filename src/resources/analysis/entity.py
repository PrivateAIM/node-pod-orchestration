import json
from typing import Optional

from pydantic import BaseModel

from src.utils.kubernetes import create_deployment, delete_deployment, get_logs
from src.utils.token import create_tokens
from src.resources.database.db_models import Analysis as AnalysisDB
from src.resources.database.entity import Database
from src.resources.analysis.constants import AnalysisStatus


class Analysis(BaseModel):
    analysis_id: str
    image_registry_address: str
    ports: list[int]
    tokens: Optional[dict[str, str]] = None
    status: Optional[str] = None
    log: Optional[str] = None
    pod_ids: Optional[list[str]] = None

    def start(self, database: Database) -> None:
        self.status = AnalysisStatus.CREATED.value
        self.tokens = create_tokens(self.analysis_id)
        self.pod_ids = create_deployment(name=self.analysis_id,
                                         image=self.image_registry_address,
                                         ports=self.ports,
                                         tokens=self.tokens)
        self.status = AnalysisStatus.RUNNING.value
        database.create_analysis(analysis_id=self.analysis_id,
                                 pod_ids=self.pod_ids,
                                 status=self.status,
                                 log=self.log,
                                 ports=self.ports,
                                 image_registry_address=self.image_registry_address)

    def stop(self, database: Database) -> None:
        logs = get_logs(self.analysis_id, database.get_pod_ids(self.analysis_id))
        # TODO: save final logs
        delete_deployment(name=self.analysis_id)
        self.status = AnalysisStatus.STOPPED.value
        database.stop_analysis(self.analysis_id)


def read_db_analysis(analysis: AnalysisDB) -> Analysis:
    return Analysis(analysis_id=analysis.analysis_id,
                    image_registry_address=analysis.image_registry_address,
                    ports=json.loads(analysis.ports),
                    status=analysis.status,
                    pod_ids=json.loads(analysis.pod_ids))
