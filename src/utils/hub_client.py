import os
from json import JSONDecodeError
from typing import Optional
from httpx import (Client,
                   HTTPTransport,
                   HTTPStatusError,
                   ConnectError,
                   ConnectTimeout)
from enum import Enum

import flame_hub


def init_hub_client_with_robot(robot_id: str,
                               robot_secret: str,
                               hub_url_core: str,
                               hub_auth: str,
                               http_proxy: str,
                               https_proxy: str) -> Optional[flame_hub.CoreClient]:
    # Attempt to init hub client
    try:
        hub_robot = flame_hub.auth.RobotAuth(robot_id=robot_id,
                                             robot_secret=robot_secret,
                                             base_url=hub_auth)
        if (http_proxy is not None) and (https_proxy is not None):
            proxies = {
                "http://": HTTPTransport(proxy=http_proxy),
                "https://":  HTTPTransport(proxy=https_proxy)
            }
            client = Client(base_url= hub_url_core, mounts=proxies ,auth=hub_robot)
            hub_client = flame_hub.CoreClient(client=client)
        else:
            hub_client = flame_hub.CoreClient(base_url=hub_url_core,
                                              auth=hub_robot)
        print("Hub client init successful")
    except Exception as e:
        hub_client = None
        print(f"Failed to authenticate with hub python client library.\n{e}")
    return hub_client


def get_node_id_by_robot(hub_client: flame_hub.CoreClient, robot_id: str) -> Optional[str]:
    try:
        node_id = str(hub_client.find_nodes(filter={"robot_id": robot_id})[0].id)
        print(f"Found node id: {node_id}")
    except (HTTPStatusError, JSONDecodeError, ConnectTimeout) as e:
        print(f"Error in hub python client whilst retrieving node id!\n{e}")
        node_id = None
    return node_id


def get_node_analysis_id(hub_client: flame_hub.CoreClient, analysis_id: str, node_id: str) -> Optional[str]:
    try:
        node_analyzes = hub_client.find_analysis_nodes(filter={"analysis_id": analysis_id,
                                                               "node_id": node_id})
        print(f"Found node analyzes: {node_analyzes}")
    except HTTPStatusError as e:
        print(f"Error in hub python client whilst retrieving node analyzes!\n{e}")
        node_analyzes = None

    if node_analyzes:
        node_analysis_id = str(node_analyzes[0].id)
    else:
        node_analysis_id = None

    return node_analysis_id


def update_hub_status(hub_client: flame_hub.CoreClient, node_analysis_id: str, run_status: str) -> None:
    """
    Update the status of the analysis in the hub.
    """
    try:
        hub_client.update_analysis_node(node_analysis_id, run_status=run_status)
        print(f"Updated hub status to {run_status} for node_analysis_id {node_analysis_id}")
    except (HTTPStatusError, ConnectError) as e:
        print(f"Failed to update hub status for node_analysis_id {node_analysis_id}.\n{e}")


def init_hub_client_and_update_hub_status_with_robot(analysis_id: str, status: str) -> None:
    """
    Create a hub client for the analysis and update the current status.
    """
    robot_id, robot_secret, hub_url_core, hub_auth, http_proxy, https_proxy = (os.getenv('HUB_ROBOT_USER'),
                                                                               os.getenv('HUB_ROBOT_SECRET'),
                                                                               os.getenv('HUB_URL_CORE'),
                                                                               os.getenv('HUB_URL_AUTH'),
                                                                               os.getenv('PO_HTTP_PROXY'),
                                                                               os.getenv('PO_HTTPS_PROXY'))
    hub_client = init_hub_client_with_robot(robot_id, robot_secret, hub_url_core, hub_auth, http_proxy, https_proxy)
    if hub_client is None:
        print("Failed to initialize hub client. Cannot update status.")
        return
    node_id = get_node_id_by_robot(hub_client, robot_id)
    if node_id is None:
        print("Failed to retrieve node_id from hub client. Cannot update status.")
        return
    node_analysis_id = get_node_analysis_id(hub_client, analysis_id, node_id)
    if node_id is None:
        print("Failed to retrieve node_analysis_id from hub client. Cannot update status.")
        return
    update_hub_status(hub_client, node_analysis_id, run_status=status)
    return


# TODO: Import this from flame sdk? (from flamesdk import HUB_LOG_LITERALS)
class HUB_LOG_LITERALS(Enum):
    status_message = 'status_message'
    error_code = 'error_code'


def send_log_to_hub(hub_client: flame_hub.CoreClient,
                    log_type: str,
                    log: str,
                    analysis_id: Optional[str] = None,
                    node_id: Optional[str] = None,
                    log_update_id: Optional[str] = None) -> str:
    if log_update_id or (analysis_id and node_id):
        error, error_code, status, status_message = (False, '', '', '')
        if log_type == HUB_LOG_LITERALS.error_code.value:
            error = True
            error_code = log
        else:
            status = log_type
            status_message = log
        # TODO: Add other cases?

        if log_update_id is None:
            analysis_node_log_id = hub_client.create_analysis_node_log(analysis_id,
                                                                       node_id,
                                                                       error=error,
                                                                       error_code=error_code,
                                                                       status=status,
                                                                       status_message=status_message).id
        else:
            # TODO: Log update needed? Or should we just create new logs over and over?
            analysis_node_log_id = hub_client.update_analysis_node_log(error=error,
                                                                       error_code=error_code,
                                                                       status=status,
                                                                       status_message=status_message).id
        return analysis_node_log_id
    else:
        raise ValueError(f"In order to update hub logs, either the uuid of an existing log entry, or the node and "
                         f"analysis id have to be provided.")
