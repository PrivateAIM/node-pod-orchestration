import os
import docker


_REGISTRY_ADDRESS = os.getenv("HARBOR_URL")


def _default_docker_client():
    client = docker.from_env()
    client.login(
        username=os.getenv("NODE_NAME"),
        password=os.getenv("HARBOR_PW"),
        registry=_REGISTRY_ADDRESS,
    )
    return client


def download_image(image: str) -> None:
    client = _default_docker_client()
    client.images.pull(image)


def validate_image(image_name: str, master_image_name: str) -> bool:
    download_image(master_image_name)

    client = _default_docker_client()
    master_image = client.images.get(master_image_name)
    image = client.images.get(image_name)

    return _history_validation(image, master_image) and _img_file_system_identical(image, master_image)


def _history_validation(image, master_image) -> bool:
    master_img_entry_ids = [
        {key: entry[key] for key in ["Created", "CreatedBy", "Size"]}
        for entry in master_image.history()
    ]
    img_entry_ids = [
        {key: entry[key] for key in ["Created", "CreatedBy", "Size"]}
        for entry in image.history()
    ]

    return all([entry_dict in img_entry_ids for entry_dict in master_img_entry_ids])


def _img_file_system_identical(image, master_image) -> bool:
    return True
