import json
import os
from typing import Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tobedeleted.constants import AnalysisStatus
from .db_models import Base, AnalysisDB


class Database:
    def __init__(self) -> None:
        host = os.getenv("POSTGRES_HOST")
        port = "5432"
        user = os.getenv("POSTGRES_USER")
        password = os.getenv("POSTGRES_PASSWORD")
        print(f'postgresql+psycopg2://{user}:{password}@{host}:{port}')
        self.engine = create_engine(f'postgresql+psycopg2://{user}:{password}@{host}:{port}')
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.session = self.SessionLocal()

    def reset_db(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def get_deployment(self, deployment_name: str) -> Optional[AnalysisDB]:
        return self.session.query(AnalysisDB).filter_by(**{"deployment_name": deployment_name}).first()

    def get_deployments(self, analysis_id: str) -> list[AnalysisDB]:
        return self.session.query(AnalysisDB).filter_by(**{"analysis_id": analysis_id}).all()

    def create_analysis(self,
                        analysis_id: str,
                        deployment_name: str,
                        project_id: str,
                        pod_ids: list[str],
                        status: str,
                        ports: list[int],
                        image_registry_address: str) -> AnalysisDB:
        analysis = AnalysisDB(analysis_id=analysis_id,
                              deployment_name=deployment_name,
                              project_id=project_id,
                              pod_ids=json.dumps(pod_ids),
                              status=status,
                              ports=json.dumps(ports),
                              image_registry_address=image_registry_address)
        self.session.add(analysis)
        self.session.commit()
        return analysis

    def update_analysis(self, analysis_id: str, **kwargs) -> list[AnalysisDB]:
        analysis = self.get_deployments(analysis_id)
        for deployment in analysis:
            if deployment:
                for key, value in kwargs.items():
                    setattr(deployment, key, value)
                self.session.commit()
        return analysis

    def update_deployment(self, deployment_name: str, **kwargs) -> AnalysisDB:
        deployment = self.get_deployment(deployment_name)
        for key, value in kwargs.items():
            print(f"Setting {key} to {value}")
            setattr(deployment, key, value)
        self.session.commit()
        return deployment

    def delete_analysis(self, analysis_id: str) -> None:
        analysis = self.get_deployments(analysis_id)
        for deployment in analysis:
            if deployment:
                self.session.delete(deployment)
                self.session.commit()

    def close(self) -> None:
        self.session.close()

    def get_analysis_ids(self) -> list[str]:
        return [analysis.analysis_id for analysis in self.session.query(AnalysisDB) if analysis is not None]

    def get_deployment_ids(self) -> list[str]:
        return [analysis.deployment_name for analysis in self.session.query(AnalysisDB) if analysis is not None]

    def get_deployment_pod_ids(self, deployment_name: str) -> list[str]:
        return self.get_deployment(deployment_name).pod_ids

    def get_analysis_pod_ids(self, analysis_id: str) -> list[str]:
        return [deployment.pod_ids for deployment in self.get_deployments(analysis_id) if deployment is not None]

    def update_analysis_status(self, analysis_id: str, status: AnalysisStatus) -> None:
        self.update_analysis(analysis_id, status=status)

    def update_deployment_status(self, deployment_name: str, status: AnalysisStatus) -> None:
        print(f"Updating deployment {deployment_name} to status {status}")
        self.update_deployment(deployment_name, status=status)

    def stop_analysis(self, analysis_id: str) -> None:
        self.update_analysis_status(analysis_id, status=AnalysisStatus.STOPPED.value)