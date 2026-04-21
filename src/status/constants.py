from enum import Enum


_INTERNAL_STATUS_TIMEOUT = 10  # Time in seconds to wait for internal status response


_MAX_RESTARTS = 10  # Maximum number of restarts for a stuck analysis


class AnalysisStatus(Enum):
    """Canonical status values tracked for an analysis.

    Includes both persisted statuses (``STARTING``, ``STARTED``,
    ``EXECUTING``, ``EXECUTED``, ``STOPPED``, ``FAILED``) and the transient
    ``STUCK`` status that is only observed via the internal health endpoint.
    """

    STARTING = 'starting'
    STARTED = 'started'

    STUCK = 'stuck'         # internal analysis status only

    STOPPING = 'stopping'
    STOPPED = 'stopped'

    EXECUTING = 'executing'
    EXECUTED = 'executed'
    FAILED = 'failed'
