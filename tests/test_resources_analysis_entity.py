"""Tests for src/resources/analysis/entity.py"""

import json
import pytest
from unittest.mock import MagicMock, patch

from src.resources.analysis.entity import Analysis, CreateAnalysis, read_db_analysis
from src.status.constants import AnalysisStatus


# ─── Analysis model ───────────────────────────────────────────────────────────

class TestAnalysisModel:
    def test_required_fields(self):
        a = Analysis(
            analysis_id="a1",
            project_id="p1",
            registry_url="harbor.test",
            image_url="harbor.test/img",
            registry_user="user",
            registry_password="pw",
            kong_token="tok",
        )
        assert a.analysis_id == "a1"
        assert a.project_id == "p1"
        assert a.registry_url == "harbor.test"
        assert a.image_url == "harbor.test/img"
        assert a.registry_user == "user"
        assert a.registry_password == "pw"
        assert a.kong_token == "tok"

    def test_default_values(self):
        a = Analysis(
            analysis_id="a1",
            project_id="p1",
            registry_url="harbor.test",
            image_url="harbor.test/img",
            registry_user="user",
            registry_password="pw",
            kong_token="tok",
        )
        assert a.namespace == "default"
        assert a.restart_counter == 0
        assert a.progress == 0
        assert a.deployment_name == ""
        assert a.tokens is None
        assert a.analysis_config is None
        assert a.status == AnalysisStatus.STARTING.value
        assert a.log is None
        assert a.pod_ids is None

    def test_status_defaults_to_starting(self):
        a = Analysis(
            analysis_id="a1",
            project_id="p1",
            registry_url="harbor.test",
            image_url="harbor.test/img",
            registry_user="user",
            registry_password="pw",
            kong_token="tok",
        )
        assert a.status == "starting"


# ─── Analysis.start() ─────────────────────────────────────────────────────────

