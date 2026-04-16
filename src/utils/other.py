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
    return (os.getenv('HUB_CLIENT_ID'),
            os.getenv('HUB_CLIENT_SECRET'),
            os.getenv('HUB_URL_CORE'),
            os.getenv('HUB_URL_AUTH'),
            os.getenv('HUB_LOGGING') in ['True', 'true', '1', 't'],
            os.getenv('PO_HTTP_PROXY'),
            os.getenv('PO_HTTPS_PROXY'))


def resource_name_to_analysis(deployment_name: str, max_r_split: int = 1) -> str:
    return deployment_name.split("analysis-")[-1].rsplit('-', max_r_split)[0]


def is_uuid(test_str: Union[str, uuid.UUID], version: int = 4):
    try:
        uuid.UUID(str(test_str), version=version)
        return len(rreplace(str(test_str), '-', '', 4)) == 32
    except ValueError:
        return False


def rreplace(string: str, replaced_str: str, replacement_str: str, count: int):
    """
    Reverse replace in string for given count number of times

    Parameters
    ----------
    string : str
    replaced_str: str
    replacement_str: str
    count : int

    Returns
    -------
    string : str
    """
    return str(replacement_str).join(str(string).rsplit(str(replaced_str), int(count)))
