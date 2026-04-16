from typing import Any
from sqlalchemy import JSON, Column, Integer, String, Float
from sqlalchemy.ext.declarative import as_declarative, declared_attr


@as_declarative()
class Base:
    """SQLAlchemy declarative base with an auto-generated ``__tablename__``."""

    id: Any
    __name__: str

    # Generate __tablename__ automatically
    @declared_attr
    def __tablename__(cls) -> str:
        """Derive the SQL table name from the lowercased class name."""
        return cls.__name__.lower()


class AnalysisDB(Base):
    """ORM model tracking the current state of an analysis deployment."""

    __tablename__ = "analysis"
    id = Column(Integer, primary_key=True, index=True)
    deployment_name = Column(String, unique=True, index=True)
    analysis_id = Column(String, unique=False, index=True)
    project_id = Column(String, unique=False, index=True)
    registry_url = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    registry_user = Column(String, nullable=True)
    registry_password = Column(String, nullable=True)
    status = Column(String, nullable=True)
    log = Column(String, nullable=True)
    pod_ids = Column(JSON, nullable=True)
    namespace = Column(String, nullable=True)
    kong_token = Column(String, nullable=True)
    restart_counter = Column(Integer, nullable=True, default=0)
    progress = Column(Integer, nullable=True, default=0)
    time_created = Column(Float, nullable=True)
    time_updated = Column(Float, nullable=True)


class ArchiveDB(Base):
    """ORM model mirroring :class:`AnalysisDB` for completed analyses kept for history."""

    __tablename__ = "archive"
    id = Column(Integer, primary_key=True, index=True)
    deployment_name = Column(String, unique=True, index=True)
    analysis_id = Column(String, unique=False, index=True)
    project_id = Column(String, unique=False, index=True)
    registry_url = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    registry_user = Column(String, nullable=True)
    registry_password = Column(String, nullable=True)
    status = Column(String, nullable=True)
    log = Column(String, nullable=True)
    pod_ids = Column(JSON, nullable=True)
    namespace = Column(String, nullable=True)
    kong_token = Column(String, nullable=True)
    restart_counter = Column(Integer, nullable=True, default=0)
    progress = Column(Integer, nullable=True, default=0)
    time_created = Column(Float, nullable=True)
    time_updated = Column(Float, nullable=True)

