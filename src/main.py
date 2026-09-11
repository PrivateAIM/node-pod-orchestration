"""Service entry point.

Wires together the three startup concerns of the Pod Orchestration service:
loading the in-cluster Kubernetes configuration and ``.env`` overrides,
initializing the PostgreSQL schema, and launching the two long-running
threads -- the FastAPI server and the background status monitoring loop.
"""

import os
from threading import Thread
from dotenv import load_dotenv, find_dotenv

from src.resources.database.entity import Database
from src.api.api import PodOrchestrationAPI
from src.k8s.utils import get_current_namespace, load_cluster_config
from src.status.status import status_loop
from src.utils.po_logging import get_logger


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
    if not os.getenv("NGINX_IMAGE"):
        logger.warning(
            "Environment variable 'NGINX_IMAGE' is not set, defaulting to "
            "'nginxinc/nginx-unprivileged:1.31.4-alpine-perl'."
        )

    # init database
    database = Database()
    namespace = get_current_namespace()
    api_thread = Thread(
        target=start_po_api, kwargs={"database": database, "namespace": namespace}
    )
    api_thread.start()

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
    PodOrchestrationAPI(database, namespace)


if __name__ == "__main__":
    logger.info("Starting server")
    main()
