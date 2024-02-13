#!/bin/bash
eval $(minikube -p minikube docker-env)

kubectl delete Service  postgresql-service
kubectl delete  deployment po
docker rmi 'po:latest'