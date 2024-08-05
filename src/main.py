import uvicorn
import os
from dotenv import load_dotenv, find_dotenv

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.k8s.kubernetes import load_cluster_config
from src.test.test_db import TestDatabase
from src.api.api import router


def main():
    # load env
    load_dotenv(find_dotenv())

    # load cluster config
    load_cluster_config()

    #TestDatabase()

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
        router,
        prefix="/po",
    )

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == '__main__':
    print("Starting server")
    main()
