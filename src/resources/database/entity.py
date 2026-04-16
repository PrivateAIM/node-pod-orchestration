import json
import os
import time
from typing import Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.status.constants import AnalysisStatus
from src.resources.database.db_models import Base, AnalysisDB
from src.utils.po_logging import get_logger


logger = get_logger()


class Database:
    """Thin CRUD wrapper around the PostgreSQL-backed analysis database.

    Each method opens a short-lived SQLAlchemy session via the ``SessionLocal``
    factory and commits before returning. ``pool_pre_ping`` and a one-hour
    recycle window guard against stale connections.
    """

    def __init__(self) -> None:
        """Connect to PostgreSQL using ``POSTGRES_*`` env vars and create tables."""
        host = os.getenv('POSTGRES_HOST')
        port = "5432"
        user = os.getenv('POSTGRES_USER')
        password = os.getenv('POSTGRES_PASSWORD')
        database = os.getenv('POSTGRES_DB')
        conn_uri = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"

        logger.debug(f"Connecting to database at postgresql+psycopg2://{user}:*******@{host}:{port}/{database}")

        self.engine = create_engine(conn_uri,
                                    pool_pre_ping=True,
                                    pool_recycle=3600)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def reset_db(self) -> None:
        """Drop and recreate all tables. Destructive — wipes all analyses."""
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def get_deployment(self, deployment_name: str) -> Optional[AnalysisDB]:
        """Return the deployment row with the given unique name, or ``None``."""
        with self.SessionLocal() as session:
            return session.query(AnalysisDB).filter_by(**{'deployment_name': deployment_name}).first()

    def get_latest_deployment(self, analysis_id: str) -> Optional[AnalysisDB]:
        """Return the most recently created deployment for an analysis, or ``None``."""
        with self.SessionLocal() as session:
            deployment = session.query(AnalysisDB).filter_by(**{'analysis_id': analysis_id}).order_by(AnalysisDB.time_created.desc()).first()
            return deployment

    def analysis_is_running(self, analysis_id: str) -> bool:
        """Return True if the latest deployment is not in a terminal status.

        Terminal statuses are ``EXECUTED``, ``STOPPED``, and ``FAILED``.
        """
        latest_deployment = self.get_latest_deployment(analysis_id)
        if latest_deployment is not None:
            return latest_deployment.status not in [AnalysisStatus.EXECUTED.value,
                                                    AnalysisStatus.STOPPED.value,
                                                    AnalysisStatus.FAILED.value]
        return False

    def get_deployments(self, analysis_id: str) -> list[AnalysisDB]:
        """Return every deployment row recorded for an analysis (all restarts)."""
        with self.SessionLocal() as session:
            return session.query(AnalysisDB).filter_by(**{'analysis_id': analysis_id}).all()

    def create_analysis(self,
                        analysis_id: str,
                        deployment_name: str,
                        project_id: str,
                        pod_ids: Optional[list[str]],
                        status: str,
                        log: Optional[str],
                        registry_url: str,
                        image_url: str,
                        registry_user: str,
                        registry_password: str,
                        kong_token: str,
                        restart_counter: int,
                        progress: int,
                        namespace: str = 'default') -> AnalysisDB:
        """Insert a new analysis deployment row and return the persisted object.

        ``pod_ids`` is stored JSON-encoded and ``time_created`` is stamped with
        the current Unix time.
        """
        analysis = AnalysisDB(analysis_id=analysis_id,
                              deployment_name=deployment_name,
                              project_id=project_id,
                              pod_ids=json.dumps(pod_ids),
                              status=status,
                              log=log,
                              registry_url=registry_url,
                              image_url=image_url,
                              registry_user=registry_user,
                              registry_password=registry_password,
                              namespace=namespace,
                              kong_token=kong_token,
                              restart_counter=restart_counter,
                              progress=progress,
                              time_created=time.time())
        with self.SessionLocal() as session:
            session.add(analysis)
            session.commit()
            session.refresh(analysis)
        return analysis

    def update_analysis(self, analysis_id: str, **kwargs) -> list[AnalysisDB]:
        """Apply ``kwargs`` as column updates to every deployment for an analysis.

        Args:
            analysis_id: Analysis whose deployment rows should be updated.
            **kwargs: Column/value pairs to ``setattr`` on each row.

        Returns:
            The list of updated deployment rows.
        """
        with self.SessionLocal() as session:
            analysis = session.query(AnalysisDB).filter_by(**{'analysis_id': analysis_id}).all()
            for deployment in analysis:
                if deployment:
                    for key, value in kwargs.items():
                        setattr(deployment, key, value)

                    session.commit()
            return analysis

    def update_deployment(self, deployment_name: str, **kwargs) -> AnalysisDB:
        """Apply ``kwargs`` as column updates to a single deployment row.

        Args:
            deployment_name: Unique deployment name to update.
            **kwargs: Column/value pairs to ``setattr`` on the row.

        Returns:
            The updated deployment row.
        """
        with self.SessionLocal() as session:
            deployment = session.query(AnalysisDB).filter_by(**{'deployment_name': deployment_name}).first()
            for key, value in kwargs.items():
                setattr(deployment, key, value)
            session.commit()
            return deployment

    def delete_analysis(self, analysis_id: str) -> None:
        """Delete every deployment row belonging to an analysis."""
        with self.SessionLocal() as session:
            analysis = session.query(AnalysisDB).filter_by(**{'analysis_id': analysis_id}).all()
            for deployment in analysis:
                if deployment:
                    session.delete(deployment)
                    session.commit()

    def delete_deployment(self, deployment_name: str) -> None:
        """Delete a single deployment row by its unique name."""
        with self.SessionLocal() as session:
            deployment = session.query(AnalysisDB).filter_by(deployment_name=deployment_name).first()
            if deployment:
                session.delete(deployment)
                session.commit()

    def close(self) -> None:
        """Open and immediately close a session to flush pooled connections."""
        with self.SessionLocal() as session:
            session.close()

    def get_analysis_ids(self) -> list[str]:
        """Return every analysis id currently tracked in the database."""
        with self.SessionLocal() as session:
            return [analysis.analysis_id for analysis in session.query(AnalysisDB).all() if analysis is not None]

    def get_deployment_ids(self) -> list[str]:
        """Return every deployment name currently tracked in the database."""
        with self.SessionLocal() as session:
            return [analysis.deployment_name for analysis in session.query(AnalysisDB).all() if analysis is not None]

    def get_deployment_pod_ids(self, deployment_name: str) -> list[str]:
        """Return the JSON-encoded pod id list recorded for a single deployment."""
        return self.get_deployment(deployment_name).pod_ids

    def get_analysis_pod_ids(self, analysis_id: str) -> list[str]:
        """Return the JSON-encoded pod id list for each deployment of an analysis."""
        return [deployment.pod_ids for deployment in self.get_deployments(analysis_id) if deployment is not None]

    def get_analysis_log(self, analysis_id: str) -> str:
        """Return the accumulated log string for the latest deployment, or ``""``."""
        deployment = self.get_latest_deployment(analysis_id)
        if deployment is not None:
            log = deployment.log
            if log is not None:
                return log
        return ""

    def get_analysis_progress(self, analysis_id: str) -> Optional[int]:
        """Return the latest recorded progress (0-100), or ``None``."""
        deployment = self.get_latest_deployment(analysis_id)
        if deployment is not None:
            progress = deployment.progress
            if progress is not None:
                return progress
        return None

    def update_analysis_log(self, analysis_id: str, log: str) -> None:
        """Append ``log`` to the existing log column for every deployment of an analysis."""
        latest = self.get_analysis_log(analysis_id)
        if latest:
            log = latest + "\n" + log
        self.update_analysis(analysis_id, log=log)

    def progress_valid(self, analysis_id: str, progress: int) -> bool:
        """Return True if ``progress`` is strictly greater than stored progress and ``<= 100``."""
        latest = self.get_analysis_progress(analysis_id)
        if (latest is not None) and (latest < progress <= 100):
            return True
        return False

    def update_analysis_progress(self, analysis_id: str, progress: int) -> None:
        """Set the progress column for every deployment of an analysis."""
        self.update_analysis(analysis_id, progress=progress)

    def update_analysis_status(self, analysis_id: str, status: str) -> None:
        """Set the status column for every deployment of an analysis."""
        self.update_analysis(analysis_id, status=status)

    def update_deployment_status(self, deployment_name: str, status: str) -> None:
        """Set the status column for a single deployment (logged at ACTION level)."""
        logger.action(f"Updating deployment {deployment_name} to status {status}")
        self.update_deployment(deployment_name, status=status)

    def stop_analysis(self, analysis_id: str) -> None:
        """Mark every deployment of an analysis as ``STOPPED`` in the database."""
        self.update_analysis_status(analysis_id, status=AnalysisStatus.STOPPED.value)

    def extract_analysis_body(self, analysis_id: str) -> Optional[dict]:
        """Return the subset of fields needed to recreate an analysis from the first stored deployment.

        Used when unstucking an analysis to rebuild a ``CreateAnalysis`` body.

        Returns:
            Dict with registry/namespace/token fields and ``progress=0``, or
            ``None`` when the analysis is unknown.
        """
        analysis = self.get_deployments(analysis_id)
        if analysis:
            analysis = analysis[0]
            return {'analysis_id': analysis.analysis_id,
                    'project_id': analysis.project_id,
                    'registry_url': analysis.registry_url,
                    'image_url': analysis.image_url,
                    'registry_user': analysis.registry_user,
                    'registry_password': analysis.registry_password,
                    'namespace': analysis.namespace,
                    'kong_token': analysis.kong_token,
                    'restart_counter': analysis.restart_counter,
                    'progress': 0}
        return None

    def delete_old_deployments_from_db(self, analysis_id: str) -> None:
        """Keep only the most recent deployment for an analysis; delete the rest.

        Used after a restart/unstuck so history does not accumulate stale
        deployment rows.
        """
        deployments = self.get_deployments(analysis_id)
        deployments = sorted(deployments, key=lambda x: x.time_created, reverse=True)
        for deployment in deployments[1:]:
            self.delete_deployment(deployment.deployment_name)
