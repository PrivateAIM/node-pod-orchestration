"""Tests for src/main.py — entry point thread startup."""

from unittest.mock import MagicMock, patch, call


class TestMain:
    def test_main_starts_api_thread_and_status_loop(self):
        """main() starts an API thread and calls status_loop in the main thread."""
        mock_db = MagicMock()
        mock_thread = MagicMock()

        with (
            patch("src.main.load_dotenv"),
            patch("src.main.find_dotenv", return_value=".env"),
            patch("src.main.load_cluster_config"),
            patch("src.main.Database", return_value=mock_db),
            patch("src.main.get_current_namespace", return_value="default"),
            patch("src.main.Thread", return_value=mock_thread) as mock_thread_cls,
            patch("src.main.status_loop") as mock_status_loop,
        ):
            from src.main import main
            main()

        # Thread was created targeting start_po_api with correct kwargs
        mock_thread_cls.assert_called_once()
        call_kwargs = mock_thread_cls.call_args
        assert call_kwargs.kwargs["kwargs"] == {"database": mock_db, "namespace": "default"}

        # Thread was started
        mock_thread.start.assert_called_once()

        # status_loop was called with the database and default interval
        mock_status_loop.assert_called_once_with(mock_db, 10)

    def test_main_uses_custom_status_loop_interval(self, monkeypatch):
        """When STATUS_LOOP_INTERVAL is set, main() uses that value."""
        monkeypatch.setenv("STATUS_LOOP_INTERVAL", "30")

        mock_db = MagicMock()
        mock_thread = MagicMock()

        with (
            patch("src.main.load_dotenv"),
            patch("src.main.find_dotenv", return_value=".env"),
            patch("src.main.load_cluster_config"),
            patch("src.main.Database", return_value=mock_db),
            patch("src.main.get_current_namespace", return_value="default"),
            patch("src.main.Thread", return_value=mock_thread),
            patch("src.main.status_loop") as mock_status_loop,
        ):
            from src.main import main
            main()

        mock_status_loop.assert_called_once_with(mock_db, 30)

    def test_main_sets_default_status_loop_interval_when_missing(self, monkeypatch):
        """When STATUS_LOOP_INTERVAL is not set, main() defaults to 10."""
        monkeypatch.delenv("STATUS_LOOP_INTERVAL", raising=False)

        mock_db = MagicMock()
        mock_thread = MagicMock()

        with (
            patch("src.main.load_dotenv"),
            patch("src.main.find_dotenv", return_value=".env"),
            patch("src.main.load_cluster_config"),
            patch("src.main.Database", return_value=mock_db),
            patch("src.main.get_current_namespace", return_value="default"),
            patch("src.main.Thread", return_value=mock_thread),
            patch("src.main.status_loop") as mock_status_loop,
        ):
            from src.main import main
            main()

        mock_status_loop.assert_called_once_with(mock_db, 10)

    def test_start_po_api_instantiates_pod_orchestration_api(self):
        """start_po_api creates a PodOrchestrationAPI with the given args."""
        mock_db = MagicMock()

        with patch("src.main.PodOrchestrationAPI") as mock_api_cls:
            from src.main import start_po_api
            start_po_api(database=mock_db, namespace="test-ns")

        mock_api_cls.assert_called_once_with(mock_db, "test-ns")