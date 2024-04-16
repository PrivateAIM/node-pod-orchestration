#!/bin/bash
eval $(minikube docker-env)
# Build Docker image
docker build  -t po:latest .

# Push Docker image to registry (if needed)
#kubectl create serviceaccount po-sa
#sleep 3
#
#kubectl apply -f k8/manifests/node-pod-orchestration-role.yaml
#kubectl apply -f k8/manifests/node-pod-orchestration-rolebinding.yaml

#sleep 3

# Apply Kubernetes YAML files
#kubectl apply -f k8/manifests/postgresql-deployment.yaml
#kubectl apply -f k8/manifests/postgresql-service.yaml
#kubectl apply -f k8/node-pod-orchestration-role.yaml
#kubectl apply -f k8/manifests/node-pod-orchestration-deployment.yaml
#kubectl apply -f k8/manifests/node-pod-orchestration-service.yaml
# Add more kubectl apply commands for any additional YAML files
kubectl apply -f k8/node-po-nginx-config-map.yaml
kubectl apply -f k8/node-po-nginx-deployment.yaml
kubectl apply -f k8/node-po-nginx-service.yaml
#kubectl apply -f k8/node-analysis-network-policy.yaml



# Wait for deployments to be ready
#kubectl wait --for=condition=available deployment/postgresql --timeout=300s
#kubectl wait --for=condition=available deployment/po --timeout=300s

# Optionally, you can run additional commands here, such as database migrations

# Print status
#echo "Deployment complete."