class TestAnalysisStart:
    @pytest.fixture
    def analysis(self):
        return Analysis(
            analysis_id="test-analysis",
            project_id="test-project",
            registry_url="harbor.test",
            image_url="harbor.test/test-project/test-analysis",
            registry_user="robot_user",
            registry_password="secret",
            kong_token="kong-tok",
        )

    def test_start_sets_status_to_started(self, analysis, mock_database):
        mock_tokens = {"RESULT_TOKEN": "result-tok", "ANALYSIS_TOKEN": "analysis-tok"}
        with (
            patch("src.resources.analysis.entity.create_analysis_tokens", return_value=mock_tokens),
            patch("src.resources.analysis.entity.create_analysis_deployment", return_value=["pod-1"]),
        ):
            analysis.start(database=mock_database)
        assert analysis.status == AnalysisStatus.STARTED.value

    def test_start_sets_deployment_name(self, analysis, mock_database):
        mock_tokens = {"RESULT_TOKEN": "r", "ANALYSIS_TOKEN": "a"}
        with (
            patch("src.resources.analysis.entity.create_analysis_tokens", return_value=mock_tokens),
            patch("src.resources.analysis.entity.create_analysis_deployment", return_value=["pod-1"]),
        ):
            analysis.start(database=mock_database)
        assert analysis.deployment_name == "analysis-test-analysis-0"

    def test_start_deployment_name_uses_restart_counter(self, mock_database):
        analysis = Analysis(
            analysis_id="test-analysis",
            project_id="test-project",
            registry_url="harbor.test",
            image_url="harbor.test/img",
            registry_user="user",
            registry_password="pw",
            kong_token="tok",
            restart_counter=3,
        )
        mock_tokens = {"RESULT_TOKEN": "r", "ANALYSIS_TOKEN": "a"}
        with (
            patch("src.resources.analysis.entity.create_analysis_tokens", return_value=mock_tokens),
            patch("src.resources.analysis.entity.create_analysis_deployment", return_value=["pod-1"]),
        ):
            analysis.start(database=mock_database)
        assert analysis.deployment_name == "analysis-test-analysis-3"

    def test_start_sets_analysis_config_with_ids(self, analysis, mock_database):
        mock_tokens = {"RESULT_TOKEN": "result-tok", "ANALYSIS_TOKEN": "analysis-tok"}
        with (
            patch("src.resources.analysis.entity.create_analysis_tokens", return_value=mock_tokens),
            patch("src.resources.analysis.entity.create_analysis_deployment", return_value=["pod-1"]),
        ):
            analysis.start(database=mock_database)
        assert analysis.analysis_config["ANALYSIS_ID"] == "test-analysis"
        assert analysis.analysis_config["PROJECT_ID"] == "test-project"
        assert analysis.analysis_config["DEPLOYMENT_NAME"] == "analysis-test-analysis-0"

    def test_start_stores_pod_ids(self, analysis, mock_database):
        mock_tokens = {"RESULT_TOKEN": "r", "ANALYSIS_TOKEN": "a"}
        with (
            patch("src.resources.analysis.entity.create_analysis_tokens", return_value=mock_tokens),
            patch(
                "src.resources.analysis.entity.create_analysis_deployment",
                return_value=["pod-1", "pod-2"],
            ),
        ):
            analysis.start(database=mock_database)
        assert analysis.pod_ids == ["pod-1", "pod-2"]

    def test_start_calls_database_create_analysis(self, analysis, mock_database):
        mock_tokens = {"RESULT_TOKEN": "r", "ANALYSIS_TOKEN": "a"}
        with (
            patch("src.resources.analysis.entity.create_analysis_tokens", return_value=mock_tokens),
            patch("src.resources.analysis.entity.create_analysis_deployment", return_value=["pod-1"]),
        ):
            analysis.start(database=mock_database)
        mock_database.create_analysis.assert_called_once()
        call_kwargs = mock_database.create_analysis.call_args.kwargs
        assert call_kwargs["analysis_id"] == "test-analysis"
        assert call_kwargs["status"] == AnalysisStatus.STARTED.value

    def test_start_uses_provided_namespace(self, analysis, mock_database):
        mock_tokens = {"RESULT_TOKEN": "r", "ANALYSIS_TOKEN": "a"}
        with (
            patch("src.resources.analysis.entity.create_analysis_tokens", return_value=mock_tokens),
            patch("src.resources.analysis.entity.create_analysis_deployment", return_value=["pod-1"]),
        ):
            analysis.start(database=mock_database, namespace="flame-ns")
        assert analysis.namespace == "flame-ns"
        call_kwargs = mock_database.create_analysis.call_args.kwargs
        assert call_kwargs["namespace"] == "flame-ns"


# ─── Analysis.stop() ──────────────────────────────────────────────────────────

class TestAnalysisStop:
    @pytest.fixture
    def started_analysis(self):
        return Analysis(
            analysis_id="test-analysis",
            project_id="test-project",
            registry_url="harbor.test",
            image_url="harbor.test/img",
            registry_user="user",
            registry_password="pw",
            kong_token="tok",
            deployment_name="analysis-test-analysis-0",
            status=AnalysisStatus.STARTED.value,
            pod_ids=["pod-1"],
        )

    def test_stop_sets_status_to_stopped(self, started_analysis, mock_database):
        with patch("src.resources.analysis.entity.delete_deployment"):
            started_analysis.stop(database=mock_database)
        assert started_analysis.status == AnalysisStatus.STOPPED.value

    def test_stop_with_custom_status(self, started_analysis, mock_database):
        with patch("src.resources.analysis.entity.delete_deployment"):
            started_analysis.stop(database=mock_database, status=AnalysisStatus.FAILED.value)
        assert started_analysis.status == AnalysisStatus.FAILED.value

    def test_stop_sets_log_when_provided(self, started_analysis, mock_database):
        with patch("src.resources.analysis.entity.delete_deployment"):
            started_analysis.stop(database=mock_database, log="something went wrong")
        assert started_analysis.log == "something went wrong"

    def test_stop_preserves_existing_log_when_none_provided(self, started_analysis, mock_database):
        started_analysis.log = "original log"
        with patch("src.resources.analysis.entity.delete_deployment"):
            started_analysis.stop(database=mock_database)
        assert started_analysis.log == "original log"

    def test_stop_calls_delete_deployment(self, started_analysis, mock_database):
        with patch("src.resources.analysis.entity.delete_deployment") as mock_del:
            started_analysis.stop(database=mock_database)
        mock_del.assert_called_once_with("analysis-test-analysis-0", namespace="default")

    def test_stop_updates_database_deployment_status(self, started_analysis, mock_database):
        with patch("src.resources.analysis.entity.delete_deployment"):
            started_analysis.stop(database=mock_database)
        calls = mock_database.update_deployment.call_args_list
        assert any(
            c.args == ("analysis-test-analysis-0",) and c.kwargs.get("status") == AnalysisStatus.STOPPED.value
            for c in calls
        )

    def test_stop_updates_database_deployment_log(self, started_analysis, mock_database):
        with patch("src.resources.analysis.entity.delete_deployment"):
            started_analysis.stop(database=mock_database, log="bye")
        calls = mock_database.update_deployment.call_args_list
        assert any(
            c.args == ("analysis-test-analysis-0",) and c.kwargs.get("log") == "bye"
            for c in calls
        )


