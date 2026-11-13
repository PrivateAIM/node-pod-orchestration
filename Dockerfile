FROM python:3.11-alpine AS builder

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN pip install poetry==1.7.1

WORKDIR /app

COPY pyproject.toml poetry.lock ./

# Install runtime deps into /app/.venv, then strip what isn't needed at runtime
RUN touch README.md \
 && poetry install --without dev --no-root \
 && rm -rf $POETRY_CACHE_DIR \
 && rm -rf .venv/lib/python3.11/site-packages/pip \
           .venv/lib/python3.11/site-packages/pip-* \
           .venv/lib/python3.11/site-packages/setuptools \
           .venv/lib/python3.11/site-packages/setuptools-* \
           .venv/lib/python3.11/site-packages/wheel \
           .venv/lib/python3.11/site-packages/wheel-* \
 && find .venv -type d -name __pycache__ -prune -exec rm -rf {} +


FROM python:3.11-alpine

RUN adduser -u 10000 -D podorchestrator

WORKDIR /app

# venv must live at the same path as in the builder (absolute paths in scripts/pyvenv.cfg)
COPY --from=builder --chown=10000:10000 /app/.venv /app/.venv
COPY --chown=10000:10000 src ./src

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER 10000:10000

EXPOSE 8000

ENTRYPOINT ["python", "-m", "src.main"]