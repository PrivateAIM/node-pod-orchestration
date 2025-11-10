import uuid
import time
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from src.status.constants import _MAX_RESTARTS


class LogEntity(BaseModel):
    log: str
    log_type: Literal['emerg', 'alert', 'crit', 'error', 'warn', 'notice', 'info', 'debug']

    id: str = str(uuid.uuid4())
    created_at: str = str(datetime.now())

    def __str__(self) -> str:
        return f"LogEntity(id={self.id}, log={self.log}, log_type={self.log_type}, created_at={self.created_at})"


class CreateLogEntity(BaseModel):
    log: str
    log_type: Literal['emerg', 'alert', 'crit', 'error', 'warn', 'notice', 'info', 'debug']

    analysis_id: str
    status: str
    progress: int

    def to_log_entity(self) -> LogEntity:
        return LogEntity(log=self.log,
                         log_type=self.log_type)


class CreateStartUpErrorLog(CreateLogEntity):
    def __init__(self,
                 restart_num: int,
                 error_type: Literal["stuck", "slow", "k8s"],
                 analysis_id: str,
                 status: str,
                 k8s_error_msg: str = '') -> None:
        term_msg = "" if restart_num < _MAX_RESTARTS else " -> Terminating analysis as failed."
        if error_type == "stuck":
            log = (f"[flame -- POAPI: ANALYSISSTARTUPERROR -- "
                   f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] "
                   f"Error: The analysis failed to connect to other node components "
                   f"[restart {restart_num} of {_MAX_RESTARTS}].{term_msg}")
        elif error_type == "slow":
            log = (f"[flame -- POAPI: ANALYSISSTARTUPERROR -- "
                   f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] "
                   f"Error: The analysis took to long during startup and was restarted "
                   f"[restart {restart_num} of {_MAX_RESTARTS}].{term_msg}")
        elif error_type == "k8s":
            log = (f"[flame -- POAPI: ANALYSISSTARTUPERROR -- "
                   f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] "
                   f"Error: The analysis failed to deploy in kubernetes "
                   f"[restart {restart_num} of {_MAX_RESTARTS}].{term_msg}")
            if k8s_error_msg:
                log += f"\n\tKubernetesApiError: {k8s_error_msg}."
        else:
            log = ''

        super().__init__(log=log, log_type="error", analysis_id=analysis_id, status=status)
