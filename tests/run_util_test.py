import unittest
from run.utils import create_deployment, delete_deployment, get_deployment_status, get_deployment_logs, get_pod_logs
from kubernetes.client import AppsV1Api, CoreV1Api

class TestUtils(unittest.TestCase):
    def setUp(self):
        self.name = "test"
        self.image = "test_image"
        self.ports = [80, 443]
        self.namespace = "default"
        self.kind = "Deployment"
        self.api_client = AppsV1Api()
        self.core_api_client = CoreV1Api()

    def test_create_deployment(self):
        create_deployment(self.name, self.image, self.ports, self.namespace, self.kind)
        # Add assertions here based on the expected outcome of the function

    def test_delete_deployment(self):
        delete_deployment(self.name, self.namespace)
        # Add assertions here based on the expected outcome of the function

    def test_get_deployment_status(self):
        status = get_deployment_status(self.name, self.namespace)
        # Add assertions here based on the expected outcome of the function

    def test_get_deployment_logs(self):
        logs = get_deployment_logs(self.name, self.namespace)
        # Add assertions here based on the expected outcome of the function

    def test_get_pod_logs(self):
        logs = get_pod_logs(self.core_api_client, self.name, self.namespace)
        # Add assertions here based on the expected outcome of the function

if __name__ == '__main__':
    unittest.main()