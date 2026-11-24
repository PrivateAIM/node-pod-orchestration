"""Service entry point.

Wires together the three startup concerns of the Pod Orchestration service:
loading the in-cluster Kubernetes configuration and ``.env`` overrides,
initializing the PostgreSQL schema, and launching the two long-running
threads -- the FastAPI server and the background status monitoring loop.
"""

import os
from threading import Thread
from dotenv import load_dotenv, find_dotenv

from flame_po import __version__
from flame_po.resources.database.entity import Database
from flame_po.api.api import PodOrchestrationAPI
from flame_po.k8s.kubernetes import DEFAULT_NGINX_IMAGE
from flame_po.k8s.utils import get_current_namespace, load_cluster_config
from flame_po.status.status import status_loop
from flame_po.utils.po_logging import get_logger


# connect logger
logger = get_logger()
# load cluster config
load_cluster_config()
# load env
load_dotenv(find_dotenv())


def main():
    """Entry point for the Pod Orchestration service.

    Loads the in-cluster Kubernetes configuration, initializes the database,
    spawns the FastAPI server in a background thread, and starts the blocking
    status monitoring loop on the main thread.
    """
    if not bool(os.getenv("NGINX_IMAGE")):
        logger.warning(f"Environment variable 'NGINX_IMAGE' is not set, defaulting to '{DEFAULT_NGINX_IMAGE}'.")

    # init database
    database = Database()
    namespace = get_current_namespace()
    api_thread = Thread(
        target=start_po_api, kwargs={"database": database, "namespace": namespace}
    )
    api_thread.start()

    logger.info("Initializing PO status loop.")
    # start status loop
    status_loop(
        database, int(os.getenv("STATUS_LOOP_INTERVAL", "10")), namespace=namespace
    )


def start_po_api(database: Database, namespace: str):
    """Instantiate and run the Pod Orchestration FastAPI server.

    Args:
        database: Initialized database wrapper used by the API for persistence.
        namespace: Kubernetes namespace the API will operate within.
    """
    logger.info(f"Starting PO API server on {namespace}.")
    PodOrchestrationAPI(database, namespace)


if __name__ == "__main__":
    logger.info(f"Starting Flame Pod-Orchestrator v{__version__}")
    main()
