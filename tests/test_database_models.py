"""Tests for src/resources/database/db_models.py"""

from sqlalchemy import JSON, Float, Integer, String

from src.resources.database.db_models import AnalysisDB, ArchiveDB

_SHARED_COLUMNS = [
    "id",
    "deployment_name",
    "analysis_id",
    "project_id",
    "registry_url",
    "image_url",
    "registry_user",
    "registry_password",
    "status",
    "log",
    "pod_ids",
    "namespace",
    "kong_token",
    "restart_counter",
    "progress",
    "time_created",
    "time_updated",
]


class TestAnalysisDB:
    def test_table_name(self):
        assert AnalysisDB.__tablename__ == "analysis"

    def test_all_columns_exist(self):
        cols = {c.name for c in AnalysisDB.__table__.columns}
        assert set(_SHARED_COLUMNS) == cols

    def test_id_is_primary_key(self):
        col = AnalysisDB.__table__.c["id"]
        assert col.primary_key
        assert isinstance(col.type, Integer)

    def test_deployment_name_is_unique(self):
        col = AnalysisDB.__table__.c["deployment_name"]
        assert col.unique
        assert isinstance(col.type, String)

    def test_analysis_id_is_indexed(self):
        col = AnalysisDB.__table__.c["analysis_id"]
        assert col.index
        assert isinstance(col.type, String)

    def test_project_id_is_indexed(self):
        col = AnalysisDB.__table__.c["project_id"]
        assert col.index
        assert isinstance(col.type, String)

    def test_pod_ids_is_json(self):
        col = AnalysisDB.__table__.c["pod_ids"]
        assert isinstance(col.type, JSON)
        assert col.nullable

    def test_restart_counter_default(self):
        col = AnalysisDB.__table__.c["restart_counter"]
        assert isinstance(col.type, Integer)
        assert col.default.arg == 0

    def test_progress_default(self):
        col = AnalysisDB.__table__.c["progress"]
        assert isinstance(col.type, Integer)
        assert col.default.arg == 0

    def test_time_created_is_float(self):
        col = AnalysisDB.__table__.c["time_created"]
        assert isinstance(col.type, Float)
        assert col.nullable

    def test_time_updated_is_float(self):
        col = AnalysisDB.__table__.c["time_updated"]
        assert isinstance(col.type, Float)
        assert col.nullable

    def test_nullable_string_columns(self):
        nullable_cols = [
            "registry_url", "image_url", "registry_user", "registry_password",
            "status", "log", "namespace", "kong_token",
        ]
        for name in nullable_cols:
            col = AnalysisDB.__table__.c[name]
            assert col.nullable, f"{name} should be nullable"
            assert isinstance(col.type, String), f"{name} should be String"


class TestArchiveDB:
    def test_table_name(self):
        assert ArchiveDB.__tablename__ == "archive"

    def test_all_columns_exist(self):
        cols = {c.name for c in ArchiveDB.__table__.columns}
        assert set(_SHARED_COLUMNS) == cols

    def test_id_is_primary_key(self):
        col = ArchiveDB.__table__.c["id"]
        assert col.primary_key
        assert isinstance(col.type, Integer)

    def test_deployment_name_is_unique(self):
        col = ArchiveDB.__table__.c["deployment_name"]
        assert col.unique
        assert isinstance(col.type, String)

    def test_analysis_id_is_indexed(self):
        col = ArchiveDB.__table__.c["analysis_id"]
        assert col.index
        assert isinstance(col.type, String)

    def test_project_id_is_indexed(self):
        col = ArchiveDB.__table__.c["project_id"]
        assert col.index
        assert isinstance(col.type, String)

    def test_pod_ids_is_json(self):
        col = ArchiveDB.__table__.c["pod_ids"]
        assert isinstance(col.type, JSON)
        assert col.nullable

    def test_restart_counter_default(self):
        col = ArchiveDB.__table__.c["restart_counter"]
        assert isinstance(col.type, Integer)
        assert col.default.arg == 0

    def test_progress_default(self):
        col = ArchiveDB.__table__.c["progress"]
        assert isinstance(col.type, Integer)
        assert col.default.arg == 0

    def test_time_created_is_float(self):
        col = ArchiveDB.__table__.c["time_created"]
        assert isinstance(col.type, Float)
        assert col.nullable

    def test_time_updated_is_float(self):
        col = ArchiveDB.__table__.c["time_updated"]
        assert isinstance(col.type, Float)
        assert col.nullable

    def test_nullable_string_columns(self):
        nullable_cols = [
            "registry_url", "image_url", "registry_user", "registry_password",
            "status", "log", "namespace", "kong_token",
        ]
        for name in nullable_cols:
            col = ArchiveDB.__table__.c[name]
            assert col.nullable, f"{name} should be nullable"
            assert isinstance(col.type, String), f"{name} should be String"


class TestSharedSchema:
    def test_analysis_and_archive_have_same_columns(self):
        analysis_cols = {c.name for c in AnalysisDB.__table__.columns}
        archive_cols = {c.name for c in ArchiveDB.__table__.columns}
        assert analysis_cols == archive_cols

    def test_analysis_and_archive_have_different_table_names(self):
        assert AnalysisDB.__tablename__ != ArchiveDB.__tablename__

    def test_both_inherit_from_base(self):
        from src.resources.database.db_models import Base

        assert issubclass(AnalysisDB, Base)
        assert issubclass(ArchiveDB, Base)