"""
Shared test fixtures for node-pod-orchestration.

IMPORTANT: mock_env_vars is session-scoped and autouse. It sets all required
environment variables BEFORE any src modules are imported, which is critical
because oauth.py and token.py read env vars at module level.

All src imports are deferred (inside fixture bodies) to ensure env vars are set first.
"""

import json
import os
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

# ─── Test Environment Variables ──────────────────────────────────────────────

_TEST_ENV_VARS = {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_USER": "test_user",
    "POSTGRES_PASSWORD": "test_password",
    "POSTGRES_DB": "test_db",
    "KEYCLOAK_URL": "http://localhost:8080",
    "KEYCLOAK_REALM": "flame",
    "RESULT_CLIENT_ID": "test_result_client",
    "RESULT_CLIENT_SECRET": "test_result_secret",
    "HUB_CLIENT_ID": "test_hub_client",
    "HUB_CLIENT_SECRET": "test_hub_secret",
    "HUB_URL_CORE": "http://localhost:3000",
    "HUB_URL_AUTH": "http://localhost:3001",
    "HARBOR_URL": "http://harbor.test",
    "HARBOR_USER": "harbor_user",
    "HARBOR_PW": "harbor_password",
    "NODE_NAME": "test-node",
}


# ─── Fixture 1: mock_env_vars ───────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def mock_env_vars():
    """Set all required env vars for the entire test session.

    Uses os.environ directly because monkeypatch is function-scoped only.
    Must run before any src module import triggers oauth.py / token.py
    module-level env var reads.
    """
    original = {}
    for key, value in _TEST_ENV_VARS.items():
        original[key] = os.environ.get(key)
        os.environ[key] = value

    yield

    for key, orig_value in original.items():
        if orig_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = orig_value


# ─── Fixture 3: sample_analysis_db (defined before mock_database) ───────────

@pytest.fixture
def sample_analysis_db():
    """Factory fixture: returns a callable that creates AnalysisDB mocks.

    Usage:
        def test_something(sample_analysis_db):
            default = sample_analysis_db()
            custom = sample_analysis_db(status="failed", restart_counter=5)
    """
    from src.resources.database.db_models import AnalysisDB

    def _factory(**kwargs):
        defaults = {
            "id": 1,
            "deployment_name": "analysis-analysis_id-0",
            "analysis_id": "analysis_id",
            "project_id": "project_id",
            "registry_url": "harbor.privateaim",
            "image_url": "harbor.privateaim/node_id/analysis_id",
            "registry_user": "robot_user",
            "registry_password": "default_pw",
            "status": "started",
            "log": None,
            "pod_ids": json.dumps(["pod-1"]),
            "namespace": "default",
            "kong_token": "default_kong_token",
            "restart_counter": 0,
            "progress": 0,
            "time_created": 1700000000.0,
            "time_updated": None,
        }
        defaults.update(kwargs)
        mock = MagicMock(spec=AnalysisDB)
        for attr, value in defaults.items():
            setattr(mock, attr, value)
        return mock

    return _factory


# ─── Fixture 2: mock_database ───────────────────────────────────────────────

@pytest.fixture
def mock_database(sample_analysis_db):
    """MagicMock(spec=Database) with sensible default return values."""
    from src.resources.database.entity import Database

    mock_db = MagicMock(spec=Database)
    default_analysis = sample_analysis_db()

    mock_db.get_deployment.return_value = default_analysis
    mock_db.get_latest_deployment.return_value = default_analysis
    mock_db.get_deployments.return_value = [default_analysis]
    mock_db.create_analysis.return_value = default_analysis
    mock_db.update_analysis.return_value = [default_analysis]
    mock_db.update_deployment.return_value = default_analysis
    mock_db.get_analysis_ids.return_value = ["analysis_id"]
    mock_db.get_deployment_ids.return_value = ["analysis-analysis_id-0"]
    mock_db.get_deployment_pod_ids.return_value = ["pod-1"]
    mock_db.get_analysis_pod_ids.return_value = [["pod-1"]]
    mock_db.get_analysis_log.return_value = ""
    mock_db.get_analysis_progress.return_value = 0
    mock_db.analysis_is_running.return_value = True
    mock_db.progress_valid.return_value = True
    mock_db.extract_analysis_body.return_value = {
        "analysis_id": "analysis_id",
        "project_id": "project_id",
        "registry_url": "harbor.privateaim",
        "image_url": "harbor.privateaim/node_id/analysis_id",
        "registry_user": "robot_user",
        "registry_password": "default_pw",
        "namespace": "default",
        "kong_token": "default_kong_token",
        "restart_counter": 0,
        "progress": 0,
    }

    return mock_db


# ─── Fixture 4: sample_create_analysis ──────────────────────────────────────

@pytest.fixture
def sample_create_analysis():
    """CreateAnalysis Pydantic model with all test defaults."""
    from src.resources.analysis.entity import CreateAnalysis

    return CreateAnalysis()


