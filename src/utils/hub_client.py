import os
from json import JSONDecodeError
from typing import Optional, Tuple
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
    proxies = None
    if http_proxy and https_proxy:
        proxies = {
            "http://": HTTPTransport(proxy=http_proxy),
            "https://":  HTTPTransport(proxy=https_proxy)
        }
    try:
        robot_client = Client(base_url=hub_auth, mounts=proxies)
        hub_robot = flame_hub.auth.RobotAuth(robot_id=robot_id,
                                             robot_secret=robot_secret,
                                             client=robot_client)

        client = Client(base_url=hub_url_core, mounts=proxies, auth=hub_robot)
        hub_client = flame_hub.CoreClient(client=client)
        print("Hub client init successful")
    except Exception as e:
        hub_client = None
        print(f"Failed to authenticate with hub python client library.\n{e}")
    return hub_client


def get_node_id_by_robot(hub_client: flame_hub.CoreClient, robot_id: str) -> Optional[str]:
    try:
        node_id_object = hub_client.find_nodes(filter={"robot_id": robot_id})[0]
        print(f"Found node id object: {node_id_object}")
    except (HTTPStatusError, JSONDecodeError, ConnectTimeout) as e:
        print(f"Error in hub python client whilst retrieving node id object!\n{e}")
        node_id_object = None
    return str(node_id_object.id) if node_id_object is not None else None


def get_node_analysis_id(hub_client: flame_hub.CoreClient, analysis_id: str, node_id_object_id: str) -> Optional[str]:
    try:
        node_analyzes = hub_client.find_analysis_nodes(filter={"analysis_id": analysis_id,
                                                               "node_id": node_id_object_id})
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
    node_id = get_node_id_by_robot(hub_client, robot_id)
    if node_id is None:
        print("Failed to retrieve node_id from hub client. Cannot update status.")
    node_analysis_id = get_node_analysis_id(hub_client, analysis_id, node_id)
    if node_id is None:
        print("Failed to retrieve node_analysis_id from hub client. Cannot update status.")
    update_hub_status(hub_client, node_analysis_id, run_status=status)


# TODO: Import this from flame sdk? (from flamesdk import HUB_LOG_LITERALS)
class HUB_LOG_LITERALS(Enum):
    info_log = 'informational'
    notice_message = 'notice'
    debug_log = 'debug'
    warning_log = 'warning'
    error_code = 'error'
