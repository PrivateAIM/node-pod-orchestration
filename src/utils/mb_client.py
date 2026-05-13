from httpx import Client, ConnectError, HTTPStatusError, TimeoutException, ConnectTimeout
from src.k8s.utils import find_k8s_resources
from src.utils.po_logging import get_logger


logger = get_logger()


def delete_subscription(analysis_id: str, keycloak_token: str, namespace: str = 'default') -> None:
    try:
        # get the service name of the message broker
        message_broker_service_name = find_k8s_resources('service',
                                                         'label',
                                                         'component=flame-message-broker',
                                                         namespace=namespace)[0]
        mb_client = Client(base_url=f"http://{message_broker_service_name}",
                           headers={"Authorization": f"Bearer {keycloak_token}",
                                    "accept": "application/json"},
                           follow_redirects=True)
        response = mb_client.delete(f"/analyses/{analysis_id}/messages/subscriptions")
        response.raise_for_status()
    except (HTTPStatusError, ConnectError, TimeoutException, ConnectTimeout, IndexError) as e:
        logger.warning(f"Could not reach Message-Broker service to delete analysis subscription "
                       f"(analysis_id={analysis_id}): {repr(e)}")
