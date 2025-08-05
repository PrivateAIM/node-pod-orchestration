import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class LogEntity(BaseModel):
    log: str
    log_type: Literal["emerg", "alert", "crit", "error", "warn", "notice", "info", "debug"]

    id: str = str(uuid.uuid4())
    created_at: str = str(datetime.now())

    def __str__(self) -> str:
        return f"LogEntity(id={self.id}, log={self.log}, log_type={self.log_type}, created_at={self.created_at})"


class CreateLogEntity(BaseModel):
    log: str
    log_type: Literal["emerg", "alert", "crit", "error", "warn", "notice", "info", "debug"]

    analysis_id: str
    node_id: str
    status: str

    def to_log_entity(self) -> LogEntity:
        return LogEntity(log=self.log,
                         log_type=self.log_type)
