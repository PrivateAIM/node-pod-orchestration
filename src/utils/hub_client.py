import os
import ssl

from pathlib import Path
from functools import lru_cache
from json import JSONDecodeError
from typing import Optional, Tuple
from httpx import (Client,
                   HTTPTransport,
                   HTTPStatusError,
                   ConnectError,
                   ConnectTimeout)
import truststore
from enum import Enum

import flame_hub

from src.status.constants import AnalysisStatus


def init_hub_client_with_client(client_id: str,
                               client_secret: str,
                               hub_url_core: str,
                               hub_auth: str,
                               http_proxy: str,
                               https_proxy: str) -> Optional[flame_hub.CoreClient]:
    # Attempt to init hub client
    proxies = None
    ssl_ctx = get_ssl_context()
    if http_proxy and https_proxy:
        proxies = {
            "http://": HTTPTransport(proxy=http_proxy),
            "https://":  HTTPTransport(proxy=https_proxy, verify=ssl_ctx)
        }
    try:

        _client = Client(base_url=hub_auth, mounts=proxies, verify=ssl_ctx)
        hub_client = flame_hub.auth.ClientAuth(client_id=client_id,
                                             client_secret=client_secret,
                                             client=_client)

        client = Client(base_url=hub_url_core, mounts=proxies, auth=hub_client, verify=ssl_ctx)
        hub_client = flame_hub.CoreClient(client=client)
        print("Hub client init successful")
    except Exception as e:
        hub_client = None
        print(f"Failed to authenticate with hub python client library.\n{e}")
    return hub_client


@lru_cache
def get_ssl_context() -> ssl.SSLContext:
    """Check if there are additional certificates present and if so, load them."""
    cert_path = os.getenv('EXTRA_CA_CERTS')
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if cert_path and Path(cert_path).exists():
        ctx.load_verify_locations(cafile=cert_path)
    return ctx


def get_node_id_by_client(hub_client: flame_hub.CoreClient, client_id: str) -> Optional[str]:
    try:
        node_id_object = hub_client.find_nodes(filter={"client_id": client_id})[0]
    except (HTTPStatusError, JSONDecodeError, ConnectTimeout, flame_hub._exceptions.HubAPIError, AttributeError) as e:
        print(f"Error in hub python client whilst retrieving node id object!\n{e}")
        node_id_object = None
    return str(node_id_object.id) if node_id_object is not None else None


def get_node_analysis_id(hub_client: flame_hub.CoreClient, analysis_id: str, node_id_object_id: str) -> Optional[str]:
    try:
        node_analyzes = hub_client.find_analysis_nodes(filter={"analysis_id": analysis_id,
                                                               "node_id": node_id_object_id})
    except (HTTPStatusError, flame_hub._exceptions.HubAPIError, AttributeError) as e:
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
    status_mapping = {
        AnalysisStatus.RUNNING.value: "executing",
        AnalysisStatus.FINISHED.value: "executed",
    }
    try:
        if run_status == AnalysisStatus.STUCK.value:
            run_status = AnalysisStatus.FAILED.value
        execution_status = status_mapping.get(run_status, run_status)
        hub_client.update_analysis_node(node_analysis_id, execution_status=execution_status)
    except (HTTPStatusError, ConnectError, flame_hub._exceptions.HubAPIError, AttributeError) as e:
        print(f"Failed to update hub status for node_analysis_id {node_analysis_id}.\n{e}")


def init_hub_client_and_update_hub_status_with_client(analysis_id: str, status: str) -> None:
    """
    Create a hub client for the analysis and update the current status.
    """
    client_id, client_secret, hub_url_core, hub_auth, http_proxy, https_proxy = (os.getenv('HUB_CLIENT_ID'),
                                                                               os.getenv('HUB_CLIENT_SECRET'),
                                                                               os.getenv('HUB_URL_CORE'),
                                                                               os.getenv('HUB_URL_AUTH'),
                                                                               os.getenv('PO_HTTP_PROXY'),
                                                                               os.getenv('PO_HTTPS_PROXY'))
    hub_client = init_hub_client_with_client(client_id, client_secret, hub_url_core, hub_auth, http_proxy, https_proxy)
    if hub_client is not None:
        node_id = get_node_id_by_client(hub_client, client_id)
        if node_id is not None:
            node_analysis_id = get_node_analysis_id(hub_client, analysis_id, node_id)
            if node_analysis_id is not None:
                update_hub_status(hub_client, node_analysis_id, run_status=status)
            else:
                print("Failed to retrieve node_analysis_id from hub client. Cannot update status.")
        else:
            print("Failed to retrieve node_id from hub client. Cannot update status.")
    else:
        print("Failed to initialize hub client. Cannot update status.")


# TODO: Import this from flame sdk? (from flamesdk import HUB_LOG_LITERALS)
class HUB_LOG_LITERALS(Enum):
    info_log = 'informational'
    notice_message = 'notice'
    debug_log = 'debug'
    warning_log = 'warning'
    error_code = 'error'
