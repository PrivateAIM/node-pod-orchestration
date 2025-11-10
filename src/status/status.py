import time
import os
import asyncio
from typing import Optional
from httpx import AsyncClient, HTTPStatusError, ConnectError, ConnectTimeout

import flame_hub

from src.k8s.kubernetes import PORTS
from src.resources.database.entity import Database, AnalysisDB
from src.utils.hub_client import (init_hub_client_with_robot,
                                  get_node_id_by_robot,
                                  get_node_analysis_id,
                                  update_hub_status)
from src.resources.utils import (unstuck_analysis_deployments,
                                 stop_analysis,
                                 delete_analysis,
                                 stream_logs)
from src.resources.log.entity import CreateStartUpErrorLog
from src.k8s.kubernetes import get_pod_status
from src.status.constants import AnalysisStatus
from src.utils.token import get_keycloak_token
from src.status.constants import _MAX_RESTARTS, _INTERNAL_STATUS_TIMEOUT


def status_loop(database: Database, status_loop_interval: int) -> None:
    """
    Send the status of the analysis to the HUB, kill deployment if analysis finished

    :return:
    """
    hub_client = None
    node_id = None
    node_analysis_ids = {}

    robot_id, robot_secret, hub_url_core, hub_auth, http_proxy, https_proxy = (os.getenv('HUB_ROBOT_USER'),
                                                                               os.getenv('HUB_ROBOT_SECRET'),
                                                                               os.getenv('HUB_URL_CORE'),
                                                                               os.getenv('HUB_URL_AUTH'),
                                                                               os.getenv('PO_HTTP_PROXY'),
                                                                               os.getenv('PO_HTTPS_PROXY'))
    # Enter lifecycle loop
    while True:
        if hub_client is None:
            hub_client = init_hub_client_with_robot(robot_id,
                                                    robot_secret,
                                                    hub_url_core,
                                                    hub_auth,
                                                    http_proxy,
                                                    https_proxy)
            node_id = get_node_id_by_robot(hub_client, robot_id)
            # Catch unresponsive hub client
            if node_id is None:
                print("PO ACTION - Resetting hub client...")
                hub_client = None
                continue
        else:
            # If running analyzes exist, enter status loop
            running_analyzes = [analysis_id for analysis_id in database.get_analysis_ids()
                                if database.analysis_is_running(analysis_id)]
            print(f"PO ACTION - Checking for running analyzes...{running_analyzes}")
            if running_analyzes:
                for analysis_id in running_analyzes:
                    print(f"PO STATUS LOOP - Current analysis id: {analysis_id}")
                    # Get node analysis id
                    if analysis_id not in node_analysis_ids.keys():
                        node_analysis_id = get_node_analysis_id(hub_client, analysis_id, node_id)
                        if node_analysis_id is not None:
                            node_analysis_ids[analysis_id] = node_analysis_id
                        else:
                            hub_client = None
                    else:
                        node_analysis_id = node_analysis_ids[analysis_id]

                    # If node analysis id found
                    print(f"\tNode analysis id: {node_analysis_id}")
                    if node_analysis_id is not None:
                        # Retrieve analysis status (skip iteration if analysis is not deployed)
                        analysis_status = _get_analysis_status(analysis_id, database)
                        if analysis_status is None:
                            continue
                        print(f"\tDatabase status: {analysis_status['db_status']}")
                        print(f"\tInternal status: {analysis_status['int_status']}")

                        # Fix stuck analyzes
                        if analysis_status['status_action'] == 'unstuck':
                            print(f"\tUnstuck analysis with internal status: {analysis_status['int_status']}")
                            _fix_stuck_status(database, analysis_status, node_id, hub_client)
                            # Update analysis status (skip iteration if analysis is not deployed)
                            analysis_status = _get_analysis_status(analysis_id, database)
                            if analysis_status is None:
                                continue

                        # Update created to running status
                        if analysis_status['status_action'] == 'running':
                            print(f"\tUpdate created-to-running database status: {analysis_status['db_status']}")
                            _update_running_status(database, analysis_status)
                            # Update analysis status (skip iteration if analysis is not deployed)
                            analysis_status = _get_analysis_status(analysis_id, database)
                            if analysis_status is None:
                                continue

                        # Update running to finished status
                        if analysis_status['status_action'] == 'finishing':
                            print(f"\tUpdate running-to-finished database status: {analysis_status['db_status']}")
                            _update_finished_status(database, analysis_status)
                            # Update analysis status (skip iteration if analysis is not deployed)
                            analysis_status = _get_analysis_status(analysis_id, database)
                            if analysis_status is None:
                                continue

                        # Submit analysis_status to hub
                        analysis_hub_status = _set_analysis_hub_status(hub_client, node_analysis_id, analysis_status)
                        print(f"\tSet Hub analysis status with node_analysis={node_analysis_id}, "
                              f"db_status={analysis_status['db_status']}, "
                              f"internal_status={analysis_status['int_status']} "
                              f"to {analysis_hub_status}")

            time.sleep(status_loop_interval)
            print(f"PO STATUS LOOP - Status loop iteration completed. Sleeping for {status_loop_interval} seconds.")

