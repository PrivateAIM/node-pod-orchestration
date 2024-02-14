import os
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .db_models import Base, Analysis


class Database:

    def __init__(self):
        host = "postgresql-service"
        port = "5432"
        user = "postgres"
        password = "postgres"
        print(f'postgresql+psycopg2://{user}:{password}@{host}:{port}')
        self.engine = create_engine(f'postgresql+psycopg2://{user}:{password}@{host}:{port}')
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.session = self.SessionLocal()

    def reset_db(self):
        Base.metadata.drop_all(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def get_analysis(self, analysis_id):
        return self.session.query(Analysis).filter(Analysis.analysis_id == analysis_id).first()

    def create_analysis(self, analysis_id: str,
                        pod_ids: list[str] = None,
                        status: str = "Pending"):
        analysis = Analysis(analysis_id=analysis_id, pod_ids=json.dumps(pod_ids), status=status)
        self.session.add(analysis)
        self.session.commit()
        return analysis

    def update_analysis(self, analysis_id, **kwargs):
        analysis = self.session.query(Analysis).filter(Analysis.analysis_id == analysis_id).first()
        if analysis:
            for key, value in kwargs.items():
                setattr(analysis, key, value)
            self.session.commit()
        return analysis

    def delete_analysis(self, analysis_id):
        analysis = self.session.query(Analysis).filter(Analysis.analysis_id == analysis_id).first()
        if analysis:
            self.session.delete(analysis)
            self.session.commit()

    def close(self):
        self.session.close()

    def get_analysis_ids(self) -> list[str]:
        return [analysis.analysis_id for analysis in self.get_entrys()]

    def get_pod_ids(self, analysis_id: str) -> list[str]:
        return self.get_analysis(analysis_id).pod_ids
