from unittest.mock import MagicMock, patch

import pytest
from httpx2 import ConnectError, HTTPStatusError, ConnectTimeout


# ─── TestDeleteSubscription ───────────────────────────────────────────────────

class TestDeleteSubscription:
    def _make_mock_response(self, status_code=200):
        resp = MagicMock()
        resp.status_code = status_code
        resp.raise_for_status = MagicMock()
        if status_code >= 400:
            resp.raise_for_status.side_effect = HTTPStatusError(
                str(status_code), request=MagicMock(), response=resp
            )
        return resp

    def test_success_calls_delete(self):
        mock_response = self._make_mock_response(200)

        with (
            patch("src.utils.mb_client.find_k8s_resources", return_value=["mb-service"]),
            patch("src.utils.mb_client.Client") as mock_client_cls,
        ):
            mock_client_instance = MagicMock()
            mock_client_instance.delete.return_value = mock_response
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client_instance)
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_client_cls.return_value = mock_client_instance

            from src.utils.mb_client import delete_subscription
            delete_subscription("analysis-1", "token-123")

        mock_client_instance.delete.assert_called_once_with("/analyses/analysis-1/messages/subscriptions")

    def test_http_status_error_does_not_raise(self):
        with (
            patch("src.utils.mb_client.find_k8s_resources", return_value=["mb-service"]),
            patch("src.utils.mb_client.Client") as mock_client_cls,
        ):
            mock_client_instance = MagicMock()
            mock_client_instance.delete.side_effect = HTTPStatusError(
                "404", request=MagicMock(), response=MagicMock()
            )
            mock_client_cls.return_value = mock_client_instance

            from src.utils.mb_client import delete_subscription
            delete_subscription("analysis-1", "token-123")

    def test_connect_error_does_not_raise(self):
        with (
            patch("src.utils.mb_client.find_k8s_resources", return_value=["mb-service"]),
            patch("src.utils.mb_client.Client") as mock_client_cls,
        ):
            mock_client_instance = MagicMock()
            mock_client_instance.delete.side_effect = ConnectError("refused")
            mock_client_cls.return_value = mock_client_instance

            from src.utils.mb_client import delete_subscription
            delete_subscription("analysis-1", "token-123")

    def test_connect_timeout_does_not_raise(self):
        with (
            patch("src.utils.mb_client.find_k8s_resources", return_value=["mb-service"]),
            patch("src.utils.mb_client.Client") as mock_client_cls,
        ):
            mock_client_instance = MagicMock()
            mock_client_instance.delete.side_effect = ConnectTimeout("timeout")
            mock_client_cls.return_value = mock_client_instance

            from src.utils.mb_client import delete_subscription
            delete_subscription("analysis-1", "token-123")

    def test_raise_for_status_on_error_response_logs_warning(self):
        mock_response = self._make_mock_response(500)

        with (
            patch("src.utils.mb_client.find_k8s_resources", return_value=["mb-service"]),
            patch("src.utils.mb_client.Client") as mock_client_cls,
            patch("src.utils.mb_client.logger") as mock_logger,
        ):
            mock_client_instance = MagicMock()
            mock_client_instance.delete.return_value = mock_response
            mock_client_cls.return_value = mock_client_instance

            from src.utils.mb_client import delete_subscription
            delete_subscription("analysis-1", "token-123")

        mock_logger.warning.assert_called_once()
        warning_msg = mock_logger.warning.call_args[0][0]
        assert "analysis-1" in warning_msg
