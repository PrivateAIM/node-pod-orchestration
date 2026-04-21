# PrivateAIM Node Pod Orchestration

Kubernetes-based orchestration service for the [FLAME](https://privateaim.de) (Federated Learning in a Medical Ecosystem) platform. It manages the full lifecycle of analysis pods within a FLAME node: creation, execution, monitoring, cleanup, and archival.

Each analysis runs in a dedicated Kubernetes deployment with an nginx reverse-proxy sidecar that provides secure, token-authenticated egress to node-side services (FLAME Hub, result store, data sources).

## Features

- REST API to create, stop, delete, and inspect analysis pods
- Per-analysis Kubernetes `Deployment`, `Service`, `NetworkPolicy`, `ConfigMap`, and Harbor pull secret
- Background status loop that syncs pod state with the FLAME Hub and auto-restarts stuck pods (up to 10 retries)
- Archival of completed analyses to a separate database table
- Structured JSON logging with custom log levels (`ACTION`, `STATUS_LOOP`)
- Keycloak OAuth2 / JWT authentication on all endpoints except `/po/healthz`

## Tech Stack

| Component        | Choice                                    |
|------------------|-------------------------------------------|
| Language         | Python 3.10+                              |
| Web framework    | FastAPI + Uvicorn (port 8000)             |
| Orchestration    | Kubernetes Python client                  |
| Database         | PostgreSQL + SQLAlchemy 2.0               |
| Auth             | Keycloak (OAuth2 / JWT)                   |
| Package manager  | Poetry                                    |
| Lint / format    | Ruff (via pre-commit)                     |
| Container base   | `python:3.11-alpine` (non-root UID 10000) |

## Requirements

- Kubernetes cluster with RBAC to manage `Deployment`, `Service`, `NetworkPolicy`, `ConfigMap`, and `Secret` resources
- PostgreSQL database
- Keycloak realm with a configured client
- Access to a [FLAME Hub](https://github.com/PrivateAIM/hub) instance
- Harbor registry for analysis images
- Docker (for local image builds)

## Quick Start

### Local development

```bash
# Install dependencies
poetry install

# Copy and fill in environment variables
cp .env.template .env

# Run the service
poetry run python -m src.main
```

The API is then available at `http://localhost:8000/po/` with Swagger docs at `http://localhost:8000/api/docs`.

### Docker

```bash
docker build -t node-pod-orchestration:latest .
docker run --env-file .env -p 8000:8000 node-pod-orchestration:latest
```

### Tests & linting

```bash
pytest
poetry run ruff check --fix src/
poetry run ruff format src/
```

## Architecture

Two threads are started at boot:

1. **FastAPI server** — exposes the REST API under `/po`.
2. **Status monitoring loop** — periodically reconciles pod state with the FLAME Hub and the Kubernetes cluster.

Analyses move through the following states:

```
STARTING → STARTED → EXECUTING → EXECUTED | STOPPED | FAILED
                            ↘ STUCK (transient, auto-restart up to 10x)
```

Deployments are named `analysis-{analysis_id}-{restart_counter}`.

## API

Base path: `/po` — all endpoints require a valid Keycloak bearer token except `GET /po/healthz`.

| Method | Path                           | Purpose                            |
|--------|--------------------------------|------------------------------------|
| POST   | `/po/`                         | Create a new analysis              |
| GET    | `/po/history` · `/po/history/{id}` | Analysis history                |
| GET    | `/po/logs` · `/po/logs/{id}`   | Analysis logs                      |
| POST   | `/po/stream_logs`              | Stream live pod logs               |
| GET    | `/po/status` · `/po/status/{id}` | Status and progress              |
| GET    | `/po/pods` · `/po/pods/{id}`   | Raw pod info                       |
| PUT    | `/po/stop` · `/po/stop/{id}`   | Stop analyses                      |
| DELETE | `/po/delete` · `/po/delete/{id}` | Delete analyses                  |
| DELETE | `/po/cleanup/{cleanup_type}`   | Bulk cleanup by type               |
| GET    | `/po/healthz`                  | Liveness probe (no auth)           |

Interactive docs: `/api/docs` (Swagger), `/api/redoc` (ReDoc).

## Configuration

Configuration is supplied via environment variables. See `.env.template` for the full list.

### Required

| Variable | Description |
|----------|-------------|
| `POSTGRES_HOST`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | PostgreSQL connection |
| `KEYCLOAK_URL`, `KEYCLOAK_REALM` | Keycloak instance |
| `RESULT_CLIENT_ID`, `RESULT_CLIENT_SECRET` | Result-service OAuth client |
| `HUB_CLIENT_ID`, `HUB_CLIENT_SECRET`, `HUB_URL_CORE`, `HUB_URL_AUTH` | FLAME Hub access |
| `HARBOR_URL`, `HARBOR_USER`, `HARBOR_PW` | Harbor registry for analysis images |
| `NODE_NAME` | Logical node identifier |

### Optional

| Variable | Description |
|----------|-------------|
| `NODE_KEY`, `NODE_KEY_PW` | Node private key (path + passphrase) |
| `PO_HTTP_PROXY`, `PO_HTTPS_PROXY` | Outbound proxy |
| `HUB_LOGGING` | Enable Hub client logging |
| `EXTRA_CA_CERTS` | Additional CA bundle path |
| `STATUS_LOOP_INTERVAL` | Status-loop interval in seconds |

## Project Layout

```
src/
├── main.py               # Entry point: config load + API and status threads
├── api/
│   ├── api.py            # FastAPI app + all REST endpoints
│   └── oauth.py          # Keycloak JWT validation
├── k8s/
│   ├── kubernetes.py     # K8s resource creation
│   └── utils.py          # K8s lookup and deletion
├── resources/
│   ├── database/         # SQLAlchemy models + CRUD wrapper
│   ├── analysis/         # Analysis Pydantic models
│   ├── log/              # Log entity models
│   └── utils.py          # Analysis lifecycle business logic
├── status/
│   ├── status.py         # Background status loop
│   └── constants.py      # Status enums and timeouts
└── utils/                # Logging, tokens, Hub client, helpers
tests/                    # Pytest suite (see tests/TEST_PLAN.md)
```

## Development Conventions

- **Commits:** Conventional Commits (enforced by pre-commit).
- **Hooks:** ruff check/format, trailing whitespace, large-file check, YAML/TOML validation.
- **Logs:** Single JSON object per line via `src/utils/po_logging.py`; use `get_logger()` in new modules.
- **CI/CD:** GitHub Actions builds and pushes the image to GHCR on push to `main`, `canary`, and `new_hub`.

## License

Apache 2.0 — see [LICENSE](LICENSE).