import os
from typing import Literal, Dict
from minio import Minio
from minio.error import S3Error


_LOGS_BUCKET_NAME = 'logs'


def get_minio_client() -> Minio:
    """
    Establish a session to the MinIO instance using credentials from environment variables.

    Returns:
        Minio: An instance of the MinIO client.

    Raises:
        EnvironmentError: If the MinIO credentials are not set in the environment variables.
    """
    endpoint = os.getenv('MINIO_ENDPOINT')
    access_key = os.getenv('MINIO_ACCESS_KEY')
    secret_key = os.getenv('MINIO_SECRET_KEY')

    if not all([endpoint, access_key, secret_key]):
        raise EnvironmentError("MinIO credentials are not set in the environment variables.")

    client = Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=False  # Set to True if using HTTPS
    )

    # Check if bucket exists, create if not
    if not client.bucket_exists(_LOGS_BUCKET_NAME):
        client.make_bucket(_LOGS_BUCKET_NAME)

    return client


def folder_exists(client: Minio, bucket_name: str, folder_name: str) -> bool:
    """
    Check if a folder exists in a bucket.

    Args:
        client (Minio): The MinIO client.
        bucket_name (str): The name of the bucket.
        folder_name (str): The name of the folder to check.

    Returns:
        bool: True if the folder exists, False otherwise.
    """
    try:
        objects = client.list_objects(bucket_name, prefix=folder_name + "/", recursive=False)
        return any(obj.object_name == folder_name + "/" for obj in objects)
    except S3Error as e:
        print(f"Error checking folder existence: {e}")
        return False


def upload_log_file(client: Minio, bucket_name: str, folder_name: str, file_name: str, log_data: str) -> None:
    """
    Upload a log as a string as a file to a folder in a bucket.

    Args:
        client (Minio): The MinIO client.
        bucket_name (str): The name of the bucket.
        folder_name (str): The name of the folder.
        file_name (str): The name of the file to create.
        log_data (str): The log data to upload.
    """
    # Convert log_data to bytes
    data = log_data.encode('utf-8')
    data_length = len(data)
    object_name = f"{folder_name}/{file_name}"
    client.put_object(bucket_name, object_name, data=data, length=data_length)


def save_log_file(project_id: str,
                  analysis_id: str,
                  log_dict: Dict[Literal['analysis', 'nginx'], Dict[str, str]],
                  status: Literal['stopped', 'success', 'failed']) -> None:
    """
    External function to save log files.

    It checks if a bucket exists and creates it if not,
    checks if a folder exists for the analysis and creates it if not,
    and uploads the log file for every element in the dict to the folder with
    the status ('stopped', 'success', or 'failed') appended to the name.

    Args:
        project_id (str): The project ID used as the bucket name.
        analysis_id (str): The analysis ID used as the folder name.
        log_dict (Dict[Literal['analysis', 'nginx'], Dict[str, str]]): A dictionary with keys 'analysis' and 'nginx',
            each containing a dict of deployment names to log contents.
        status (Literal['stopped', 'success', 'failed']): The status to append to the file names.
    """
    client = get_minio_client()
    bucket_name = _LOGS_BUCKET_NAME
    folder_name = f"{project_id}/{analysis_id}"

    # Check if subfolder exists, create if not
    if not folder_exists(client, bucket_name, folder_name):
        client.put_object(bucket_name, folder_name + "/", data=b'', length=0)

    # Upload logs
    for key in log_dict.keys():
        for depl_name, log in log_dict[key].items():
            file_name = f"{depl_name}_{status}.log"
            upload_log_file(client, bucket_name, folder_name, file_name, log)
