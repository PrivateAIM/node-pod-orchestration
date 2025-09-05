import json
import os
import time
from typing import Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.status.constants import AnalysisStatus
from .db_models import Base, AnalysisDB


class Database:
    def __init__(self) -> None:
        host = os.getenv("POSTGRES_HOST")
        port = "5432"
        user = os.getenv("POSTGRES_USER")
        password = os.getenv("POSTGRES_PASSWORD")
        database = os.getenv("POSTGRES_DB")
        conn_uri = f'postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}'
        print(conn_uri)
        self.engine = create_engine(conn_uri,
                                    pool_pre_ping=True,
                                    pool_recycle=3600)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def reset_db(self) -> None:
        #TODO : for archive purposes only
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def get_deployment(self, deployment_name: str) -> Optional[AnalysisDB]:
        with self.SessionLocal() as session:
            return session.query(AnalysisDB).filter_by(**{"deployment_name": deployment_name}).first()

    def get_latest_deployment(self, analysis_id: str) -> Optional[AnalysisDB]:
        with self.SessionLocal() as session:
            deployments = session.query(AnalysisDB).filter_by(**{"analysis_id": analysis_id}).all()
            if deployments:
                return deployments[-1]
            return None

    def get_deployments(self, analysis_id: str) -> list[AnalysisDB]:
        with self.SessionLocal() as session:
            return session.query(AnalysisDB).filter_by(**{"analysis_id": analysis_id}).all()

    def create_analysis(self,
                        analysis_id: str,
                        deployment_name: str,
                        project_id: str,
                        pod_ids: list[str],
                        status: str,
                        registry_url: str,
                        image_url: str,
                        registry_user: str,
                        registry_password: str,
                        kong_token: str,
                        restart_counter: int ,
                        namespace: str = 'default') -> AnalysisDB:
        analysis = AnalysisDB(analysis_id=analysis_id,
                              deployment_name=deployment_name,
                              project_id=project_id,
                              pod_ids=json.dumps(pod_ids),
                              status=status,
                              registry_url=registry_url,
                              image_url=image_url,
                              registry_user=registry_user,
                              registry_password=registry_password,
                              namespace=namespace,
                              kong_token=kong_token,
                              restart_counter=restart_counter,
                              time_created=time.time())
        with self.SessionLocal() as session:
            session.add(analysis)
            session.commit()
            session.refresh(analysis)
        return analysis

    def update_analysis(self, analysis_id: str, **kwargs) -> list[AnalysisDB]:
        with self.SessionLocal() as session:
            analysis = session.query(AnalysisDB).filter_by(**{"analysis_id": analysis_id}).all()
            for deployment in analysis:
                if deployment:
                    for key, value in kwargs.items():
                        print(f"in update analysis Setting {key} to {value}")
                        setattr(deployment, key, value)

                    session.commit()
            return analysis

    def update_deployment(self, deployment_name: str, **kwargs) -> AnalysisDB:
        with self.SessionLocal() as session:
            deployment = session.query(AnalysisDB).filter_by(**{"deployment_name": deployment_name}).first()
            print(kwargs.items())
            for key, value in kwargs.items():
                setattr(deployment, key, value)
            session.commit()
            return deployment

    def delete_analysis(self, analysis_id: str) -> None:
        with self.SessionLocal() as session:
            analysis = session.query(AnalysisDB).filter_by(**{"analysis_id": analysis_id}).all()
            for deployment in analysis:
                if deployment:
                    session.delete(deployment)
                    session.commit()

    def delete_deployment(self, deployment_name: str) -> None:
        with self.SessionLocal() as session:
            deployment = session.query(AnalysisDB).filter_by(deployment_name=deployment_name).first()
            if deployment:
                session.delete(deployment)
                session.commit()

    def close(self) -> None:
        with self.SessionLocal() as session:
            session.close()

    def get_analysis_ids(self) -> list[str]:
        with self.SessionLocal() as session:
            return [analysis.analysis_id for analysis in session.query(AnalysisDB).all() if analysis is not None]

    def get_deployment_ids(self) -> list[str]:
        with self.SessionLocal() as session:
            return [analysis.deployment_name for analysis in session.query(AnalysisDB).all() if analysis is not None]

    def get_deployment_pod_ids(self, deployment_name: str) -> list[str]:
        return self.get_deployment(deployment_name).pod_ids

    def get_analysis_pod_ids(self, analysis_id: str) -> list[str]:
        return [deployment.pod_ids for deployment in self.get_deployments(analysis_id) if deployment is not None]

    def get_analysis_log(self, analysis_id: str) -> str:
        deployment = self.get_deployments(analysis_id)[0]

        if deployment is not None:
            return deployment.log
        return ""

    def update_analysis_log(self, analysis_id: str, log: str) -> None:
        log = self.get_analysis_log(analysis_id) + "\n" + log
        self.update_analysis(analysis_id, log=log)

    def update_analysis_status(self, analysis_id: str, status: str) -> None:
        self.update_analysis(analysis_id, status=status)

    def update_deployment_status(self, deployment_name: str, status: str) -> None:
        print(f"Updating deployment {deployment_name} to status {status}")
        self.update_deployment(deployment_name, status=status)

    def stop_analysis(self, analysis_id: str) -> None:
        self.update_analysis_status(analysis_id, status=AnalysisStatus.STOPPED.value)

    def extract_analysis_body(self, analysis_id: str) -> Optional[dict]:
        analysis = self.get_deployments(analysis_id)
        if analysis:
            analysis = analysis[0]
            return {"analysis_id": analysis.analysis_id,
                    "project_id": analysis.project_id,
                    "registry_url": analysis.registry_url,
                    "image_url": analysis.image_url,
                    "registry_user": analysis.registry_user,
                    "registry_password": analysis.registry_password,
                    "namespace": analysis.namespace,
                    "kong_token": analysis.kong_token,
                    "restart_counter": analysis.restart_counter}
        return None

    def delete_old_deployments_db(self, analysis_id: str) -> None:
        deployments = self.get_deployments(analysis_id)
        deployments = sorted(deployments, key=lambda x: x.time_created, reverse=True)
        for deployment in deployments[1:]:
            self.delete_deployment(deployment.deployment_name)