# ─── read_db_analysis() ───────────────────────────────────────────────────────

class TestReadDbAnalysis:
    def test_returns_analysis_instance(self, sample_analysis_db):
        db_row = sample_analysis_db()
        result = read_db_analysis(db_row)
        assert isinstance(result, Analysis)

    def test_maps_all_fields(self, sample_analysis_db):
        db_row = sample_analysis_db(
            analysis_id="a99",
            project_id="p99",
            registry_url="harbor.custom",
            image_url="harbor.custom/img",
            registry_user="ruser",
            registry_password="rpw",
            status="executing",
            pod_ids=json.dumps(["pod-a", "pod-b"]),
            log="some log",
            namespace="flame-ns",
            kong_token="kong123",
            restart_counter=2,
            progress=50,
            deployment_name="analysis-a99-2",
        )
        result = read_db_analysis(db_row)
        assert result.analysis_id == "a99"
        assert result.project_id == "p99"
        assert result.registry_url == "harbor.custom"
        assert result.image_url == "harbor.custom/img"
        assert result.registry_user == "ruser"
        assert result.registry_password == "rpw"
        assert result.status == "executing"
        assert result.pod_ids == ["pod-a", "pod-b"]
        assert result.log == "some log"
        assert result.namespace == "flame-ns"
        assert result.kong_token == "kong123"
        assert result.restart_counter == 2
        assert result.progress == 50
        assert result.deployment_name == "analysis-a99-2"

    def test_deserializes_pod_ids_from_json(self, sample_analysis_db):
        db_row = sample_analysis_db(pod_ids=json.dumps(["pod-1", "pod-2", "pod-3"]))
        result = read_db_analysis(db_row)
        assert result.pod_ids == ["pod-1", "pod-2", "pod-3"]

    def test_null_log_preserved(self, sample_analysis_db):
        db_row = sample_analysis_db(log=None)
        result = read_db_analysis(db_row)
        assert result.log is None


# ─── CreateAnalysis ───────────────────────────────────────────────────────────

class TestCreateAnalysis:
    def test_default_values(self):
        ca = CreateAnalysis()
        assert ca.analysis_id == "analysis_id"
        assert ca.project_id == "project_id"
        assert ca.registry_url == "harbor.privateaim"
        assert ca.image_url == "harbor.privateaim/node_id/analysis_id"
        assert ca.registry_user == "robot_user"
        assert ca.registry_password == "default_pw"
        assert ca.kong_token == "default_kong_token"
        assert ca.restart_counter == 0
        assert ca.progress == 0

    def test_custom_values(self):
        ca = CreateAnalysis(
            analysis_id="custom-id",
            project_id="custom-proj",
            registry_url="harbor.custom",
            image_url="harbor.custom/img",
            registry_user="cuser",
            registry_password="cpw",
            kong_token="ctok",
            restart_counter=5,
            progress=42,
        )
        assert ca.analysis_id == "custom-id"
        assert ca.project_id == "custom-proj"
        assert ca.restart_counter == 5
        assert ca.progress == 42

    def test_is_pydantic_model(self):
        from pydantic import BaseModel
        assert issubclass(CreateAnalysis, BaseModel)