import time
import os
from typing import Optional
from httpx import Client, HTTPStatusError, ConnectError, ConnectTimeout

import flame_hub

from src.resources.log.entity import CreateStartUpErrorLog
from src.k8s.kubernetes import PORTS, get_pod_status
from src.resources.database.entity import Database, AnalysisDB


from src.utils.hub_client import (init_hub_client_with_client,
                                  get_node_id_by_client,
                                  get_node_analysis_id,
                                  get_partner_node_statuses,
                                  update_hub_status)
from src.resources.utils import (unstuck_analysis_deployments,
                                 stop_analysis,
                                 delete_analysis,
                                 stream_logs)
from src.status.constants import AnalysisStatus
from src.utils.other import extract_hub_envs
from src.utils.token import get_keycloak_token
from src.status.constants import _MAX_RESTARTS, _INTERNAL_STATUS_TIMEOUT
from src.utils.po_logging import get_logger


logger = get_logger()


def status_loop(database: Database, status_loop_interval: int) -> None:
    """
    Send the status of the analysis to the HUB, kill deployment if analysis finished

    :return:
    """
    hub_client = None
    node_id = None
    node_analysis_ids = {}

    client_id, client_secret, hub_url_core, hub_auth, enable_hub_logging, http_proxy, https_proxy = extract_hub_envs()

    # Enter lifecycle loop
    while True:
        if hub_client is None:
            hub_client = init_hub_client_with_client(client_id,
                                                    client_secret,
                                                    hub_url_core,
                                                    hub_auth,
                                                    http_proxy,
                                                    https_proxy)
            node_id = get_node_id_by_client(hub_client, client_id)
            # Catch unresponsive hub client
            if node_id is None:
                logger.action("Resetting hub client...")
                hub_client = None
                time.sleep(status_loop_interval)
                continue
        else:
            # If running analyzes exist, enter status loop
            running_analyzes = [analysis_id for analysis_id in database.get_analysis_ids()
                                if database.analysis_is_running(analysis_id)]
            logger.action(f"Checking for running analyzes...{running_analyzes}")
            if running_analyzes:
                hub_client_issues = 0
                for analysis_id in running_analyzes:
                    logger.status_loop(f"Current analysis id: {analysis_id}")
                    # Get node analysis id
                    if analysis_id not in node_analysis_ids.keys():
                        node_analysis_id = get_node_analysis_id(hub_client, analysis_id, node_id)
                        if node_analysis_id is not None:
                            node_analysis_ids[analysis_id] = node_analysis_id
                        else:
                            logger.warning(f"Retrieving node_analysis id for malformed analysis returned None "
                                           f"(analysis_id={analysis_id})... Skipping")
                            hub_client_issues += 1
                            continue
                    else:
                        node_analysis_id = node_analysis_ids[analysis_id]

                    # If node analysis id found
                    logger.info(f"\tNode analysis id: {node_analysis_id}")
                    if node_analysis_id is not None:
                        try:
                            # Inform local analysis of partner node statuses
                            _ = inform_analysis_of_partner_statuses(database,
                                                                    hub_client,
                                                                    analysis_id,
                                                                    node_analysis_id)
                        except Exception as e:
                            logger.status_loop(f"Error when attempting to access partner_status endpoint of "
                                               f"{analysis_id} ({repr(e)})")

                        # Retrieve analysis status (skip iteration if analysis is not deployed)
                        analysis_status = _get_analysis_status(analysis_id, database)
                        if analysis_status is None:
                            continue
                        logger.debug(f"Database status: {analysis_status['db_status']}")
                        logger.debug(f"Internal status: {analysis_status['int_status']}")

                        # Fix stuck analyzes
                        if analysis_status['status_action'] == 'unstuck':
                            logger.info(f"Unstuck analysis with internal status: {analysis_status['int_status']}")
                            _fix_stuck_status(database, analysis_status, node_id, enable_hub_logging, hub_client)
                            # Update analysis status (skip iteration if analysis is not deployed)
                            analysis_status = _get_analysis_status(analysis_id, database)
                            if analysis_status is None:
                                continue

                        # Update created to running status
                        if analysis_status['status_action'] == 'running':
                            logger.info(f"Update created-to-running database status: {analysis_status['db_status']}")
                            _update_running_status(database, analysis_status)
                            # Update analysis status (skip iteration if analysis is not deployed)
                            analysis_status = _get_analysis_status(analysis_id, database)
                            if analysis_status is None:
                                continue

                        # Update running to finished status
                        if analysis_status['status_action'] == 'finishing':
                            logger.info(f"Update running-to-finished database status: {analysis_status['db_status']}")
                            _update_finished_status(database, analysis_status)
                            # Update analysis status (skip iteration if analysis is not deployed)
                            analysis_status = _get_analysis_status(analysis_id, database)
                            if analysis_status is None:
                                continue

                        # Submit analysis_status to hub
                        analysis_hub_status = _set_analysis_hub_status(hub_client, node_analysis_id, analysis_status)
                        logger.info(f"Set Hub analysis status with node_analysis={node_analysis_id}, "
                                    f"db_status={analysis_status['db_status']}, "
                                    f"internal_status={analysis_status['int_status']} "
                                    f"to {analysis_hub_status}")

            time.sleep(status_loop_interval)
            logger.status_loop(f"Iteration completed. Sleeping for {status_loop_interval} seconds.")



