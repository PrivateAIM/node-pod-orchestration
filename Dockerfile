FROM python:3.11-buster

RUN pip install poetry==1.7.1

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

WORKDIR /app

COPY pyproject.toml poetry.lock ./

RUN touch README.md

RUN poetry install --without dev --no-root && rm -rf $POETRY_CACHE_DIR

COPY src ./src


# Make port 8080 available to the world outside this container
EXPOSE 8080

# Define environment variable
ENV POSTGRES_HOST=<postgres_host>
ENV POSTGRES_DB=<postgres_db>
ENV POSTGRES_USER=<postgres_user>
ENV POSTGRES_PASSWORD=<postgres_password>

ENTRYPOINT ["poetry", "run", "python", "-m", "src.main"]
