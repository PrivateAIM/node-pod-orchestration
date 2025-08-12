import time
import os
import asyncio
from typing import Literal, Optional
from httpx import AsyncClient, HTTPStatusError, ConnectError, ConnectTimeout

import flame_hub

from src.resources.database.entity import Database
from src.resources.analysis.entity import Analysis, read_db_analysis
from src.utils.hub_client import (init_hub_client_with_robot,
                                  get_node_id_by_robot,
                                  get_node_analysis_id,
                                  update_hub_status,
                                  send_log_line_to_hub)
from src.resources.utils import (unstuck_analysis_deployments,
                                 stop_analysis,
                                 delete_analysis,
                                 retrieve_logs)
from src.status.constants import AnalysisStatus
from src.utils.other import split_logs
from src.utils.token import get_keycloak_token


_MAX_RESTARTS = 10  # Maximum number of restarts for a stuck analysis


def status_loop(database: Database, status_loop_interval: int) -> None:
    """
    Send the status of the analysis to the HUB, kill deployment if analysis finished

    :return:
    """
    hub_client = None
    node_analysis_ids = {}
    latest_analysis_logs = {}

    robot_id, robot_secret, hub_url_core, hub_auth, http_proxy, https_proxy = (os.getenv('HUB_ROBOT_USER'),
                                                                               os.getenv('HUB_ROBOT_SECRET'),
                                                                               os.getenv('HUB_URL_CORE'),
                                                                               os.getenv('HUB_URL_AUTH'),
                                                                               os.getenv('PO_HTTP_PROXY'),
                                                                               os.getenv('PO_HTTPS_PROXY'))
    analysis_restart_counter = {}
    # Enter lifecycle loop
    while True:
        if hub_client is None:
            hub_client = init_hub_client_with_robot(robot_id,
                                                    robot_secret,
                                                    hub_url_core,
                                                    hub_auth,
                                                    http_proxy,
                                                    https_proxy)
        else:
            node_id = get_node_id_by_robot(hub_client, robot_id)
            # Catch unresponsive hub client
            if node_id is None:
                print("Resetting hub client...")
                hub_client = None
                continue
            # If running analyzes exist, enter status loop
            print(f"Checking for running analyzes...{database.get_analysis_ids()}")
            if database.get_analysis_ids():
                for analysis_id in set(database.get_analysis_ids()):
                    if analysis_id not in node_analysis_ids.keys():
                        node_analysis_id = get_node_analysis_id(hub_client, analysis_id, node_id)
                        if node_analysis_id is not None:
                            node_analysis_ids[analysis_id] = node_analysis_id
                    else:
                        node_analysis_id = node_analysis_ids[analysis_id]
                    print(f"Node analysis id: {node_analysis_id}")
                    if node_analysis_id:
                        deployments = [read_db_analysis(deployment)
                                       for deployment in database.get_deployments(analysis_id)]

                        db_status = _get_status(deployments)
                        int_status = _get_internal_status(deployments, analysis_id)
                        print(f"Database status: {db_status}")
                        print(f"Internal status: {int_status}")

                        # fix for stuck analyzes
                        db_status, analysis_restart_counter =_fix_stuck_status(analysis_id,
                                                                               database,
                                                                               analysis_restart_counter,
                                                                               db_status,
                                                                               int_status)
                        print(f"Unstuck analysis with internal stuck status: {int_status}")

                        # update created to running status if deployment responsive
                        db_status = _update_running_status(analysis_id, database, db_status, int_status)
                        print(f"Update created to running database status: {db_status}")

                        # update running to finished status if analysis finished
                        db_status, analysis_restart_counter = _update_finished_status(analysis_id,
                                                                                      database,
                                                                                      analysis_restart_counter,
                                                                                      db_status,
                                                                                      int_status)
                        print(f"Update running to finished database status: {db_status}")

                        # update hub analysis status
                        analysis_hub_status = _set_analysis_hub_status(hub_client, node_analysis_id, db_status, int_status)
                        print(f"Set Hub analysis status with node_analysis={node_analysis_id}, db_status={db_status}, "
                              f"internal_status={int_status}")

                        # create hub analysis logs
                        # latest_analysis_logs[analysis_id] = _set_analysis_hub_logs(hub_client,
                        #                                                            analysis_id,
                        #                                                            node_id,
                        #                                                            database,
                        #                                                            analysis_hub_status,
                        #                                                            latest_analysis_logs[analysis_id] if analysis_id in latest_analysis_logs.keys() else [])
                        # print(f"Create Hub analysis logs with analysis_id={analysis_id}, node_id={node_id}, "
                        #       f"status={analysis_hub_status}")

            time.sleep(status_loop_interval)
            print(f"Status loop iteration completed. Sleeping for {status_loop_interval} seconds.")


