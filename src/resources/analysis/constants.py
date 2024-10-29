from enum import Enum


class AnalysisStatus(Enum):
    PENDING = 'pending'
    CREATED = 'created'
    RUNNING = 'running'
    STOPPED = 'stopped'
    FINISHED = 'finished'
