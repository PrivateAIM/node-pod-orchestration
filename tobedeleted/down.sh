#!/bin/bash
eval $(minikube -p minikube docker-env)

#kubectl delete all deployments with test in name
kubectl delete deployment $(kubectl get deployments | grep test | awk '{print $1}')

kubectl delete service postgresql-service
kubectl delete deployment po
kubectl delete service po-service
kubectl delete serviceaccount po-sa
kubectl delete rolebinding po-sa-binding
kubectl delete secret po-sa-token
kubectl delete deployment postgresql
kubectl delete secret harbor-credentials
kubectl delete deployment base
kubectl delete deployment po-nginx
kubectl delete service po-nginx-service
kubectl delete configmap po-nginx-config
kubectl delete networkpolicy po-analysis-network-policy

sleep 3
docker rmi 'po:latest'
