from enum import Enum


_INTERNAL_STATUS_TIMEOUT = 10  # Time in seconds to wait for internal status response


_MAX_RESTARTS = 10  # Maximum number of restarts for a stuck analysis


class AnalysisStatus(Enum):
    STARTING = 'starting'
    STARTED = 'started'

    STUCK = 'stuck'
    RUNNING = 'running'

    STOPPING = 'stopping'
    STOPPED = 'stopped'

    FINISHED = 'finished'
    FAILED = 'failed'
