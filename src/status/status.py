import time
import os
import asyncio
from typing import Literal, Optional

import flame_hub
from httpx import AsyncClient, HTTPStatusError, ConnectError

from src.resources.database.entity import Database
from src.resources.analysis.entity import Analysis, read_db_analysis
from src.resources.utils import delete_analysis, stop_analysis
from src.utils.token import delete_keycloak_client, get_hub_token
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
                node_id = _get_node_id()
                if hub_client:
                    new_node_id = str(hub_client.find_nodes(filter={"robot_id": robot_id})[0].id) #TODO
                    print(f"Node IDs are equal {node_id == new_node_id}\n\tnode_id={node_id}, new_node_id={new_node_id}")
                    print(f"\t\thub_client.find_nodes(filter={{'robot_id': robot_id}})="
                          f"{hub_client.find_nodes(filter={'robot_id': robot_id})}")
                    print(f"\t\tids: {[n.id for n in hub_client.find_nodes(filter={'robot_id': robot_id})]}")
            else:
                for analysis_id in set(database.get_analysis_ids()):
                    if analysis_id not in node_analysis_ids.keys():
                        # new_node_analysis_ids = hub_client.fin #TODO
                        node_analysis_id = _get_node_analysis_id(node_id, analysis_id)
                        # print(f"Node IDs are equal {node_analysis_id == new_node_analysis_ids}")
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

                        _set_analysis_hub_status(node_analysis_id, db_status, int_status)
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
                                      for deployment in deployments if deployment.status == 'started']

    running_deployment_names = [deployment_name
                                for deployment_name in internal_status['status'].keys()
                                if (deployment_name in newly_created_deployment_names) and
                                (internal_status['status'][deployment_name] == 'ongoing')]
    for deployment_name in running_deployment_names:
        database.update_deployment_status(deployment_name, AnalysisStatus.RUNNING.value)
        database_status = _get_status(deployments)

    return database_status


def _set_analysis_hub_status(node_analysis_id: str,
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

        if intern_depl_status == 'failed':
            analysis_hub_status = AnalysisStatus.FAILED.value
            break
        elif intern_depl_status == 'finished':
            analysis_hub_status = AnalysisStatus.FINISHED.value
            break
        elif intern_depl_status == 'ongoing':
            analysis_hub_status = AnalysisStatus.RUNNING.value
            break
        else:
            analysis_hub_status = db_depl_status
            break

    _submit_analysis_status_update(node_analysis_id, analysis_hub_status)


def _submit_analysis_status_update(node_analysis_id: str, status: AnalysisStatus) -> None:
    """
    update status of analysis at hub

    POST https://core.privateaim.dev/analysis-nodes/3c895658-69f1-4fbe-b65c-768601b83f83
    Payload { "run_status": "started" }
    :return:
    """
    if status is not None:
        try:
            response = asyncio.run(AsyncClient(base_url=os.getenv('HUB_URL_CORE'),
                                               headers={"accept": "application/json",
                                                        "Authorization": f"Bearer {get_hub_token()['hub_token']}"})
                                   .post(f'/analysis-nodes/{node_analysis_id}',
                                         json={"run_status": status},
                                         headers=[('Connection', 'close')]))

            response.raise_for_status()
        except (HTTPStatusError, ConnectError) as e:
            print(f"Error updating analysis status: {e}")


def _get_node_analysis_id(node_id: str, analysis_id: str) -> Optional[str]:
    """
    get node-analysis id from hub
    analysis-id: 893761b5-d8ac-42be-ad71-a2d3e70b3990
    node-id: e64a1551-4007-4754-a7b9-57c9cb56a7c5
    endpoint: GET https://core.privateaim.dev/analysis-nodes?filter[node_id]=e64a1551-4007-4754-a7b9-57c9cb56a7c5&filter[analysis_id]=893761b5-d8ac-42be-ad71-a2d3e70b3990
    retrieve analysis id from object: 1b1b1b1b-1b1b-1b1b-1b1b-1b1b1b1b1b1b

    :param analysis_id:
    :param node_id:
    :param analysis_id:
    :return:
    """
    response = asyncio.run(AsyncClient(base_url=os.getenv('HUB_URL_CORE'),
                                       headers={"accept": "application/json",
                                                "Authorization": f"Bearer {get_hub_token()['hub_token']}"})
                           .get(f'/analysis-nodes?filter[node_id]={node_id}&filter[analysis_id]={analysis_id}',
                                headers=[('Connection', 'close')]))
    try:
        response.raise_for_status()
    except HTTPStatusError as e:
        print(f"Error getting node-analysis id: {e}")
        return None
    data = response.json().get('data', [])
    if data:
        return data[0]['id']
    else:
        return None

    #return response.json()['data'][0]['id']


def _get_node_id() -> Optional[str]:
    """
    robot-id: 170c1cd8-d468-41c3-9bee-8e3cb1813210
    endpoint: GET https://core.privateaim.dev/nodes?filter[robot_id]=170c1cd8-d468-41c3-9bee-8e3cb1813210
    node id read from object: e64a1551-4007-4754-a7b9-57c9cb56a7c5
    :return: node ID
    """
    robot_id, robot_secret, hub_url_core = (os.getenv('HUB_ROBOT_USER'),
                                            os.getenv('HUB_ROBOT_SECRET'),
                                            os.getenv('HUB_URL_CORE'))

    response = asyncio.run(AsyncClient(base_url=hub_url_core,
                                       headers={"accept": "application/json",
                                                "Authorization": f"Bearer {get_hub_token()['hub_token']}"})
                           .get(f'/nodes?filter[robot_id]={robot_id}',
                                headers=[('Connection', 'close')]))
    try:
        response.raise_for_status()
    except HTTPStatusError as e:
        print(f"Error getting node id: {e}")
        return None
    data = response.json().get('data', [])
    if data:
        return data[0]['id']
    else:
        return None

    #return response.json()['data'][0]['id']


def _get_status(deployments: list[Analysis]) -> dict[Literal['status'],
                                                     dict[str, Literal['started', 'running', 'stopped', 'finished']]]:
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
        #try:
        #    print(f"analyse status: {response.json()}")
        #except json.decoder.JSONDecodeError:
        #    print("No JSON in response")
        analysis_health_status = response.json()['status']
        if analysis_health_status == 'finished':
            health_status = 'finished'
        elif analysis_health_status == 'ongoing':
            health_status = 'ongoing'
        else:
            health_status = 'failed'
        return health_status

    except ConnectError as e:
        print(f"Connection to http://nginx-{deployment_name}:80 yielded an error: {e}")
        return None
