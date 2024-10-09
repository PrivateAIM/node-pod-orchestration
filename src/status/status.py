import time
import asyncio
from typing import Literal
from httpx import AsyncClient

from src.resources.database.entity import Database
from src.resources.analysis.entity import Analysis, AnalysisStatus, read_db_analysis
from src.utils.token import delete_keycloak_client


def status_loop(database: Database):
    """
    Send the status of the analysis to the HUB, kill deployment if analysis finished

    :return:
    """
    while True:
        for analysis_id in database.get_analysis_ids():
            deployments = [read_db_analysis(deployment) for deployment in database.get_deployments(analysis_id)]
            database_status = _get_status(deployments)
            if database_status == 'running':
                print(f"analysis_id: {analysis_id}")
                internal_status = asyncio.run(_get_internal_analysis_status(deployments))
                if internal_status == 'finished':  # if analysis successful
                    # TODO: final local log save (minio?)  # archive logs
                    _delete_analysis(analysis_id, database, deployments)  # delete analysis

            # TODO: submit database_status to HUB
        time.sleep(100)


def _get_status(deployments: list[Analysis]):
    return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}

def _delete_analysis(analysis_id: str, database: Database, deployments: list[Analysis]):
    for deployment in deployments:
        if deployment.status != AnalysisStatus.STOPPED.value:
            deployment.stop(database)
            deployment.status = AnalysisStatus.STOPPED.value
    delete_keycloak_client(analysis_id)
    database.delete_analysis(analysis_id)
    return {"status": {deployment.deployment_name: deployment.status for deployment in deployments}}

async def _get_internal_analysis_status(deployments: list[Analysis]) \
        -> dict[str, Literal['finished', 'ongoing', 'failed']]:
    health_status_list = {}
    for deployment in deployments:
        if deployment.deployment_name is not None:
            analysis_health_status = await AsyncClient(base_url=f'http://analysis-nginx-{deployment.deployment_name}:80').get('/analysis/healthz').json()['status']

            if analysis_health_status == 'finished':
                health_status_list[deployment.deployment_name] = 'finished'
            elif analysis_health_status == 'ongoing':
                health_status_list[deployment.deployment_name] = 'ongoing'
            else:
                health_status_list[deployment.deployment_name] = 'failed'
    return health_status_list
