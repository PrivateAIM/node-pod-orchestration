import os


def create_image_address(analysis_id: str) -> str:
    return f"{_add_slash(os.getenv('HARBOR_URL'))}"\
           f"{_add_slash(os.getenv('NODE_NAME'))}"\
           f"{analysis_id}:latest"


def _add_slash(string: str) -> str:
    return string + ('' if string.endswith('/') else '/')
