import time
import os
import asyncio
from typing import Literal, Optional

import flame_hub
from httpx import AsyncClient, HTTPStatusError, ConnectError

from src.resources.database.entity import Database
from src.resources.analysis.entity import Analysis, read_db_analysis
from src.resources.utils import delete_analysis, stop_analysis
from src.status.constants import AnalysisStatus


def status_loop(database: Database, status_loop_interval: int) -> None:
    """
    Send the status of the analysis to the HUB, kill deployment if analysis finished

    :return:
    """
    node_id = None
    node_analysis_ids = {}

    robot_id, robot_secret, hub_url_core, hub_auth = (os.getenv('HUB_ROBOT_USER'),
                                                      os.getenv('HUB_ROBOT_SECRET'),
                                                      os.getenv('HUB_URL_CORE'),
                                                      os.getenv('HUB_URL_AUTH'))

    try:
        hub_client = _get_hub_client(robot_id, robot_secret, hub_url_core, hub_auth)
    except Exception as e:
        hub_client = None
        print(f"Failed to authenticate with hub python client library.\n{e}")

    while True:
        if database.get_analysis_ids():
            if node_id is None:
                node_id = str(hub_client.find_nodes(filter={"robot_id": robot_id})[0].id)
            else:
                for analysis_id in set(database.get_analysis_ids()):
                    if analysis_id not in node_analysis_ids.keys():
                        node_analysis_id = str(hub_client.find_analysis_nodes(filter={"analysis_id": analysis_id,
                                                                                      "node_id": node_id})[0].id)
                        if node_analysis_id is not None:
                            node_analysis_ids[analysis_id] = node_analysis_id
                    else:
                        node_analysis_id = node_analysis_ids[analysis_id]

                    if node_analysis_id is not None:
                        deployments = [read_db_analysis(deployment)
                                       for deployment in database.get_deployments(analysis_id)]

                        db_status, int_status = (_get_status(deployments), _get_internal_status(deployments))

                        # update created to running status if deployment responsive
                        db_status = _update_running_status(analysis_id, database, db_status, int_status)

                        # update running to finished status if analysis finished
                        db_status = _update_finished_status(analysis_id, database, db_status, int_status)

                        _set_analysis_hub_status(hub_client,node_analysis_id, db_status, int_status)
        time.sleep(status_loop_interval)


def _get_hub_client(robot_id: str, robot_secret: str, hub_url_core: str, hub_auth: str) -> flame_hub.CoreClient:
    auth = flame_hub.auth.RobotAuth(robot_id=robot_id, robot_secret=robot_secret, base_url=hub_auth)
    return flame_hub.CoreClient(base_url=hub_url_core, auth=auth)


def _update_finished_status(analysis_id: str,
                            database: Database,
                            database_status: dict[str, dict[str, str]],
                            internal_status: dict[str, dict[str, Optional[str]]]) -> dict[str, dict[str, str]]:
    """
    update status of analysis in database from running to finished if deployment is finished
    and delete analysis
    #
    :param analysis_id:
    :param database:
    :param database_status:
    :param internal_status:
    :return:
    """
    deployments = [read_db_analysis(deployment)
                   for deployment in database.get_deployments(analysis_id)]
    running_deployment_names = [deployment.deployment_name
                                for deployment in deployments
                                if deployment.status in [AnalysisStatus.STARTED.value, AnalysisStatus.RUNNING.value]]

    newly_ended_deployment_names = [deployment_name
                                    for deployment_name in internal_status['status'].keys()
                                    if (deployment_name in running_deployment_names) and
                                    ((internal_status['status'][deployment_name] == AnalysisStatus.FINISHED.value) or
                                     (internal_status['status'][deployment_name] == AnalysisStatus.FAILED.value))]
    print(f"All deployments (name,db_status,internal_status): "
          f"{[(deployment.deployment_name, database_status['status'][deployment.deployment_name], internal_status['status'][deployment.deployment_name]) for deployment in deployments]}\n"
          f"Running deployments: {running_deployment_names}\n"
          f"Newly ended deployments: {newly_ended_deployment_names}")
    for deployment_name in newly_ended_deployment_names:
        intn_dpl_status = internal_status['status'][deployment_name]
        print(f"Attempt to update status to {intn_dpl_status}")
        database.update_deployment_status(deployment_name,
                                          AnalysisStatus.FINISHED.value
                                          if intn_dpl_status == AnalysisStatus.FINISHED.value
                                          else AnalysisStatus.FAILED.value)  # change database status
        if intn_dpl_status == 'finished':
            print("Delete deployment")
            # TODO: final local log save (minio?)  # archive logs
            delete_analysis(analysis_id, database)  # delete analysis from database
        else:
            print("Stop deployment")
            stop_analysis(analysis_id, database)  # stop analysis

    return database_status


