"""Status enums and timeout constants for the monitoring loop.

:class:`AnalysisStatus` is the canonical set of analysis states; the private
module constants bound how long the loop waits for an analysis to answer its
internal status endpoint and how often a stuck analysis may be restarted.
"""

from enum import Enum


_INTERNAL_STATUS_TIMEOUT = 60  # Time in seconds to wait for internal status response


_MAX_RESTARTS = 3  # Maximum number of restarts for a stuck analysis


class AnalysisStatus(Enum):
    """Canonical status values tracked for an analysis.

    Includes both persisted statuses (``STARTING``, ``STARTED``,
    ``EXECUTING``, ``EXECUTED``, ``STOPPED``, ``FAILED``) and the transient
    ``STUCK`` status that is only observed via the internal health endpoint.
    """

    STARTING = "starting"
    STARTED = "started"

    STUCK = "stuck"  # internal analysis status only

    STOPPING = "stopping"
    STOPPED = "stopped"

    EXECUTING = "executing"
    EXECUTED = "executed"
    FAILED = "failed"
