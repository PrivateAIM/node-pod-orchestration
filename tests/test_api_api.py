"""Tests for src/api/api.py — all 16 endpoints via TestClient.

Uses the api_test_client fixture from conftest.py, which:
  - patches uvicorn.run to capture the FastAPI app
  - overrides valid_access_token to skip JWT validation
  - patches hub client init to avoid real network calls
"""

from unittest.mock import MagicMock, patch

import pytest

from src.status.constants import AnalysisStatus


# ─── TestHealthEndpoint ───────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_healthz_returns_ok(self, api_test_client):
        response = api_test_client.get("/po/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_healthz_no_auth_required(self, api_test_client):
        """healthz route has no auth dependency — it works even without a token."""
        import anyio
        import httpx

        app = api_test_client.app
        overrides_backup = dict(app.dependency_overrides)
        app.dependency_overrides.clear()

        async def _get():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                return await client.get("/po/healthz")

        response = anyio.run(_get)
        assert response.status_code == 200

        app.dependency_overrides.update(overrides_backup)


# ─── TestUnauthenticated ──────────────────────────────────────────────────────

class TestUnauthenticated:
    def test_unauthenticated_create_returns_4xx(self, api_test_client):
        """Without override, OAuth dependency raises 401/403."""
        import anyio
        import httpx

        app = api_test_client.app
        overrides_backup = dict(app.dependency_overrides)
        app.dependency_overrides.clear()

        async def _post():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://testserver",
                follow_redirects=True,
            ) as client:
                return await client.post("/po/", json={})

        response = anyio.run(_post)
        assert response.status_code in (401, 403, 422)

        app.dependency_overrides.update(overrides_backup)


# ─── TestCreateAnalysis ───────────────────────────────────────────────────────

class TestCreateAnalysis:
    def test_create_returns_starting_status(self, api_test_client):
        with patch("src.api.api.create_analysis", return_value={"analysis_id": AnalysisStatus.STARTING.value}) as mock_create:
            response = api_test_client.post("/po/", json={
                "analysis_id": "analysis_id",
                "project_id": "project_id",
                "registry_url": "harbor.test",
                "image_url": "harbor.test/img",
                "registry_user": "user",
                "registry_password": "pw",
                "kong_token": "token",
            })

        assert response.status_code == 200
        data = response.json()
        assert "analysis_id" in data
        assert data["analysis_id"] == AnalysisStatus.STARTING.value


# ─── TestHistoryEndpoints ─────────────────────────────────────────────────────

class TestHistoryEndpoints:
    def test_retrieve_all_history(self, api_test_client):
        fake_result = {"analysis": {"analysis_id": []}, "nginx": {"analysis_id": []}}
        with patch("src.api.api.retrieve_history", return_value=fake_result) as mock_fn:
            response = api_test_client.get("/po/history")
        assert response.status_code == 200
        mock_fn.assert_called_once_with("all", mock_fn.call_args[0][1])

    def test_retrieve_all_history_500_on_exception(self, api_test_client):
        with patch("src.api.api.retrieve_history", side_effect=RuntimeError("db error")):
            response = api_test_client.get("/po/history")
        assert response.status_code == 500

    def test_retrieve_history_by_id(self, api_test_client):
        fake_result = {"analysis": {"analysis_id": []}, "nginx": {"analysis_id": []}}
        with patch("src.api.api.retrieve_history", return_value=fake_result) as mock_fn:
            response = api_test_client.get("/po/history/analysis_id")
        assert response.status_code == 200
        mock_fn.assert_called_once_with("analysis_id", mock_fn.call_args[0][1])

    def test_retrieve_history_by_id_500_on_exception(self, api_test_client):
        with patch("src.api.api.retrieve_history", side_effect=RuntimeError("db error")):
            response = api_test_client.get("/po/history/analysis_id")
        assert response.status_code == 500


# ─── TestLogsEndpoints ────────────────────────────────────────────────────────

