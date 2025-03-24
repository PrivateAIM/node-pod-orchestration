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
from src.utils.token import get_keycloak_token

def status_loop(database: Database, status_loop_interval: int) -> None:
    """
    Send the status of the analysis to the HUB, kill deployment if analysis finished

    :return:
    """
    node_id = None
    hub_client = None
    node_analysis_ids = {}

    robot_id, robot_secret, hub_url_core, hub_auth = (os.getenv('HUB_ROBOT_USER'),
                                                      os.getenv('HUB_ROBOT_SECRET'),
                                                      os.getenv('HUB_URL_CORE'),
                                                      os.getenv('HUB_URL_AUTH'))
    while True:
        if not hub_client:
            # Attempt to init hub client
            try:
                hub_client = _get_hub_client(robot_id, robot_secret, hub_url_core, hub_auth)
                print("Hub client init successful")
            except Exception as e:
                hub_client = None
                print(f"Failed to authenticate with hub python client library.\n{e}")
        else:
            if database.get_analysis_ids():
                if node_id is None:
                    try:
                        node_id = str(hub_client.find_nodes(filter={"robot_id": robot_id})[0].id)
                        continue
                    except HTTPStatusError as e:
                        # TODO: Address this in hub python client
                        print(f"Error in hub python client whilst retrieving node id!\n{e}")
                        node_id = None
                else:
                    for analysis_id in set(database.get_analysis_ids()):
                        if analysis_id not in node_analysis_ids.keys():
                            try:
                                node_analyzes = hub_client.find_analysis_nodes(filter={"analysis_id": analysis_id,
                                                                                       "node_id": node_id})
                            except HTTPStatusError as e:
                                # TODO: Address this in hub python client
                                print(f"Error in hub python client whilst retrieving node analysis id!\n{e}")
                                node_analyzes = None
                            if node_analyzes:
                                node_analysis_id = str(node_analyzes[0].id)
                            else:
                                node_analysis_id = None

                            if node_analysis_id:
                                node_analysis_ids[analysis_id] = node_analysis_id
                        else:
                            node_analysis_id = node_analysis_ids[analysis_id]

                        if node_analysis_id:
                            deployments = [read_db_analysis(deployment)
                                           for deployment in database.get_deployments(analysis_id)]

                            db_status, int_status = (_get_status(deployments),
                                                     _get_internal_status(deployments, analysis_id))

                            # update created to running status if deployment responsive
                            db_status = _update_running_status(analysis_id, database, db_status, int_status)

                            # update running to finished status if analysis finished
                            db_status = _update_finished_status(analysis_id, database, db_status, int_status)

                            _set_analysis_hub_status(hub_client, node_analysis_id, db_status, int_status)
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
    for deployment_name in newly_ended_deployment_names:
        intn_dpl_status = internal_status['status'][deployment_name]
        print(f"Attempt to update status to {intn_dpl_status}")
        database.update_deployment_status(deployment_name,
                                          AnalysisStatus.FINISHED.value
                                          if intn_dpl_status == AnalysisStatus.FINISHED.value
                                          else AnalysisStatus.FAILED.value)  # change database status
        if intn_dpl_status == AnalysisStatus.FINISHED.value:
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
                                      for deployment in deployments
                                      if deployment.status == AnalysisStatus.STARTED.value]

    running_deployment_names = [deployment_name
                                for deployment_name in internal_status['status'].keys()
                                if (deployment_name in newly_created_deployment_names) and
                                (internal_status['status'][deployment_name] == AnalysisStatus.RUNNING.value)]
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
        elif intern_depl_status == AnalysisStatus.RUNNING.value:
            analysis_hub_status = AnalysisStatus.RUNNING.value
            break
        else:
            analysis_hub_status = db_depl_status
            break

    hub_client.update_analysis_node(node_analysis_id, run_status=analysis_hub_status)


def _get_status(deployments: list[Analysis]) -> dict[Literal['status'], dict[str, str]]:
    return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}


def _get_internal_status(deployments: list[Analysis], analysis_id: str) \
        -> dict[Literal['status'], dict[str, Optional[str]]]:
    return {"status": {deployment.deployment_name:
                           asyncio.run(_get_internal_deployment_status(deployment.deployment_name,
                                                                       analysis_id))
                       for deployment in deployments}}


async def _get_internal_deployment_status(deployment_name: str, analysis_id: str) -> Optional[str]:
    try:
        response = await (AsyncClient(base_url=f'http://nginx-{deployment_name}:80')
                          .get('/analysis/healthz', headers=[('Connection', 'close')]))
        try:
            response.raise_for_status()
        except HTTPStatusError as e:
            print(f"Error getting internal deployment status: {e}")
            return None

        analysis_health_status, analysis_token_remaining_time = (response.json()['status'],
                                                                 response.json()['token_remaining_time'])
        await refresh_keycloak_token(deployment_name=deployment_name,
                                     analysis_id=analysis_id,
                                     token_remaining_time=analysis_token_remaining_time)

        if analysis_health_status == AnalysisStatus.FINISHED.value:
            health_status = AnalysisStatus.FINISHED.value
        elif analysis_health_status == AnalysisStatus.RUNNING.value:
            health_status = AnalysisStatus.RUNNING.value
        else:
            health_status = AnalysisStatus.FAILED.value
        return health_status

    except ConnectError as e:
        print(f"Connection to http://nginx-{deployment_name}:80 yielded an error: {e}")
        return None

async def refresh_keycloak_token(deployment_name: str, analysis_id: str, token_remaining_time: int) -> None:
    """
    Refresh the keycloak token
    :return:
    """
    if token_remaining_time < (int(os.getenv('STATUS_LOOP_INTERVAL')) * 2 + 1):
        keycloak_token = get_keycloak_token(analysis_id)
        try:
            response = await (AsyncClient(base_url=f'http://nginx-{deployment_name}:80')
                              .post('/analysis/token_refresh',
                                    data={"token": keycloak_token},
                                    headers=[('Connection', 'close')]))
            response.raise_for_status()
        except HTTPStatusError as e:
            print(f"Failed to refresh keycloak token in deployment {deployment_name}.\n{e}")
            return None
