# PrivateAIM Node Pod Orchestration

Kubernetes-based orchestration service for the [FLAME](https://privateaim.de) (Federated Learning in a Medical Ecosystem) platform. It manages the full lifecycle of analysis pods within a FLAME node: creation, execution, monitoring, cleanup, and archival.

Each analysis runs in a dedicated Kubernetes deployment with an nginx reverse-proxy sidecar that provides secure, token-authenticated egress to node-side services (FLAME Hub, result store, data sources).

## Features

- REST API to create, stop, delete, and inspect analysis pods
- Per-analysis Kubernetes `Deployment`, `Service`, `NetworkPolicy`, `ConfigMap`, and registry pull secret
- Optional network-statistics sidecar per analysis (`NET_STATS_ENABLED`)
- Background status loop that syncs pod state with the FLAME Hub and auto-restarts stuck pods (up to 3 restarts, then `FAILED`)
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
                            ↘ STUCK (transient, auto-restart up to 3x)
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

Configuration is supplied via environment variables. The tables below list every variable the
service actually reads; `.env.template` is a starting point for local development and currently
lags behind them.

### Required

| Variable | Description |
|----------|-------------|
| `POSTGRES_HOST`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | PostgreSQL connection |
| `KEYCLOAK_URL`, `KEYCLOAK_REALM` | Keycloak instance |
| `RESULT_CLIENT_ID`, `RESULT_CLIENT_SECRET` | Result-service OAuth client |
| `HUB_CLIENT_ID`, `HUB_CLIENT_SECRET`, `HUB_URL_CORE`, `HUB_URL_AUTH` | FLAME Hub access |

> Registry credentials for analysis images are **not** configured here. They are supplied
> per analysis in the `POST /po/` request body (`registry_url`, `registry_user`,
> `registry_password`) and turned into a `dockerconfigjson` pull secret for that analysis.

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `PO_HTTP_PROXY`, `PO_HTTPS_PROXY` | Outbound proxy for Hub traffic | unset |
| `HUB_LOGGING` | Forward analysis logs to the FLAME Hub | unset |
| `EXTRA_CA_CERTS` | Additional CA bundle path | unset |
| `STATUS_LOOP_INTERVAL` | Status-loop interval in seconds | `10` |
| `NGINX_IMAGE` | Image for the reverse-proxy sidecar | `nginxinc/nginx-unprivileged:1.31.4-alpine-perl` |
| `NET_STATS_ENABLED` | Enable the network-statistics sidecar (`1` / `true`) | disabled |
| `NET_STATS_IMAGE` | Image for that sidecar | `busybox:1.37` |

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
└── utils/                # Logging, tokens, Hub client, message broker, helpers
tests/                    # Pytest suite
```

## Development Conventions

- **Commits:** Conventional Commits (enforced by pre-commit).
- **Hooks:** ruff check/format, trailing whitespace, large-file check, YAML/TOML validation.
- **Logs:** Single JSON object per line via `src/utils/po_logging.py`; use `get_logger()` in new modules.
- **CI/CD:** GitHub Actions builds and pushes the image to GHCR on push to `main`, `canary`, and `new_hub`.

## License

Apache 2.0 — see [LICENSE](LICENSE).