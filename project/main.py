from run.utils import create_deployment, delete_deployment ,get_deployment_logs
from project.api.po_servers.api import api_router
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

def main():


    app = FastAPI(title="FLAME PO",
                  docs_url="/api/docs",
                  redoc_url="/api/redoc",
                  openapi_url="/api/v1/openapi.json", )

    origins = [
        "http://localhost:8080/",
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(
        api_router,
        prefix="/api",
    )

    # server = PoBaseServer()

    #create_deployment("hallo-world", "karthequian/helloworld:latest", [80, 443])

    #uvicorn.run(app, host="0.0.0.0", port=8000)

    #create_deployment( "ubuntu-test3", "ubuntu:latest", [80, 443])
    #delete_deployment("ubuntu-test3")
    get_deployment_logs("helloworld")
if __name__ == '__main__':
    main()