def _get_status(deployments: list[Analysis]) -> dict[Literal['status'], dict[str, str]]:
    return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}


def _get_internal_status(deployments: list[Analysis], analysis_id: str) \
        -> dict[Literal['status'], dict[str, Optional[str]]]:
    return {"status": {deployment.deployment_name:
                           asyncio.run(_get_internal_deployment_status(deployment.deployment_name, analysis_id))
                       for deployment in deployments}}


async def _get_internal_deployment_status(deployment_name: str, analysis_id: str) -> Optional[str]:
    try:
        response = await (AsyncClient(base_url=f'http://nginx-{deployment_name}:80')
                          .get('/analysis/healthz', headers=[('Connection', 'close')]))
        try:
            response.raise_for_status()
        except HTTPStatusError as e:
            print(f"Error getting internal deployment status: {e}")
            return AnalysisStatus.FAILED.value

        analysis_health_status, analysis_token_remaining_time = (response.json()['status'],
                                                                 response.json()['token_remaining_time'])
        await _refresh_keycloak_token(deployment_name=deployment_name,
                                      analysis_id=analysis_id,
                                      token_remaining_time=analysis_token_remaining_time)

        if analysis_health_status == AnalysisStatus.FINISHED.value:
            health_status = AnalysisStatus.FINISHED.value
        elif analysis_health_status == AnalysisStatus.RUNNING.value:
            health_status = AnalysisStatus.RUNNING.value
        else:
            health_status = AnalysisStatus.FAILED.value
        return health_status

    except ConnectError  as e:
        print(f"Connection to http://nginx-{deployment_name}:80 yielded an error: {e}")
        return None
    except ConnectTimeout as e:
        print(f"Connection to http://nginx-{deployment_name}:80 timed out: {e}")
        return None


async def _refresh_keycloak_token(deployment_name: str, analysis_id: str, token_remaining_time: int) -> None:
    """
    Refresh the keycloak token
    :return:
    """
    if token_remaining_time < (int(os.getenv('STATUS_LOOP_INTERVAL')) * 2 + 1):
        keycloak_token = get_keycloak_token(analysis_id)
        try:
            response = await (AsyncClient(base_url=f'http://nginx-{deployment_name}:80')
                              .post('/analysis/token_refresh',
                                    json={"token": keycloak_token},
                                    headers=[('Connection', 'close')]))
            response.raise_for_status()
        except HTTPStatusError as e:
            print(f"Failed to refresh keycloak token in deployment {deployment_name}.\n{e}")


def _fix_stuck_status(analysis_id: str,
                      database: Database,
                      analysis_restart_counter: dict[str, int],
                      db_status: dict[str, dict[str, str]],
                      internal_status: dict[str, dict[str, Optional[str]]]) -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    stuck_deployment_names = [deployment_name
                              for deployment_name in internal_status['status'].keys()
                              if internal_status['status'][deployment_name] in [AnalysisStatus.STUCK.value]]
    slow_deployment_names = [deployment_name
                             for deployment_name in internal_status['status'].keys()
                             if (internal_status['status'][deployment_name] in [AnalysisStatus.FAILED.value]) and
                             (db_status['status'][deployment_name] in [AnalysisStatus.STARTED.value])]
    stuck_deployment_names.extend(slow_deployment_names)
    for stuck_deployment_name in stuck_deployment_names:
        database.update_deployment_status(stuck_deployment_name, status=AnalysisStatus.STUCK.value)

    if analysis_id not in analysis_restart_counter.keys():
        analysis_restart_counter[analysis_id] = 0
    analysis_restart_counter[analysis_id] += 1
    if analysis_restart_counter[analysis_id] < _MAX_RESTARTS:
        unstuck_analysis_deployments(analysis_id, database)
    else:
        database.update_deployment_status(database.get_deployments(analysis_id)[-1].deployment_name,
                                          status=AnalysisStatus.FAILED.value)

    # update database status
    deployments = [read_db_analysis(deployment)
                   for deployment in database.get_deployments(analysis_id)]
    database_status = _get_status(deployments)

    return database_status, analysis_restart_counter

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
    newly_running_deployment_names = [deployment_name
                                      for deployment_name in database_status['status'].keys()
                                      if (database_status['status'][deployment_name] in [AnalysisStatus.STARTED.value])
                                      and (internal_status['status'][deployment_name] in [AnalysisStatus.RUNNING.value])]

    for deployment_name in newly_running_deployment_names:
        database.update_deployment_status(deployment_name, AnalysisStatus.RUNNING.value)

    # update database status
    deployments = [read_db_analysis(deployment)
                   for deployment in database.get_deployments(analysis_id)]
    database_status = _get_status(deployments)

    return database_status


