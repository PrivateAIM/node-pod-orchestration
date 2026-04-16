import os
import ssl

from pathlib import Path
from functools import lru_cache
from json import JSONDecodeError
from typing import Optional
from httpx import (Client,
                   HTTPTransport,
                   HTTPStatusError,
                   ConnectError,
                   ConnectTimeout)
import truststore

import flame_hub

from src.status.constants import AnalysisStatus
from src.utils.po_logging import get_logger
from src.utils.other import extract_hub_envs


logger = get_logger()


def init_hub_client_with_client(client_id: str,
                                client_secret: str,
                                hub_url_core: str,
                                hub_auth: str,
                                http_proxy: str,
                                https_proxy: str) -> Optional[flame_hub.CoreClient]:
    """Authenticate and build a :class:`flame_hub.CoreClient` talking to the FLAME Hub.

    Honors the ``PO_HTTP_PROXY`` / ``PO_HTTPS_PROXY`` and ``EXTRA_CA_CERTS``
    environment variables via :func:`get_ssl_context`.

    Args:
        client_id: OAuth2 client id for the node.
        client_secret: OAuth2 client secret for the node.
        hub_url_core: Base URL of the Hub core API.
        hub_auth: Base URL of the Hub auth service.
        http_proxy: HTTP proxy URL (may be empty/None).
        https_proxy: HTTPS proxy URL (may be empty/None).

    Returns:
        An initialized Hub core client, or ``None`` on authentication failure.
    """
    # Attempt to init hub client
    proxies = None
    ssl_ctx = get_ssl_context()
    if http_proxy and https_proxy:
        proxies = {
            "http://": HTTPTransport(proxy=http_proxy),
            "https://": HTTPTransport(proxy=https_proxy, verify=ssl_ctx)
        }
    try:

        _client = Client(base_url=hub_auth, mounts=proxies, verify=ssl_ctx)
        hub_client = flame_hub.auth.ClientAuth(client_id=client_id,
                                               client_secret=client_secret,
                                               client=_client)

        client = Client(base_url=hub_url_core, mounts=proxies, auth=hub_client, verify=ssl_ctx)
        hub_client = flame_hub.CoreClient(client=client)
        logger.action("Hub client init successful")
    except Exception as e:
        hub_client = None
        logger.error(f"Failed to authenticate with hub python client library: {repr(e)}")
    return hub_client


@lru_cache
def get_ssl_context() -> ssl.SSLContext:
    """Return a cached SSL context that trusts the system store plus ``EXTRA_CA_CERTS``.

    Returns:
        A :class:`truststore.SSLContext` loaded with the system certificate
        store and, if present, the CA bundle pointed to by ``EXTRA_CA_CERTS``.
    """
    cert_path = os.getenv('EXTRA_CA_CERTS')
    ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if cert_path and Path(cert_path).exists():
        ctx.load_verify_locations(cafile=cert_path)
    return ctx


def get_node_id_by_client(hub_client: flame_hub.CoreClient, client_id: str) -> Optional[str]:
    """Look up the Hub node id associated with an OAuth2 client id.

    Args:
        hub_client: Initialized Hub core client.
        client_id: OAuth2 client id of this node.

    Returns:
        The node's UUID as a string, or ``None`` on failure.
    """
    try:
        node_id_object = hub_client.find_nodes(filter={'client_id': client_id})[0]
    except (HTTPStatusError, JSONDecodeError, ConnectTimeout, flame_hub._exceptions.HubAPIError, AttributeError) as e:
        logger.error(f"Failed to retrieve node id object from hub python client {client_id}: {repr(e)}")
        node_id_object = None
    return str(node_id_object.id) if node_id_object is not None else None


def get_node_analysis_id(hub_client: flame_hub.CoreClient, analysis_id: str, node_id_object_id: str) -> Optional[str]:
    """Look up the Hub analysis-node id for a (analysis, node) pair.

    Args:
        hub_client: Initialized Hub core client.
        analysis_id: Analysis id to filter by.
        node_id_object_id: Hub node id (see :func:`get_node_id_by_client`).

    Returns:
        The analysis-node UUID as a string, or ``None`` if none exists.
    """
    try:
        node_analyzes = hub_client.find_analysis_nodes(filter={'analysis_id': analysis_id,
                                                               'node_id': node_id_object_id})
    except (HTTPStatusError, flame_hub._exceptions.HubAPIError, AttributeError) as e:
        logger.error(f"Failed to retrieve node analyzes from hub python client: {repr(e)}")
        node_analyzes = None

    if node_analyzes:
        node_analysis_id = str(node_analyzes[0].id)
    else:
        node_analysis_id = None

    return node_analysis_id


