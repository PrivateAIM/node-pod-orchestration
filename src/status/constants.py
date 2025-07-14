from enum import Enum


class AnalysisStatus(Enum):
    STARTING = 'starting'
    STARTED = 'started'

    STUCK = 'stuck'
    RUNNING = 'running'

    STOPPING = 'stopping'
    STOPPED = 'stopped'

    FINISHED = 'finished'
    FAILED = 'failed'
