import uuid
import time
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from src.status.constants import _MAX_RESTARTS, AnalysisStatus


class LogEntity(BaseModel):
    """A persisted log line with an id and ISO-ish timestamp."""

    log: str
    log_type: Literal['emerg', 'alert', 'crit', 'error', 'warn', 'notice', 'info', 'debug']

    id: str
    created_at: str

    def __str__(self) -> str:
        """Render the log entity as the string stored in the database column."""
        return f"LogEntity(id={self.id}, log={self.log}, log_type={self.log_type}, created_at={self.created_at})"


class CreateLogEntity(BaseModel):
    """Request body accepted by ``POST /po/stream_logs`` from analysis pods."""

    log: str
    log_type: Literal['emerg', 'alert', 'crit', 'error', 'warn', 'notice', 'info', 'debug']

    analysis_id: str
    status: str
    progress: int

    def to_log_entity(self) -> LogEntity:
        """Materialize a :class:`LogEntity` with a fresh uuid and timestamp."""
        return LogEntity(
            log=self.log,
            log_type=self.log_type,
            id=str(uuid.uuid4()),
            created_at=str(datetime.now())
        )


class CreateStartUpErrorLog(CreateLogEntity):
    """Pre-formatted error log emitted when an analysis fails to start.

    Covers three error categories: ``stuck`` (cannot reach node services),
    ``slow`` (exceeded startup budget), and ``k8s`` (Kubernetes deployment
    error). The message includes the current restart count and whether the
    analysis will be terminated.
    """

    def __init__(self,
                 restart_num: int,
                 error_type: Literal['stuck', 'slow', 'k8s'],
                 analysis_id: str,
                 status: str,
                 k8s_error_msg: str = '') -> None:
        """Build the error log message.

        Args:
            restart_num: Current restart counter (0-indexed attempt number).
            error_type: One of ``stuck``, ``slow``, ``k8s``.
            analysis_id: Analysis the log belongs to.
            status: Current analysis status to forward to the Hub.
            k8s_error_msg: Optional Kubernetes error reason appended for the
                ``k8s`` error type.
        """
        terminating = restart_num >= _MAX_RESTARTS
        term_msg = " -> Terminating analysis as failed." if terminating else ""
        if error_type == "stuck":
            log = (f"[flame -- POAPI: ANALYSISSTARTUP{'ERROR' if terminating else 'WARNING'} -- "
                   f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] "
                   f"The analysis failed to connect to other node components "
                   f"[restart {restart_num} of {_MAX_RESTARTS}].{term_msg}")
        elif error_type == "slow":
            log = (f"[flame -- POAPI: ANALYSISSTARTUP{'ERROR' if terminating else 'WARNING'} -- "
                   f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] "
                   f"The analysis took too long during startup and was restarted "
                   f"[restart {restart_num} of {_MAX_RESTARTS}].{term_msg}")
        elif error_type == "k8s":
            log = (f"[flame -- POAPI: ANALYSISSTARTUP{'ERROR' if terminating else 'WARNING'} -- "
                   f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] "
                   f"The analysis failed to deploy in kubernetes "
                   f"[restart {restart_num} of {_MAX_RESTARTS}].{term_msg}")
            if k8s_error_msg:
                log += f"\n\tKubernetesApiError: {k8s_error_msg}."
        else:
            log = ''

        super().__init__(log=log,
                         log_type="error" if terminating else "warn",
                         analysis_id=analysis_id,
                         status=status,
                         progress=0)


class AnalysisStoppedLog(CreateLogEntity):
    """Pre-formatted info log emitted whenever an analysis is stopped."""

    def __init__(self, analysis_id: str) -> None:
        """Build the stop log for ``analysis_id`` with status ``stopped``."""
        log = (f"[flame -- POAPI: ANALYSISSTOPPED -- "
               f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}] "
               f"Info: The analysis was stopped either locally, or externally on another node.")
        super().__init__(log=log,
                         log_type="info",
                         analysis_id=analysis_id,
                         status=AnalysisStatus.STOPPED.value,
                         progress=0)
