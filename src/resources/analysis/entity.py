from typing import Optional
from enum import Enum

from pydantic import BaseModel

from src.utils.docker import download_image, validate_image
from src.utils.token import create_token
from src.utils.kubernetes import create_deployment, delete_deployment, get_log
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


class AnalysisCreate(Analysis):
    status: str = AnalysisStatus.CREATED.value

    def __int__(
            self,
            analysis_id: str,
            registry_address: str,
            name: str,
            ports: list[int],
            database: Database,
    ) -> None:
        self.analysis_id = analysis_id
        self.image_registry_address = registry_address + analysis_id
        self.name = name
        self.ports = ports

        self.image_id = download_image(self.image_registry_address)
        self.token = create_token()

        if validate_image(self.image_id, self.image_registry_address):
            pod_ids = create_deployment(name=name, image=self.image_id, ports=ports)
            self.pod_ids = pod_ids
            database.add_entry(analysis_id, pod_ids)

            self.status = AnalysisStatus.RUNNING.value
        else:
            raise ValueError('Validation of image against harbor reference failed.')


class AnalysisDelete(Analysis):
    image_registry_address: Optional[str]
    ports: Optional[list[int]]
    status: str = AnalysisStatus.RUNNING.value

    def __int__(
            self,
            analysis_id: str,
            name: str,
            database: Database,
    ) -> None:
        for pod_id in database.get_pod_ids(analysis_id):
            log = get_log(name, pod_id)
            # TODO: save final logs
        delete_deployment(name=name)
        self.status = AnalysisStatus.STOPPED.value
        database.delete_entry(analysis_id)
