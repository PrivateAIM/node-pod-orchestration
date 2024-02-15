from enum import Enum


class AnalysisStatus(Enum):
    CREATED = 'created'
    RUNNING = 'running'
    STOPPED = 'stopped'