def inform_analysis_of_partner_statuses(database: Database,
                                        hub_client: flame_hub.CoreClient,
                                        analysis_id: str,
                                        node_analysis_id: str) -> Optional[dict[str, str]]:
    node_statuses = get_partner_node_statuses(hub_client, analysis_id, node_analysis_id)
    deployment_name = database.get_latest_deployment(analysis_id).deployment_name
    client = Client(base_url=f"http://nginx-{deployment_name}:{PORTS['nginx'][0]}")
    try: # try except, in case analysis api is not yet ready
        response = client.post(url="/analysis/partner_status",
                               headers=[('Connection', 'close')],
                               json={'partner_status': node_statuses})
        response.raise_for_status()
        client.close()
        return response.json()
    except HTTPStatusError as e:
        logger.warning(f"Error whilst trying to access analysis partner_status endpoint: {repr(e)}")
    except ConnectError as e:
        logger.warning(f"Connection to http://nginx-{deployment_name}:{PORTS['nginx'][0]} yielded an error: {repr(e)}")
    except ConnectTimeout as e:
        logger.warning(f"Connection to http://nginx-{deployment_name}:{PORTS['nginx'][0]} timed out: {repr(e)}")
    client.close()
    return None


def _get_analysis_status(analysis_id: str, database: Database) -> Optional[dict[str, str]]:
    analysis = database.get_latest_deployment(analysis_id)
    if analysis is not None:
        db_status = analysis.status
        # Make the Finished status final, the internal status is not checked anymore,
        # because the analysis will already be deleted
        if db_status == AnalysisStatus.EXECUTED.value:
            int_status = AnalysisStatus.EXECUTED.value
        else:
            int_status = _get_internal_deployment_status(analysis.deployment_name, analysis_id)
        return {'analysis_id': analysis_id,
                'db_status': analysis.status,
                'int_status': int_status,
                'status_action': _decide_status_action(analysis.status, int_status)}
    else:
        return None


def _decide_status_action(db_status: str, int_status: str) -> Optional[str]:
    is_stuck = int_status == AnalysisStatus.STUCK.value
    is_slow = ((db_status in [AnalysisStatus.STARTED.value]) and (int_status in [AnalysisStatus.FAILED.value]))
    newly_running = ((db_status in [AnalysisStatus.STARTED.value]) and (int_status in [AnalysisStatus.EXECUTING.value]))
    speedy_finished = ((db_status in [AnalysisStatus.STARTED.value]) and (int_status in [AnalysisStatus.EXECUTED.value]))
    newly_ended = ((db_status in [AnalysisStatus.EXECUTING.value, AnalysisStatus.FAILED.value])
                   and (int_status in [AnalysisStatus.EXECUTED.value, AnalysisStatus.FAILED.value]))
    firmly_stuck = ((db_status in [AnalysisStatus.FAILED.value]) and (int_status in [AnalysisStatus.STUCK.value]))
    was_stopped = int_status == AnalysisStatus.STOPPED.value
    if is_stuck or is_slow:
        return 'unstuck'
    elif newly_running:
        return 'running'
    elif speedy_finished or newly_ended or firmly_stuck or was_stopped:
        return 'finishing'
    else:
        return None


def _get_internal_deployment_status(deployment_name: str, analysis_id: str) -> str:
    # Attempt to retrieve internal analysis status via health endpoint
    start_time = time.time()
    client = Client(base_url=f"http://nginx-{deployment_name}:{PORTS['nginx'][0]}")
    while True:
        try:
            response = client.get("/analysis/healthz", headers=[('Connection', 'close')])
            response.raise_for_status()
            client.close()
            break
        except HTTPStatusError as e:
            logger.warning(f"Error whilst retrieving internal deployment status: {repr(e)}")
        except ConnectError as e:
            logger.warning(f"Connection to http://nginx-{deployment_name}:{PORTS['nginx'][0]} yielded an error: {repr(e)}")
        except ConnectTimeout as e:
            logger.warning(f"Connection to http://nginx-{deployment_name}:{PORTS['nginx'][0]} timed out: {repr(e)}")
        elapsed_time = time.time() - start_time
        if elapsed_time > _INTERNAL_STATUS_TIMEOUT:
            logger.error(f"Timeout getting internal deployment status after {elapsed_time:.1f} seconds")
            client.close()
            return AnalysisStatus.FAILED.value
        time.sleep(1)

    # Extract fields from response
    analysis_status, analysis_token_remaining_time = (response.json()['status'],
                                                      response.json()['token_remaining_time'])
    # Check if token needs refresh, do so if needed
    _refresh_keycloak_token(deployment_name=deployment_name,
                            analysis_id=analysis_id,
                            token_remaining_time=analysis_token_remaining_time)

    # Map status from response to preset values
    if analysis_status == AnalysisStatus.EXECUTED.value:
        health_status = AnalysisStatus.EXECUTED.value
    elif analysis_status == AnalysisStatus.EXECUTING.value:
        health_status = AnalysisStatus.EXECUTING.value
    elif analysis_status == AnalysisStatus.STUCK.value:
        health_status = AnalysisStatus.STUCK.value
    else:
        health_status = AnalysisStatus.FAILED.value
    return health_status


