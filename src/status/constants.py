from enum import Enum


class AnalysisHubStatus(Enum):
    STARTING = 'starting'
    STARTED = 'started'

    STOPPING = 'stopping'
    STOPPED = 'stopped'

    RUNNING = 'running'
    FINISHED = 'finished'

    FAILED = 'failed'
