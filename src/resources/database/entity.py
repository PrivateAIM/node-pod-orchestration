import json
from typing import Optional
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.resources.analysis.constants import AnalysisStatus
from .db_models import Base, Analysis


class Database:

    def __init__(self) -> None:
        host = "postgresql-service"
        port = "5432"
        user = "postgres"
        password = "postgres"
        print(f'postgresql+psycopg2://{user}:{password}@{host}:{port}')
        self.engine = create_engine(f'postgresql+psycopg2://{user}:{password}@{host}:{port}')
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.session = self.SessionLocal()

    def reset_db(self) -> None:
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def get_analysis(self, analysis_id: str) -> Optional[Analysis]:
        return self.session.query(Analysis).filter_by(**{"analysis_id": analysis_id}).first()

    def create_analysis(self,
                        analysis_id: str,
                        pod_ids: list[str],
                        status: str,
                        ports: list[int],
                        image_registry_address: str,
                        log: str = None) -> Analysis:
        analysis = Analysis(analysis_id=analysis_id,
                            pod_ids=json.dumps(pod_ids),
                            status=status,
                            ports=json.dumps(ports),
                            image_registry_address=image_registry_address)
        self.session.add(analysis)
        self.session.commit()
        return analysis

    def update_analysis(self, analysis_id: str, **kwargs) -> Analysis:
        analysis = self.get_analysis(analysis_id)
        if analysis:
            for key, value in kwargs.items():
                setattr(analysis, key, value)
            self.session.commit()
        return analysis

    def delete_analysis(self, analysis_id) -> None:
        analysis = self.get_analysis(analysis_id)
        if analysis:
            self.session.delete(analysis)
            self.session.commit()

    def close(self) -> None:
        self.session.close()

    def get_analysis_ids(self) -> list[str]:
        return [analysis.analysis_id for analysis in self.session.query(Analysis)]

    def get_pod_ids(self, analysis_id: str) -> list[str]:
        return self.get_analysis(analysis_id).pod_ids

    def stop_analysis(self, analysis_id: str) -> None:
        self.update_analysis(analysis_id, status=AnalysisStatus.STOPPED.value)

