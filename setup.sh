#!/bin/bash
eval $(minikube docker-env)
# Build Docker image
docker build  -t po:latest .

# Push Docker image to registry (if needed)
# docker push your-registry/your-image-name

# Apply Kubernetes YAML files
kubectl apply -f k8/postgresql-deployment.yaml
kubectl apply -f k8/postgresql-service.yaml
kubectl apply -f k8/node-pod-orchestration-deployment.yaml
kubectl apply -f k8/node-pod-orchestration-service.yaml
# Add more kubectl apply commands for any additional YAML files

# Wait for deployments to be ready
kubectl wait --for=condition=available deployment/postgresql --timeout=300s
kubectl wait --for=condition=available deployment/po --timeout=300s

# Optionally, you can run additional commands here, such as database migrations

# Print status
echo "Deployment complete."
