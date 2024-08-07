#!/bin/bash
eval $(minikube docker-env)
# Build Docker image
docker build  -t po:latest .


