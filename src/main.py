import os
from threading import Thread

from dotenv import load_dotenv, find_dotenv

from src.resources.database.entity import Database
from src.api.api import PodOrchestrationAPI
from src.k8s.kubernetes import load_cluster_config
from src.status.status import status_loop


def main():
    # load env
    load_dotenv(find_dotenv())

    # load cluster config
    load_cluster_config()

    # init database
    database = Database()

    api_thread = Thread(target=start_po_api, kwargs={'database': database})
    api_thread.start()

    # start status loop
    status_loop(database, os.getenv('STATUS_LOOP_INTERVAL', 10))


def start_po_api(database: Database):
    PodOrchestrationAPI(database)


if __name__ == '__main__':
    print("Starting server")
    main()
