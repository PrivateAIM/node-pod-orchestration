import json
from typing import Optional

from pydantic import BaseModel

from src.k8s.kubernetes import create_analysis_deployment, delete_deployment
from src.utils.token import create_analysis_tokens
from src.resources.database.db_models import AnalysisDB
from src.resources.database.entity import Database
from src.status.constants import AnalysisStatus


class Analysis(BaseModel):
    """Runtime model describing a single analysis deployment.

    Combines the user-supplied creation payload with runtime-derived fields
    (deployment name, Keycloak/Kong tokens, pod ids, current status) and
    exposes ``start`` / ``stop`` helpers that drive the Kubernetes resources.
    """

    analysis_id: str
    project_id: str
    registry_url: str
    image_url: str
    registry_user: str
    registry_password: str
    namespace: str = 'default'
    kong_token: str

    restart_counter: int = 0
    progress: int = 0
    deployment_name: str = ''
    tokens: Optional[dict[str, str]] = None
    analysis_config: Optional[dict[str, str]] = None
    status: str = AnalysisStatus.STARTING.value
    log: Optional[str] = None
    pod_ids: Optional[list[str]] = None

    def start(self, database: Database, namespace: str = 'default') -> None:
        """Deploy the analysis on Kubernetes and persist it in the database.

        Generates the deployment name, mints the Kong and Keycloak tokens,
        assembles the analysis env, creates the Kubernetes resources, and then
        writes an ``AnalysisDB`` row tracking the new deployment.

        Args:
            database: Database wrapper used to persist the new deployment.
            namespace: Namespace the Kubernetes resources are created in.
        """
        self.status = AnalysisStatus.STARTED.value
        self.deployment_name = "analysis-" + self.analysis_id + "-" + str(self.restart_counter)
        self.tokens = create_analysis_tokens(kong_token=self.kong_token, analysis_id=self.analysis_id)
        self.analysis_config = self.tokens
        self.analysis_config['ANALYSIS_ID'] = self.analysis_id
        self.analysis_config['PROJECT_ID'] = self.project_id
        self.analysis_config['DEPLOYMENT_NAME'] = self.deployment_name
        self.namespace = namespace
        self.pod_ids = create_analysis_deployment(name=self.deployment_name,
                                                  image=self.image_url,
                                                  env=self.analysis_config,
                                                  namespace=namespace)

        database.create_analysis(analysis_id=self.analysis_id,
                                 deployment_name=self.deployment_name,
                                 project_id=self.project_id,
                                 pod_ids=self.pod_ids,
                                 status=self.status,
                                 log=self.log,
                                 registry_url=self.registry_url,
                                 image_url=self.image_url,
                                 registry_user=self.registry_user,
                                 registry_password=self.registry_password,
                                 namespace=self.namespace,
                                 kong_token=self.kong_token,
                                 restart_counter=self.restart_counter,
                                 progress=self.progress)

    def stop(self,
             database: Database,
             log: Optional[str] = None,
             status: str = AnalysisStatus.STOPPED.value) -> None:
        """Tear down the Kubernetes deployment and update the database row.

        Args:
            database: Database wrapper used to persist the final status/log.
            log: Optional log snapshot to persist before deletion.
            status: Terminal status to record (defaults to ``STOPPED``).
        """
        if log is not None:
            self.log = log
        self.status = status
        # Delete the deployment from Kubernetes
        delete_deployment(self.deployment_name, namespace=self.namespace)
        # Update the database
        database.update_deployment(self.deployment_name, status=self.status)
        database.update_deployment(self.deployment_name, log=self.log)


def read_db_analysis(analysis: AnalysisDB) -> Analysis:
    """Convert a persisted :class:`AnalysisDB` row into a runtime :class:`Analysis`.

    Decodes the JSON-encoded ``pod_ids`` column back into a Python list.
    """
    return Analysis(analysis_id=analysis.analysis_id,
                    deployment_name=analysis.deployment_name,
                    project_id=analysis.project_id,
                    registry_url=analysis.registry_url,
                    image_url=analysis.image_url,
                    registry_user=analysis.registry_user,
                    registry_password=analysis.registry_password,
                    status=analysis.status,
                    pod_ids=json.loads(analysis.pod_ids),
                    log=analysis.log,
                    namespace=analysis.namespace,
                    kong_token=analysis.kong_token,
                    restart_counter=analysis.restart_counter,
                    progress=analysis.progress)


class CreateAnalysis(BaseModel):
    """Request body accepted by ``POST /po/`` to create a new analysis."""

    analysis_id: str
    project_id: str
    registry_url: str
    image_url: str
    registry_user: str
    registry_password: str
    kong_token: str
    restart_counter: int = 0
    progress: int = 0
