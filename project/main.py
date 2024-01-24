import argparse
from run.utils import create_deployment
from project.api.po_servers.api import api_router
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--images', help='name of the image that has to be loaded')
    parser.add_argument('--name', help='name of the deployment ')
    args = parser.parse_args()

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
    print(args.images)
    print(args.name)
    # create_deployment("hallo-world", "karthequian/helloworld:latest", [80, 443])

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == '__main__':
    main()