class TestLogsEndpoints:
    def test_retrieve_all_logs(self, api_test_client):
        fake_result = {"analysis_id": {"analysis": [], "nginx": []}}
        with patch("src.api.api.retrieve_logs", return_value=fake_result) as mock_fn:
            response = api_test_client.get("/po/logs")
        assert response.status_code == 200
        mock_fn.assert_called_once_with("all", mock_fn.call_args[0][1])

    def test_retrieve_all_logs_500_on_exception(self, api_test_client):
        with patch("src.api.api.retrieve_logs", side_effect=RuntimeError("err")):
            response = api_test_client.get("/po/logs")
        assert response.status_code == 500

    def test_retrieve_logs_by_id(self, api_test_client):
        fake_result = {"analysis_id": {"analysis": [], "nginx": []}}
        with patch("src.api.api.retrieve_logs", return_value=fake_result) as mock_fn:
            response = api_test_client.get("/po/logs/analysis_id")
        assert response.status_code == 200
        mock_fn.assert_called_once_with("analysis_id", mock_fn.call_args[0][1])

    def test_retrieve_logs_by_id_500_on_exception(self, api_test_client):
        with patch("src.api.api.retrieve_logs", side_effect=RuntimeError("err")):
            response = api_test_client.get("/po/logs/analysis_id")
        assert response.status_code == 500


# ─── TestStatusEndpoints ──────────────────────────────────────────────────────

class TestStatusEndpoints:
    def test_get_all_status(self, api_test_client):
        fake_result = {"analysis_id": {"status": "started", "progress": 0}}
        with patch("src.api.api.get_status_and_progress", return_value=fake_result) as mock_fn:
            response = api_test_client.get("/po/status")
        assert response.status_code == 200
        mock_fn.assert_called_once_with("all", mock_fn.call_args[0][1])

    def test_get_all_status_500_on_exception(self, api_test_client):
        with patch("src.api.api.get_status_and_progress", side_effect=RuntimeError("err")):
            response = api_test_client.get("/po/status")
        assert response.status_code == 500

    def test_get_status_by_id(self, api_test_client):
        fake_result = {"analysis_id": {"status": "started", "progress": 0}}
        with patch("src.api.api.get_status_and_progress", return_value=fake_result) as mock_fn:
            response = api_test_client.get("/po/status/analysis_id")
        assert response.status_code == 200
        mock_fn.assert_called_once_with("analysis_id", mock_fn.call_args[0][1])

    def test_get_status_by_id_500_on_exception(self, api_test_client):
        with patch("src.api.api.get_status_and_progress", side_effect=RuntimeError("err")):
            response = api_test_client.get("/po/status/analysis_id")
        assert response.status_code == 500


# ─── TestPodsEndpoints ────────────────────────────────────────────────────────

class TestPodsEndpoints:
    def test_get_all_pods(self, api_test_client):
        fake_result = {"analysis_id": ["pod-1"]}
        with patch("src.api.api.get_pods", return_value=fake_result) as mock_fn:
            response = api_test_client.get("/po/pods")
        assert response.status_code == 200
        mock_fn.assert_called_once_with("all", mock_fn.call_args[0][1])

    def test_get_all_pods_500_on_exception(self, api_test_client):
        with patch("src.api.api.get_pods", side_effect=RuntimeError("err")):
            response = api_test_client.get("/po/pods")
        assert response.status_code == 500

    def test_get_pods_by_id(self, api_test_client):
        fake_result = {"analysis_id": ["pod-1"]}
        with patch("src.api.api.get_pods", return_value=fake_result) as mock_fn:
            response = api_test_client.get("/po/pods/analysis_id")
        assert response.status_code == 200
        mock_fn.assert_called_once_with("analysis_id", mock_fn.call_args[0][1])

    def test_get_pods_by_id_500_on_exception(self, api_test_client):
        with patch("src.api.api.get_pods", side_effect=RuntimeError("err")):
            response = api_test_client.get("/po/pods/analysis_id")
        assert response.status_code == 500


# ─── TestStopEndpoints ────────────────────────────────────────────────────────

