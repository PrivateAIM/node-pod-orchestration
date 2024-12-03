# models.py
from sqlalchemy import JSON, Column, DateTime, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func

Base = declarative_base()

class AnalysisBase(Base):
    __abstract__ = True
    id = Column(Integer, primary_key=True, index=True)
    deployment_name = Column(String, unique=True, index=True, nullable=False)
    analysis_id = Column(String, index=True, nullable=False)
    project_id = Column(String, index=True, nullable=False)
    image_registry_address = Column(String)
    ports = Column(JSON)
    status = Column(String)
    log = Column(String)
    pod_ids = Column(JSON)
    time_created = Column(DateTime(timezone=True), server_default=func.now())
    time_updated = Column(DateTime(timezone=True), onupdate=func.now())

class AnalysisDB(AnalysisBase):
    __tablename__ = "analysis"

class ArchiveDB(AnalysisBase):
    __tablename__ = "archive"