def _refresh_keycloak_token(deployment_name: str, analysis_id: str, token_remaining_time: int) -> None:
    """
    Refresh the keycloak token
    :return:
    """
    if token_remaining_time < (int(os.getenv('STATUS_LOOP_INTERVAL', '10')) * 2 + 1):
        keycloak_token = get_keycloak_token(analysis_id)
        client = Client(base_url=f"http://nginx-{deployment_name}:{PORTS['nginx'][0]}")
        try:
            response = client.post("/analysis/token_refresh",
                                   json={'token': keycloak_token},
                                   headers=[('Connection', 'close')])
            response.raise_for_status()
        except HTTPStatusError as e:
            logger.error(f"Failed to refresh keycloak token in deployment {deployment_name}: {repr(e)}")
        client.close()


def _fix_stuck_status(database: Database,
                      analysis_status: dict[str, str],
                      node_id: str,
                      enable_hub_logging: bool,
                      hub_client: flame_hub.CoreClient) -> None:
    analysis = database.get_latest_deployment(analysis_status['analysis_id'])
    if analysis is not None:
        is_slow = ((analysis_status['db_status'] in [AnalysisStatus.STARTED.value]) and
                   (analysis_status['int_status'] in [AnalysisStatus.FAILED.value]))

        # Tracking restarts
        if analysis.restart_counter < _MAX_RESTARTS:
            _stream_stuck_logs(analysis, node_id, enable_hub_logging, database, hub_client, is_slow)
            unstuck_analysis_deployments(analysis_status['analysis_id'], database)
        else:
            database.update_deployment_status(analysis.deployment_name, status=AnalysisStatus.FAILED.value)
            _stream_stuck_logs(analysis, node_id, enable_hub_logging, database, hub_client, is_slow)


def _stream_stuck_logs(analysis: AnalysisDB,
                       node_id: str,
                       enable_hub_logging: bool,
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
                logger.error(f"Deployment of analysis={analysis.analysis_id} failed (ready={ready}). "
                               f"{reason}: {message}")

    # Create and stream POAPIError logs or either slow, stuck, or kubernetes_error state to Hub
    stream_logs(CreateStartUpErrorLog(analysis.restart_counter,
                                      ('k8s' if is_k8s_related else 'slow') if is_slow else 'stuck',
                                      analysis.analysis_id,
                                      analysis.status,
                                      k8s_error_msg=reason if is_k8s_related else ''),
                node_id,
                enable_hub_logging,
                database,
                hub_client)


def _update_running_status(database: Database, analysis_status: dict[str, str]) -> None:
    analysis = database.get_latest_deployment(analysis_status['analysis_id'])
    if analysis is not None:
        database.update_deployment_status(analysis.deployment_name, AnalysisStatus.EXECUTING.value)


def _update_finished_status(database: Database, analysis_status: dict[str, str]) -> None:
    analysis = database.get_latest_deployment(analysis_status['analysis_id'])
    if analysis is not None:
        database.update_deployment_status(analysis.deployment_name, analysis_status['int_status'])
        if analysis_status['int_status'] == AnalysisStatus.EXECUTED.value:
            logger.info("Delete deployment")
            delete_analysis(analysis_status['analysis_id'], database)  # delete analysis from database
        else:
            logger.info("Stop deployment")
            stop_analysis(analysis_status['analysis_id'], database)  # stop analysis


def _set_analysis_hub_status(hub_client: flame_hub.CoreClient,
                             node_analysis_id: str,
                             analysis_status: dict[str, str]) -> str:
    if analysis_status['db_status'] in [AnalysisStatus.FAILED.value,
                                        AnalysisStatus.EXECUTED.value]:
        analysis_hub_status = analysis_status['db_status']
    elif analysis_status['int_status'] in [AnalysisStatus.FAILED.value,
                                           AnalysisStatus.EXECUTED.value,
                                           AnalysisStatus.EXECUTING.value]:
        analysis_hub_status = analysis_status['int_status']
    else:
        analysis_hub_status = analysis_status['db_status']

    update_hub_status(hub_client, node_analysis_id, analysis_hub_status)
    return analysis_hub_status
