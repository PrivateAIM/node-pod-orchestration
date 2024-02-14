import uvicorn
import psycopg2

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.api import router
from src.resources.database.entity import Database


def main():
    # TODO: temporary for testing
    db = Database()

    analysis = db.create_analysis(analysis_id="1", status="pending")
    print(analysis)
    retrieved_analysis = db.get_analysis(analysis_id="1")
    print(retrieved_analysis.status)

    updated_analysis = db.update_analysis(analysis_id="1", status="completed")
    print(updated_analysis.status)

    db.delete_analysis(analysis_id="1")
    db.close()
    # TODO

    print("Database created2")

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


    #uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == '__main__':
    print("Starting server")
    main()
