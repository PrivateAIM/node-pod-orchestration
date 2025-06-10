from enum import Enum


class AnalysisStatus(Enum):
    STARTING = 'starting'
    STARTED = 'started'

    STOPPING = 'stopping'
    STOPPED = 'stopped'

    STUCK = 'stuck'

    RUNNING = 'running'
    FINISHED = 'finished'

    FAILED = 'failed'
