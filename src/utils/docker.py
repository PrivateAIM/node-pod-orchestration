

#_CLIENT = docker.from_env()
_CLIENT = None
#_CLIENT.login(
#    username=os.getenv("NODE_NAME"),
#    password=os.getenv("HARBOR_PW"),
#    registry=os.getenv("HARBOR_URL"),
#)


def download_image(image_registry_address: str) -> str:
    _CLIENT.images.pull(image_registry_address)
    return image_registry_address.split('/')[-1] + ':latest'


def validate_image(image_name: str, master_image_name: str) -> bool:
    _ = download_image(master_image_name)

    master_image = _CLIENT.images.get(master_image_name)
    image = _CLIENT.images.get(image_name)

    return _history_validation(image, master_image) and _image_valid(image, master_image)


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


def _image_valid(image, master_image) -> bool:
    return True