# ─── Fixture 5: mock_hub_client ─────────────────────────────────────────────

@pytest.fixture
def mock_hub_client():
    """MagicMock for flame_hub.CoreClient with sensible defaults."""
    import flame_hub

    mock_client = MagicMock(spec=flame_hub.CoreClient)

    mock_node = MagicMock()
    mock_node.id = "test-node-id"
    mock_client.find_nodes.return_value = [mock_node]

    mock_analysis_node = MagicMock()
    mock_analysis_node.id = "test-node-analysis-id"
    mock_analysis_node.execution_status = "started"
    mock_analysis_node.node_id = "test-node-id"
    mock_client.find_analysis_nodes.return_value = [mock_analysis_node]

    mock_client.update_analysis_node.return_value = None

    return mock_client


# ─── Fixture 6: mock_k8s_clients ────────────────────────────────────────────

@dataclass
class K8sMocks:
    """Named container for mocked Kubernetes API clients."""

    core_v1: MagicMock
    apps_v1: MagicMock
    networking_v1: MagicMock
    batch_v1: MagicMock
    load_config: MagicMock


@pytest.fixture
def mock_k8s_clients():
    """Patch all 4 K8s API client classes and load_incluster_config.

    Usage:
        def test_something(mock_k8s_clients):
            mock_k8s_clients.core_v1.list_namespaced_pod.return_value = ...
    """
    mock_core = MagicMock()
    mock_apps = MagicMock()
    mock_net = MagicMock()
    mock_batch = MagicMock()

    with (
        patch("kubernetes.client.CoreV1Api", return_value=mock_core),
        patch("kubernetes.client.AppsV1Api", return_value=mock_apps),
        patch("kubernetes.client.NetworkingV1Api", return_value=mock_net),
        patch("kubernetes.client.BatchV1Api", return_value=mock_batch),
        patch("kubernetes.config.load_incluster_config") as mock_load,
    ):
        yield K8sMocks(
            core_v1=mock_core,
            apps_v1=mock_apps,
            networking_v1=mock_net,
            batch_v1=mock_batch,
            load_config=mock_load,
        )


# ─── Fixture 7: api_test_client ─────────────────────────────────────────────

@pytest.fixture
def api_test_client(mock_database, mock_hub_client, mock_k8s_clients):
    """Capture FastAPI app from PodOrchestrationAPI and return TestClient.

    Patches uvicorn.run to intercept the app argument (since
    PodOrchestrationAPI calls uvicorn.run at the end of __init__).
    Bypasses OAuth via FastAPI dependency_overrides.
    """
    from starlette.testclient import TestClient
    from src.api.oauth import valid_access_token

    captured_app = None

    def fake_uvicorn_run(app, **kwargs):
        nonlocal captured_app
        captured_app = app

    with (
        patch("src.api.api.uvicorn.run", side_effect=fake_uvicorn_run),
        patch(
            "src.api.api.extract_hub_envs",
            return_value=(
                "test_hub_client",
                "test_hub_secret",
                "http://localhost:3000",
                "http://localhost:3001",
                False,
                None,
                None,
            ),
        ),
        patch(
            "src.api.api.init_hub_client_with_client",
            return_value=mock_hub_client,
        ),
        patch(
            "src.api.api.get_node_id_by_client",
            return_value="test-node-id",
        ),
    ):
        from src.api.api import PodOrchestrationAPI

        PodOrchestrationAPI(database=mock_database, namespace="default")

    assert captured_app is not None, "Failed to capture FastAPI app from uvicorn.run"

    captured_app.dependency_overrides[valid_access_token] = lambda: {
        "sub": "test-user",
        "preferred_username": "tester",
    }

    # starlette 0.36.x / httpx 0.28.x incompatibility: starlette passes `app=` to
    # httpx.Client, but httpx 0.28 removed that parameter. ASGITransport is async-only.
    # Use a thin sync wrapper that drives AsyncClient via anyio.run().
    import anyio
    import httpx

    class SyncASGIClient:
        """Sync test client that drives httpx.AsyncClient with ASGITransport via anyio."""

        def __init__(self, asgi_app, base_url="http://testserver"):
            self.app = asgi_app
            self._base_url = base_url

        def _request(self, method: str, url: str, **kwargs):
            async def _do():
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=self.app),
                    base_url=self._base_url,
                ) as client:
                    return await getattr(client, method)(url, **kwargs)

            return anyio.run(_do)

        def get(self, url, **kw): return self._request("get", url, **kw)
        def post(self, url, **kw): return self._request("post", url, **kw)
        def put(self, url, **kw): return self._request("put", url, **kw)
        def delete(self, url, **kw): return self._request("delete", url, **kw)

    yield SyncASGIClient(captured_app)

    captured_app.dependency_overrides.clear()