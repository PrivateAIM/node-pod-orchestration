import os
from threading import Thread

from dotenv import load_dotenv, find_dotenv

from src.resources.database.entity import Database
from src.api.api import PodOrchestrationAPI
from src.k8s.kubernetes import load_cluster_config
from src.k8s.utils import get_current_namespace
from src.status.status import status_loop


def main():
    # load env
    load_dotenv(find_dotenv())

    # load cluster config
    load_cluster_config()

    # init database
    database = Database()

    print("in main script:", {'namespace': get_current_namespace()})
    api_thread = Thread(target=start_po_api, kwargs={'database': database, 'namespace': get_current_namespace()})
    api_thread.start()

    # start status loop
    if not os.getenv('STATUS_LOOP_INTERVAL'):
        os.environ['STATUS_LOOP_INTERVAL'] = '10'
    status_loop(database, int(os.getenv('STATUS_LOOP_INTERVAL')))


def start_po_api(database: Database, namespace: str):
    PodOrchestrationAPI(database, namespace)


if __name__ == '__main__':
    print("Starting server")
    main()