def update_hub_status(hub_client: flame_hub.CoreClient,
                      node_analysis_id: str,
                      run_status: str,
                      run_progress: Optional[int] = None) -> None:
    """Update the execution status (and optionally progress) of an analysis-node in the Hub.

    ``STUCK`` is normalized to ``FAILED`` since the Hub does not model a
    stuck status.

    Args:
        hub_client: Initialized Hub core client.
        node_analysis_id: Hub analysis-node id to update.
        run_status: New execution status string.
        run_progress: Optional execution progress (0-100).
    """
    try:
        if run_status == AnalysisStatus.STUCK.value:
            run_status = AnalysisStatus.FAILED.value
        if run_progress is None:
            hub_client.update_analysis_node(node_analysis_id, execution_status=run_status)
        else:
            hub_client.update_analysis_node(node_analysis_id, execution_status=run_status, execution_progress=run_progress)
    except (HTTPStatusError, ConnectError, flame_hub._exceptions.HubAPIError, AttributeError) as e:
        logger.error(f"Failed to update hub status for node_analysis_id {node_analysis_id}: {repr(e)}")


def get_analysis_node_statuses(hub_client: flame_hub.CoreClient, analysis_id: str) -> Optional[dict[str, str]]:
    """Return the execution status of every node participating in an analysis.

    Args:
        hub_client: Initialized Hub core client.
        analysis_id: Analysis to query.

    Returns:
        Mapping ``{node_analysis_id: execution_status}``, or ``None`` on
        lookup failure.
    """
    try:
        node_analyzes = hub_client.find_analysis_nodes(filter={'analysis_id': analysis_id})
    except (HTTPStatusError, flame_hub._exceptions.HubAPIError, AttributeError) as e:
        logger.error(f"Failed to retrieve node analyzes from hub python client: {repr(e)}")
        return  None
    analysis_node_statuses = {}
    for node in node_analyzes:
        analysis_node_statuses[str(node.id)] = node.execution_status
    return analysis_node_statuses


def get_partner_node_statuses(hub_client: flame_hub.CoreClient,
                              analysis_id: str,
                              node_analysis_id: str) -> Optional[dict[str, str]]:
    """Return :func:`get_analysis_node_statuses` with the local node filtered out.

    Args:
        hub_client: Initialized Hub core client.
        analysis_id: Analysis to query.
        node_analysis_id: Local node's analysis-node id, excluded from the
            result.

    Returns:
        Mapping ``{partner_node_analysis_id: execution_status}``, or ``None``
        on lookup failure.
    """
    analysis_node_statuses = get_analysis_node_statuses(hub_client, analysis_id)
    return {k : v for k, v in analysis_node_statuses.items() if k != node_analysis_id} \
        if analysis_node_statuses is not None else None


def init_hub_client_and_update_hub_status_with_client(analysis_id: str, status: str) -> None:
    """One-shot convenience that (re)builds a Hub client and pushes a status update.

    Used by API endpoints that do not hold a long-lived Hub client. Logs and
    returns silently when any lookup in the chain (client, node id, analysis
    node id) fails.

    Args:
        analysis_id: Analysis whose Hub status should be updated.
        status: New execution status string.
    """
    client_id, client_secret, hub_url_core, hub_auth, _, http_proxy, https_proxy = extract_hub_envs()
    hub_client = init_hub_client_with_client(client_id, client_secret, hub_url_core, hub_auth, http_proxy, https_proxy)
    if hub_client is not None:
        node_id = get_node_id_by_client(hub_client, client_id)
        if node_id is not None:
            node_analysis_id = get_node_analysis_id(hub_client, analysis_id, node_id)
            if node_analysis_id is not None:
                update_hub_status(hub_client, node_analysis_id, run_status=status)
            else:
                logger.error("Failed to retrieve node_analysis_id from hub client. Cannot update status.")
        else:
            logger.error("Failed to retrieve node_id from hub client. Cannot update status.")
    else:
        logger.error(f"Failed to initialize hub client. Cannot update status.")
