from typing import Optional, Union
import os
import uuid


def extract_hub_envs() -> tuple[Optional[str],
                                Optional[str],
                                Optional[str],
                                Optional[str],
                                bool,
                                Optional[str],
                                Optional[str]]:
    """Read the FLAME-Hub related environment variables into a tuple.

    Returns:
        Tuple ``(client_id, client_secret, hub_url_core, hub_url_auth,
        hub_logging_enabled, http_proxy, https_proxy)``.
    """
    return (os.getenv('HUB_CLIENT_ID'),
            os.getenv('HUB_CLIENT_SECRET'),
            os.getenv('HUB_URL_CORE'),
            os.getenv('HUB_URL_AUTH'),
            os.getenv('HUB_LOGGING') in ['True', 'true', '1', 't'],
            os.getenv('PO_HTTP_PROXY'),
            os.getenv('PO_HTTPS_PROXY'))


def resource_name_to_analysis(deployment_name: str, max_r_split: int = 1) -> str:
    """Extract the analysis id from a FLAME analysis resource name.

    Resource names follow the ``analysis-{analysis_id}-{restart_counter}``
    pattern (with an optional ``nginx-`` prefix and pod hash suffix); this
    helper strips those and returns the analysis id.

    Args:
        deployment_name: Kubernetes resource name.
        max_r_split: Number of trailing ``-``-separated segments to drop.

    Returns:
        The analysis id portion of the name.
    """
    return deployment_name.split("analysis-")[-1].rsplit('-', max_r_split)[0]


def is_uuid(test_str: Union[str, uuid.UUID], version: int = 4):
    """Return True if ``test_str`` parses as a UUID of the given version.

    Args:
        test_str: String or UUID to validate.
        version: UUID version to require (defaults to 4).

    Returns:
        ``True`` if ``test_str`` is a syntactically valid UUID; otherwise
        ``False``.
    """
    try:
        uuid.UUID(str(test_str), version=version)
        return len(rreplace(str(test_str), '-', '', 4)) == 32
    except ValueError:
        return False


def rreplace(string: str, replaced_str: str, replacement_str: str, count: int):
    """Replace up to ``count`` occurrences of ``replaced_str`` starting from the right.

    Args:
        string: The input string.
        replaced_str: Substring to replace.
        replacement_str: Substring to insert in its place.
        count: Maximum number of rightmost occurrences to replace.

    Returns:
        The resulting string.
    """
    return str(replacement_str).join(str(string).rsplit(str(replaced_str), int(count)))
