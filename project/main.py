from kubernetes import client, config
import os


def deploy_image_from_harbor(image_name, namespace, deployment_name):
    # Load kubeconfig if available, else use default in-cluster config
    config.load_kube_config()

    # Create an instance of the Kubernetes client
    api_instance = client.AppsV1Api()

    # Specify the container details
    container = client.V1Container(
        name=deployment_name,
        image=image_name,
        image_pull_policy="Always"  # Modify as needed
    )

    # Specify the pod template
    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"app": deployment_name}),
        spec=client.V1PodSpec(containers=[container])
    )

    # Specify the deployment details
    spec = client.V1DeploymentSpec(
        replicas=1,
        selector=client.V1LabelSelector(match_labels={"app": deployment_name}),
        template=template
    )

    # Create the deployment object
    deployment = client.V1Deployment(
        api_version="apps/v1",
        kind="Deployment",
        metadata=client.V1ObjectMeta(name=deployment_name),
        spec=spec
    )

    try:
        # Create the deployment
        api_response = api_instance.create_namespaced_deployment(
            body=deployment,
            namespace=namespace
        )
        print("Deployment created. Status='%s'" % str(api_response.status))
    except Exception as e:
        print("Error: %s" % e)


if __name__ == "__main__":
    # Replace with your Harbor image details
    #docker pull harbor.personalhealthtrain.de/phtstation02/aacd0d1c-3985-4976-858e-88249a02d35a@sha256:98835795fbe591b6c0eac898bac736a8e084a7e4b5d6a2bf7f27a887c04d4118
    harbor_image = "harbor.personalhealthtrain.de/phtstation02/aacd0d1c-3985-4976-858e-88249a02d35a:latest"
    k8s_namespace = "default"
    deployment_name = "my-deployment"

    # Deploy the image
    deploy_image_from_harbor(harbor_image, k8s_namespace, deployment_name)