def _update_running_status(analysis_id: str,
                           database: Database,
                           database_status: dict[str, dict[str, str]],
                           internal_status: dict[str, dict[str, Optional[str]]]) -> dict[str, dict[str, str]]:
    """
    update status of analysis in database from created to running if deployment is ongoing
    :param analysis_id:
    :param database:
    :param database_status:
    :param internal_status:
    :return:
    """
    deployments = [read_db_analysis(deployment)
                   for deployment in database.get_deployments(analysis_id)]
    newly_created_deployment_names = [deployment.deployment_name
                                      for deployment in deployments if deployment.status == AnalysisStatus.STARTED.value]

    running_deployment_names = [deployment_name
                                for deployment_name in internal_status['status'].keys()
                                if (deployment_name in newly_created_deployment_names) and
                                (internal_status['status'][deployment_name] == 'ongoing')]
    for deployment_name in running_deployment_names:
        database.update_deployment_status(deployment_name, AnalysisStatus.RUNNING.value)
        database_status = _get_status(deployments)

    return database_status


def _set_analysis_hub_status(hub_client: flame_hub.CoreClient,
                             node_analysis_id: str,
                             database_status: dict[str, dict[str, str]],
                             internal_status: dict[str, dict[str, Optional[str]]]) -> None:

    analysis_hub_status = None
    # get keys from database_status
    for deployment_name in database_status['status'].keys():
        db_depl_status = database_status['status'][deployment_name]
        try:
            intern_depl_status = internal_status['status'][deployment_name]
        except KeyError:
            intern_depl_status = None

        if intern_depl_status == AnalysisStatus.FAILED.value:
            analysis_hub_status = AnalysisStatus.FAILED.value
            break
        elif intern_depl_status == AnalysisStatus.FINISHED.value:
            analysis_hub_status = AnalysisStatus.FINISHED.value
            break
        elif intern_depl_status == 'ongoing':
            analysis_hub_status = AnalysisStatus.RUNNING.value
            break
        else:
            analysis_hub_status = db_depl_status
            break

    #_submit_analysis_status_update(node_analysis_id, analysis_hub_status)
    hub_client.update_analysis_node(node_analysis_id, run_status=analysis_hub_status)


# def _submit_analysis_status_update(node_analysis_id: str, status: AnalysisStatus) -> None:
#     """
#     update status of analysis at hub
#
#     POST https://core.privateaim.dev/analysis-nodes/3c895658-69f1-4fbe-b65c-768601b83f83
#     Payload { "run_status": "started" }
#     :return:
#     """
#     if status is not None:
#         try:
#             response = asyncio.run(AsyncClient(base_url=os.getenv('HUB_URL_CORE'),
#                                                headers={"accept": "application/json",
#                                                         "Authorization": f"Bearer {get_hub_token()['hub_token']}"})
#                                    .post(f'/analysis-nodes/{node_analysis_id}',
#                                          json={"run_status": status},
#                                          headers=[('Connection', 'close')]))
#
#             response.raise_for_status()
#         except (HTTPStatusError, ConnectError) as e:
#             print(f"Error updating analysis status: {e}")


def _get_status(deployments: list[Analysis]) -> dict[Literal['status'], dict[str, str]]:
    return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}


def _get_internal_status(deployments: list[Analysis]) \
        -> dict[Literal['status'], dict[str, Optional[Literal['finished', 'ongoing', 'failed']]]]:
    return {"status": {deployment.deployment_name: asyncio.run(_get_internal_deployment_status(deployment.deployment_name))
                       for deployment in deployments}}


async def _get_internal_deployment_status(deployment_name: str) -> Optional[Literal['finished', 'ongoing', 'failed']]:
    try:
        response = await (AsyncClient(base_url=f'http://nginx-{deployment_name}:80')
                          .get('/analysis/healthz', headers=[('Connection', 'close')]))
        try:
            response.raise_for_status()
        except HTTPStatusError as e:
            print(f"Error getting internal deployment status: {e}")
            return None

        analysis_health_status = response.json()['status']
        if analysis_health_status == AnalysisStatus.FINISHED.value:
            health_status = AnalysisStatus.FINISHED.value
        elif analysis_health_status == 'ongoing':
            health_status = 'ongoing'
        else:
            health_status = AnalysisStatus.FAILED.value
        return health_status

    except ConnectError as e:
        print(f"Connection to http://nginx-{deployment_name}:80 yielded an error: {e}")
        return None
