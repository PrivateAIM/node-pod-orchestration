from httpx import Client
from src.k8s.utils import find_k8s_resources


def delete_subscription(analysis_id: str, keycloak_token: str, namespace: str = 'default') -> None:
    # get the service name of the message broker
    message_broker_service_name = find_k8s_resources('service',
                                                     'label',
                                                     'component=flame-message-broker',
                                                     namespace=namespace)[0]
    mb_client = Client(base_url=f"http://{message_broker_service_name}",
                       headers={"Authorization": f"Bearer {keycloak_token}",
                                "accept": "application/json"},
                       follow_redirects=True)
    mb_client.delete(f"/analyses/{analysis_id}/messages/subscriptions")