class TestStopEndpoints:
    def test_stop_all(self, api_test_client, mock_database):
        fake_stop_result = {"analysis_id": "stopped"}
        with (
            patch("src.api.api.stop_analysis", return_value=fake_stop_result) as mock_stop,
            patch("src.api.api.stream_logs") as mock_stream,
        ):
            response = api_test_client.put("/po/stop")
        assert response.status_code == 200
        mock_stop.assert_called_once_with("all", mock_database)
        # stream_logs called once per analysis_id returned by get_analysis_ids
        assert mock_stream.call_count == len(mock_database.get_analysis_ids())

    def test_stop_all_500_on_exception(self, api_test_client):
        with patch("src.api.api.stop_analysis", side_effect=RuntimeError("err")):
            response = api_test_client.put("/po/stop")
        assert response.status_code == 500

    def test_stop_by_id(self, api_test_client, mock_database):
        fake_stop_result = {"analysis_id": "stopped"}
        with (
            patch("src.api.api.stop_analysis", return_value=fake_stop_result) as mock_stop,
            patch("src.api.api.stream_logs") as mock_stream,
        ):
            response = api_test_client.put("/po/stop/analysis_id")
        assert response.status_code == 200
        mock_stop.assert_called_once_with("analysis_id", mock_database)
        mock_stream.assert_called_once()

    def test_stop_by_id_500_on_exception(self, api_test_client):
        with patch("src.api.api.stop_analysis", side_effect=RuntimeError("err")):
            response = api_test_client.put("/po/stop/analysis_id")
        assert response.status_code == 500


# ─── TestDeleteEndpoints ──────────────────────────────────────────────────────

class TestDeleteEndpoints:
    def test_delete_all(self, api_test_client, mock_database):
        fake_result = {"analysis_id": "stopped"}
        with patch("src.api.api.delete_analysis", return_value=fake_result) as mock_fn:
            response = api_test_client.delete("/po/delete")
        assert response.status_code == 200
        mock_fn.assert_called_once_with("all", mock_database)

    def test_delete_all_500_on_exception(self, api_test_client):
        with patch("src.api.api.delete_analysis", side_effect=RuntimeError("err")):
            response = api_test_client.delete("/po/delete")
        assert response.status_code == 500

    def test_delete_by_id(self, api_test_client, mock_database):
        fake_result = {"analysis_id": "stopped"}
        with patch("src.api.api.delete_analysis", return_value=fake_result) as mock_fn:
            response = api_test_client.delete("/po/delete/analysis_id")
        assert response.status_code == 200
        mock_fn.assert_called_once_with("analysis_id", mock_database)

    def test_delete_by_id_500_on_exception(self, api_test_client):
        with patch("src.api.api.delete_analysis", side_effect=RuntimeError("err")):
            response = api_test_client.delete("/po/delete/analysis_id")
        assert response.status_code == 500


# ─── TestCleanupEndpoint ──────────────────────────────────────────────────────

class TestCleanupEndpoint:
    def test_cleanup(self, api_test_client, mock_database):
        fake_result = {"analyzes": "Deleted 1 analysis deployments"}
        with patch("src.api.api.cleanup", return_value=fake_result) as mock_fn:
            response = api_test_client.delete("/po/cleanup/analyzes")
        assert response.status_code == 200
        mock_fn.assert_called_once_with("analyzes", mock_database, "default")

    def test_cleanup_500_on_exception(self, api_test_client):
        with patch("src.api.api.cleanup", side_effect=RuntimeError("err")):
            response = api_test_client.delete("/po/cleanup/analyzes")
        assert response.status_code == 500


# ─── TestStreamLogsEndpoint ───────────────────────────────────────────────────

class TestStreamLogsEndpoint:
    def test_stream_logs(self, api_test_client):
        fake_result = {"status": "ok"}
        with patch("src.api.api.stream_logs", return_value=fake_result) as mock_fn:
            response = api_test_client.post("/po/stream_logs", json={
                "analysis_id": "analysis_id",
                "log": "some log line",
                "log_type": "info",
                "status": "executing",
                "progress": 50,
            })
        assert response.status_code == 200
        mock_fn.assert_called_once()

    def test_stream_logs_500_on_exception(self, api_test_client):
        with patch("src.api.api.stream_logs", side_effect=RuntimeError("err")):
            response = api_test_client.post("/po/stream_logs", json={
                "analysis_id": "analysis_id",
                "log": "log",
                "log_type": "info",
                "status": "executing",
                "progress": 0,
            })
        assert response.status_code == 500