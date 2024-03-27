#!/bin/bash

docker build  -t po:latest .
docker tag flame_test:latest dev-harbor.personalhealthtrain.de/flame_test/po:latest
docker push dev-harbor.personalhealthtrain.de/flame_test/po:latest