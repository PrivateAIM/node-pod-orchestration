from typing import Optional
from enum import Enum

from pydantic import BaseModel

from src.utils.docker import download_image, validate_image
from src.utils.token import create_token
from src.utils.kubernetes import create_deployment, delete_deployment, get_logs
from src.resources.database.entity import Database


class AnalysisStatus(Enum):
    CREATED = 'created'
    RUNNING = 'running'
    STOPPED = 'stopped'


class Analysis(BaseModel):
    analysis_id: str
    image_registry_address: str
    name: str
    ports: list[int]
    status: str
    log: Optional[str]
    pod_ids: Optional[list[str]]

    def start(self, database: Database) -> None:
        self.status = AnalysisStatus.CREATED.value
        # if validate_image(self.image_registry_address, self.image_registry_address):
        self.pod_ids = create_deployment(name=self.name, image=self.image_registry_address, ports=self.ports)
        database.create_analysis(self.analysis_id, self.pod_ids)

        self.status = AnalysisStatus.RUNNING.value
        # else:
        #    raise ValueError('Validation of image against harbor reference failed.')

    def stop(self, database: Database) -> None:
        logs = get_logs(self.name, database.get_pod_ids(self.analysis_id))
        # TODO: save final logs
        delete_deployment(name=self.name)
        self.status = AnalysisStatus.STOPPED.value
        database.stop_analysis(self.analysis_id)
