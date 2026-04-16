import pytest
from unittest.mock import patch, MagicMock, AsyncMock


class TestExtractHubEnvs:
    def test_all_set(self, monkeypatch):
        monkeypatch.setenv("HUB_CLIENT_ID", "client-id")
        monkeypatch.setenv("HUB_CLIENT_SECRET", "secret")
        monkeypatch.setenv("HUB_URL_CORE", "http://hub-core")
        monkeypatch.setenv("HUB_URL_AUTH", "http://hub-auth")
        monkeypatch.setenv("HUB_LOGGING", "true")
        monkeypatch.setenv("PO_HTTP_PROXY", "http://proxy")
        monkeypatch.setenv("PO_HTTPS_PROXY", "https://proxy")

        from src.utils.other import extract_hub_envs
        result = extract_hub_envs()

        assert result == (
            "client-id",
            "secret",
            "http://hub-core",
            "http://hub-auth",
            True,
            "http://proxy",
            "https://proxy",
        )

    def test_missing_optional(self, monkeypatch):
        monkeypatch.setenv("HUB_CLIENT_ID", "client-id")
        monkeypatch.setenv("HUB_CLIENT_SECRET", "secret")
        monkeypatch.setenv("HUB_URL_CORE", "http://hub-core")
        monkeypatch.setenv("HUB_URL_AUTH", "http://hub-auth")
        monkeypatch.delenv("HUB_LOGGING", raising=False)
        monkeypatch.delenv("PO_HTTP_PROXY", raising=False)
        monkeypatch.delenv("PO_HTTPS_PROXY", raising=False)

        from src.utils.other import extract_hub_envs
        result = extract_hub_envs()

        assert result[4] is False  # HUB_LOGGING defaults to False
        assert result[5] is None   # PO_HTTP_PROXY
        assert result[6] is None   # PO_HTTPS_PROXY

    def test_missing_required(self, monkeypatch):
        monkeypatch.delenv("HUB_CLIENT_ID", raising=False)
        monkeypatch.delenv("HUB_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("HUB_URL_CORE", raising=False)
        monkeypatch.delenv("HUB_URL_AUTH", raising=False)
        monkeypatch.delenv("HUB_LOGGING", raising=False)
        monkeypatch.delenv("PO_HTTP_PROXY", raising=False)
        monkeypatch.delenv("PO_HTTPS_PROXY", raising=False)

        from src.utils.other import extract_hub_envs
        result = extract_hub_envs()

        assert result[0] is None
        assert result[1] is None
        assert result[2] is None
        assert result[3] is None

    @pytest.mark.parametrize("value,expected", [
        ("True", True),
        ("true", True),
        ("1", True),
        ("t", True),
        ("False", False),
        ("false", False),
        ("0", False),
        ("yes", False),
        ("", False),
    ])
    def test_hub_logging_variants(self, monkeypatch, value, expected):
        monkeypatch.setenv("HUB_LOGGING", value)

        from src.utils.other import extract_hub_envs
        result = extract_hub_envs()

        assert result[4] is expected


class TestResourceNameToAnalysis:
    def test_single_split(self):
        from src.utils.other import resource_name_to_analysis
        # deployment_name = "analysis-{analysis_id}-{restart_counter}"
        result = resource_name_to_analysis("analysis-abc123-0")
        assert result == "abc123"

    def test_double_split(self):
        from src.utils.other import resource_name_to_analysis
        # analysis_id itself contains a hyphen
        result = resource_name_to_analysis("analysis-abc-123-0", max_r_split=1)
        assert result == "abc-123"

    def test_nginx_prefix(self):
        from src.utils.other import resource_name_to_analysis
        # nginx sidecar container name includes extra prefix before "analysis-"
        result = resource_name_to_analysis("nginx-analysis-abc123-0")
        assert result == "abc123"

    def test_max_r_split_two(self):
        from src.utils.other import resource_name_to_analysis
        # with max_r_split=2 strips two trailing segments
        result = resource_name_to_analysis("analysis-abc123-pod-0", max_r_split=2)
        assert result == "abc123"

    def test_no_restart_counter(self):
        from src.utils.other import resource_name_to_analysis
        # edge case: no trailing hyphen — rsplit finds nothing to strip, returns full segment
        result = resource_name_to_analysis("analysis-abc123")
        assert result == "abc123"