def _get_analysis_status(analysis_id: str, database: Database) -> Optional[dict[str, str]]:
    analysis = database.get_latest_deployment(analysis_id)
    if analysis is not None:
        db_status = analysis.status
        # Make the Finished status final, the internal status is not checked anymore,
        # because the analysis will already be deleted
        if db_status == AnalysisStatus.FINISHED.value:
            int_status = AnalysisStatus.FINISHED.value
        else:
            int_status = asyncio.run(_get_internal_deployment_status(analysis.deployment_name, analysis_id))
        return {'analysis_id': analysis_id,
                'db_status': analysis.status,
                'int_status': int_status,
                'status_action': _decide_status_action(analysis.status, int_status)}
    else:
        return None


def _decide_status_action(db_status: str, int_status: str) -> Optional[str]:
    is_stuck = int_status == AnalysisStatus.STUCK.value
    is_slow = ((db_status in [AnalysisStatus.STARTED.value]) and (int_status in [AnalysisStatus.FAILED.value]))
    newly_running = ((db_status in [AnalysisStatus.STARTED.value]) and (int_status in [AnalysisStatus.RUNNING.value]))
    speedy_finished = ((db_status in [AnalysisStatus.STARTED.value]) and (int_status in [AnalysisStatus.FINISHED.value]))
    newly_ended = ((db_status in [AnalysisStatus.RUNNING.value, AnalysisStatus.FAILED.value])
                   and (int_status in [AnalysisStatus.FINISHED.value, AnalysisStatus.FAILED.value]))
    firmly_stuck = ((db_status in [AnalysisStatus.FAILED.value]) and (int_status in [AnalysisStatus.STUCK.value]))
    if is_stuck or is_slow:
        return 'unstuck'
    elif newly_running:
        return 'running'
    elif speedy_finished or newly_ended or firmly_stuck:
        return 'finishing'
    else:
        return None


async def _get_internal_deployment_status(deployment_name: str, analysis_id: str) -> str:
    # Attempt to retrieve internal analysis status via health endpoint
    start_time = time.time()
    while True:
        try:
            response = await (AsyncClient(base_url=f"http://nginx-{deployment_name}:{PORTS['nginx'][0]}")
                              .get("/analysis/healthz", headers=[('Connection', 'close')]))
            response.raise_for_status()
            break
        except HTTPStatusError as e:
            print(f"\tError whilst retrieving internal deployment status: {e}")
        except ConnectError as e:
            print(f"\tConnection to http://nginx-{deployment_name}:{PORTS['nginx'][0]} yielded an error: {e}")
        except ConnectTimeout as e:
            print(f"\tConnection to http://nginx-{deployment_name}:{PORTS['nginx'][0]} timed out: {e}")
        elapsed_time = time.time() - start_time
        time.sleep(1)
        if elapsed_time > _INTERNAL_STATUS_TIMEOUT:             # TODO: Handle case of this happening for large images
            print(f"\tTimeout getting internal deployment status after {elapsed_time} seconds")
            return AnalysisStatus.FAILED.value

    # Extract fields from response
    analysis_status, analysis_token_remaining_time = (response.json()['status'],
                                                      response.json()['token_remaining_time'])
    # Check if token needs refresh, do so if needed
    await _refresh_keycloak_token(deployment_name=deployment_name,
                                  analysis_id=analysis_id,
                                  token_remaining_time=analysis_token_remaining_time)

    # Map status from response to preset values
    if analysis_status == AnalysisStatus.FINISHED.value:
        health_status = AnalysisStatus.FINISHED.value
    elif analysis_status == AnalysisStatus.RUNNING.value:
        health_status = AnalysisStatus.RUNNING.value
    elif analysis_status == AnalysisStatus.STUCK.value:
        health_status = AnalysisStatus.STUCK.value
    else:
        health_status = AnalysisStatus.FAILED.value
    return health_status


