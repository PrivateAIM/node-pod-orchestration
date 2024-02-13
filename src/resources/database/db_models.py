from typing import Any
from enum import Enum
from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.ext.declarative import as_declarative, declared_attr


@as_declarative()
class Base:
    id: Any
    __name__: str

    # Generate __tablename__ automatically
    @declared_attr
    def __tablename__(cls) -> str:
        return cls.__name__.lower()


class Analysis(Base):
    __tablename__ = "analysis"
    id = Column(Integer, primary_key=True, index=True)
    analysis_id = Column(String, unique=True, index=True)
    image_registry_address = Column(String, nullable=True)
    ports = Column(JSON, nullable=True)
    status = Column(String, nullable=True)
    log = Column(String, nullable=True)
    pod_ids = Column(JSON, nullable=True)
    minio_bucket = Column(String, nullable=True)
    minio_bucket_id = Column(String, nullable=True)
    time_created = Column(DateTime, nullable=True)
    time_updated = Column(DateTime, nullable=True)



