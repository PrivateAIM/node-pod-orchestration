# pull images form harbor

# validaition only in running image or if posibel befor

# deploy job
#  - pod creatoin
#  - give tokens
#    - data token
#    - resutlt token
#    - PO token
#  - image execution

# get logs

# hypernate not mvp

# therdown
    # - store logs
    # - job delttion
    # - db update

import json


dict = {"apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
                "name": "helloworld"
            },
        "spec": {
            "selector": {
                "matchLabels": {
                    "app": "helloworld"
                },
            },
            "replicas": 1,  # tells deployment to run 1 pods matching the template,
            "template": {  # create pods using pod definition in this template
                "metadata": {
                    "labels": {
                        "app": "helloworld"
                    },
                },
                "spec": {
                    "containers": [
                        {
                            "name": "helloworld",
                            "image": "karthequian/helloworld:latest",
                            "ports": [
                                {
                                    "containerPort": 80
                                }
                            ]
                        }
                    ]
                }
            }
        }
        }

with open('pod.json', 'w') as f:
    json.dump(dict, f)

# os.system("cat pod.json | kubectl create -f -")