async def _refresh_keycloak_token(deployment_name: str, analysis_id: str, token_remaining_time: int) -> None:
    """
    Refresh the keycloak token
    :return:
    """
    if token_remaining_time < (int(os.getenv('STATUS_LOOP_INTERVAL')) * 2 + 1):
        keycloak_token = get_keycloak_token(analysis_id)
        try:
            response = await (AsyncClient(base_url=f"http://nginx-{deployment_name}:{PORTS['nginx'][0]}")
                              .post("/analysis/token_refresh",
                                    json={'token': keycloak_token},
                                    headers=[('Connection', 'close')]))
            response.raise_for_status()
        except HTTPStatusError as e:
            print(f"Error: Failed to refresh keycloak token in deployment {deployment_name}.\n{e}")


def _fix_stuck_status(database: Database,
                      analysis_status: dict[str, str],
                      node_id: str,
                      hub_client: flame_hub.CoreClient) -> None:
    analysis = database.get_latest_deployment(analysis_status['analysis_id'])
    if analysis is not None:
        database.update_deployment_status(analysis.deployment_name, status=AnalysisStatus.FAILED.value)
        is_slow = ((analysis_status['db_status'] in [AnalysisStatus.STARTED.value]) and
                   (analysis_status['int_status'] in [AnalysisStatus.FAILED.value]))

        # Tracking restarts
        if analysis.restart_counter < _MAX_RESTARTS:
            _stream_stuck_logs(analysis, node_id, database, hub_client, is_slow)
            unstuck_analysis_deployments(analysis_status['analysis_id'], database)
        else:
            _stream_stuck_logs(analysis, node_id, database, hub_client, is_slow)


def _stream_stuck_logs(analysis: AnalysisDB,
                       node_id: str,
                       database: Database,
                       hub_client: flame_hub.CoreClient,
                       is_slow: bool) -> None:
    # If is_slow=True differentiate between slow, or kubernetes_error state, else assume stuck state
    is_k8s_related = False
    if is_slow:
        deployment_name = analysis.deployment_name
        # Retrieve status of latest pod
        pod_status_dict = get_pod_status(deployment_name)
        if pod_status_dict is not None:
            _, pod_status_dict = list(pod_status_dict.items())[-1]
            ready, reason, message = pod_status_dict['ready'], pod_status_dict['reason'], pod_status_dict['message']
            # ready=True implicates slow state, else assume kubernetes_error state
            if not ready:
                is_k8s_related = True
                print(f"\tDeployment of analysis={analysis.analysis_id} failed (ready={ready}).\n"
                      f"\t\t{reason}: {message}")

    # Create and stream POAPIError logs or either slow, stuck, or kubernetes_error state to Hub
    stream_logs(CreateStartUpErrorLog(analysis.restart_counter,
                                      ('k8s' if is_k8s_related else 'slow') if is_slow else 'stuck',
                                      analysis.analysis_id,
                                      analysis.status,
                                      k8s_error_msg=reason if is_k8s_related else ''),
                node_id,
                database,
                hub_client)


def _update_running_status(database: Database, analysis_status: dict[str, str]) -> None:
    analysis = database.get_latest_deployment(analysis_status['analysis_id'])
    if analysis is not None:
        database.update_deployment_status(analysis.deployment_name, AnalysisStatus.RUNNING.value)


def _update_finished_status(database: Database, analysis_status: dict[str, str]) -> None:
    analysis = database.get_latest_deployment(analysis_status['analysis_id'])
    if analysis is not None:
        database.update_deployment_status(analysis.deployment_name, analysis_status['int_status'])
        if analysis_status['int_status'] == AnalysisStatus.FINISHED.value:
            print("\tDelete deployment")
            # TODO: final local log save (minio?)  # archive logs
            # delete_analysis(analysis_status['analysis_id'], database)  # delete analysis from database
            stop_analysis(analysis_status['analysis_id'], database)  # stop analysis TODO: Change to delete in the future (when archive logs implemented)
        else:
            print("\tStop deployment")
            stop_analysis(analysis_status['analysis_id'], database)  # stop analysis


def _set_analysis_hub_status(hub_client: flame_hub.CoreClient,
                             node_analysis_id: str,
                             analysis_status: dict[str, str]) -> str:
    if analysis_status['db_status'] in [AnalysisStatus.FAILED.value,
                                        AnalysisStatus.FINISHED.value]:
        analysis_hub_status = analysis_status['db_status']
    elif analysis_status['int_status'] in [AnalysisStatus.FAILED.value,
                                           AnalysisStatus.FINISHED.value,
                                           AnalysisStatus.RUNNING.value]:
        analysis_hub_status = analysis_status['int_status']
    else:
        analysis_hub_status = analysis_status['db_status']

    update_hub_status(hub_client, node_analysis_id, analysis_hub_status)
    return analysis_hub_status