def _update_finished_status(analysis_id: str,
                            database: Database,
                            analysis_restart_counter: dict[str, int],
                            database_status: dict[str, dict[str, str]],
                            internal_status: dict[str, dict[str, Optional[str]]]) \
        -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    """
    update status of analysis in database from running to finished if deployment is finished
    and delete analysis
    #
    :param analysis_id:
    :param database:
    :param analysis_restart_counter:
    :param database_status:
    :param internal_status:
    :return:
    """
    newly_ended_deployment_names = [deployment_name
                                    for deployment_name in database_status['status'].keys()
                                    if (database_status['status'][deployment_name] in [AnalysisStatus.RUNNING.value,
                                                                                       AnalysisStatus.FAILED.value])
                                    and (internal_status['status'][deployment_name] in [AnalysisStatus.FINISHED.value,
                                                                                        AnalysisStatus.FAILED.value,
                                                                                        AnalysisStatus.STUCK.value])
                                   ]
    for deployment_name in newly_ended_deployment_names:
        del analysis_restart_counter[analysis_id]  # remove analysis from restart counter
        intn_dpl_status = internal_status['status'][deployment_name]
        print(f"Attempt to update status to {intn_dpl_status}")
        database.update_deployment_status(deployment_name,
                                          AnalysisStatus.FINISHED.value
                                          if intn_dpl_status == AnalysisStatus.FINISHED.value
                                          else AnalysisStatus.FAILED.value)  # change database status
        if intn_dpl_status == AnalysisStatus.FINISHED.value:
            print("Delete deployment")
            # TODO: final local log save (minio?)  # archive logs
            # delete_analysis(analysis_id, database)  # delete analysis from database
            stop_analysis(analysis_id, database)  # stop analysis TODO: Change to delete in the future (when archive logs implemented)
        else:
            print("Stop deployment")
            stop_analysis(analysis_id, database)  # stop analysis

        # update database status
        deployments = [read_db_analysis(deployment)
                       for deployment in database.get_deployments(analysis_id)]
        database_status = _get_status(deployments)

    return database_status, analysis_restart_counter


def _set_analysis_hub_status(hub_client: flame_hub.CoreClient,
                             node_analysis_id: str,
                             database_status: dict[str, dict[str, str]],
                             internal_status: dict[str, dict[str, Optional[str]]]) -> str:
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

    update_hub_status(hub_client, node_analysis_id, analysis_hub_status)
    return analysis_hub_status


def _set_analysis_hub_logs(hub_client: flame_hub.CoreClient,
                           analysis_id: str,
                           node_id: str,
                           database: Database,
                           status: str,
                           latest_logs: dict[str, list[str]]) -> dict[str, list[str]]:
    analysis_logs = retrieve_logs(analysis_id, database)["analysis"]

    log_dict = split_logs(analysis_logs)

    for log_type, log in log_dict.keys():
        for line in log.split('\n'):
            if line not in latest_logs[log_type]:
                send_log_line_to_hub(hub_client=hub_client,
                                     analysis_id=analysis_id,
                                     node_id=node_id,
                                     status=status,
                                     log_type=log_type,
                                     log_line=line)
                latest_logs[log_type].append(line)

    return latest_logs
