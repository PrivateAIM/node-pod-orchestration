#!/bin/bash
eval $(minikube -p minikube docker-env)

#kubectl delete all deploymets with test in name
kubectl delete deployment $(kubectl get deployments | grep test | awk '{print $1}')

kubectl delete service postgresql-service
kubectl delete deployment po
kubectl delete serviceaccount po-sa
kubectl delete rolebinding po-sa-binding
kubectl delete secret po-sa-token
kubectl delete deployment postgresql
kubectl delete secret harbor-credentials
kubectl delete deployment base

sleep 3
docker rmi 'po:latest'