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
- JWT authentication against the global Authup instance (client tokens only) on all endpoints except `/po/healthz`, with a deprecated fallback to a local Keycloak realm

## Tech Stack

| Component        | Choice                                    |
|------------------|-------------------------------------------|
| Language         | Python 3.10+                              |
| Web framework    | FastAPI + Uvicorn (port 8000)             |
| Orchestration    | Kubernetes Python client                  |
| Database         | PostgreSQL + SQLAlchemy 2.0               |
| Auth             | Keycloak / Authup (OAuth2 / JWT)          |
| Package manager  | Poetry                                    |
| Lint / format    | Ruff (via pre-commit)                     |
| Container base   | `python:3.11-alpine` (non-root UID 10000) |

## Requirements

- Kubernetes cluster with RBAC to manage `Deployment`, `Service`, `NetworkPolicy`, `ConfigMap`, and `Secret` resources
- PostgreSQL database
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

When an analysis finishes (`EXECUTED`, `FAILED`, or `STUCK` after the restart limit), the status loop stops its deployment and keeps the database entry until the FLAME Hub reports the same final status. It re-pushes the status with exponential backoff (up to 5 retries per pass) and deletes the entry once the Hub agrees, or once the Hub no longer knows the analysis. `DELETE /po/delete/{id}` removes the entry straight away, without a Hub check.

## API

Base path: `/po` — all endpoints require a valid bearer token except `GET /po/healthz`.

The token issuer is selected at startup by `KEYCLOAK_URL`:

- **Authup** (default, `KEYCLOAK_URL` unset or empty): every endpoint verifies tokens against the
  global Authup JWKS (`AUTHUP_JWKS_URL`). Only Authup **client** tokens are accepted
  (`sub_kind == "client"`, e.g. analysis tokens or the node's Hub client); Authup user tokens are
  rejected.
- **Keycloak** (deprecated, `KEYCLOAK_URL` set and non-empty): all endpoints except
  `POST /po/stream_logs` verify tokens against the local Keycloak realm (`KEYCLOAK_URL` /
  `KEYCLOAK_REALM`) and log a deprecation warning per request. `POST /po/stream_logs` is always
  verified against Authup, since analysis tokens are minted by Authup (`AUTHUP_TOKEN_URL`), so
  `AUTHUP_JWKS_URL` is required in this mode as well.

If `AUTHUP_JWKS_URL` is missing, every Authup-verified endpoint answers with `500`.

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
| `AUTHUP_JWKS_URL` | Global Authup JWKS endpoint, used to verify API tokens (all endpoints in Authup mode, `/po/stream_logs` in Keycloak mode; see [API](#api)) |
| `AUTHUP_TOKEN_URL` | Global Authup token endpoint, used to mint each analysis's access token |
| `RESULT_CLIENT_ID`, `RESULT_CLIENT_SECRET` | Result-service OAuth client |
| `HUB_CLIENT_ID`, `HUB_CLIENT_SECRET`, `HUB_URL_CORE`, `HUB_URL_AUTH` | FLAME Hub access |

> Registry credentials for analysis images are **not** configured here. On every analysis
> start (restarts included) the service reads its node's registry project credentials from
> the Hub (`GET /nodes/{node_id}/registry/credentials`, using the `HUB_CLIENT_*` node client),
> turns them into a `dockerconfigjson` pull secret and pulls `<host>/<project>/<analysis_id>`.
> They are not persisted. If the Hub is unreachable during a restart, the existing pull secret
> and the previously used image are reused.

### Optional

| Variable | Description | Default |
|----------|-------------|---------|
| `PO_HTTP_PROXY`, `PO_HTTPS_PROXY` | Outbound proxy for Hub traffic | unset |
| `HUB_LOGGING` | Forward analysis logs to the FLAME Hub | unset |
| `EXTRA_CA_CERTS` | Additional CA bundle path | unset |
| `STATUS_LOOP_INTERVAL` | Status-loop interval in seconds | `10` |
| `NGINX_IMAGE` | Image for the reverse-proxy sidecar | `nginxinc/nginx-unprivileged:1.31.7-alpine-slim` |
| `NET_STATS_ENABLED` | Enable the network-statistics sidecar (`1` / `true`) | disabled |
| `NET_STATS_IMAGE` | Image for that sidecar | `busybox:1.37` |
| `KEYCLOAK_URL`, `KEYCLOAK_REALM` | Deprecated. A non-empty `KEYCLOAK_URL` switches the API to Keycloak mode (see [API](#api)) | unset, `flame` |

## Project Layout

```
src/
├── main.py               # Entry point: config load + API and status threads
├── api/
│   ├── api.py            # FastAPI app + all REST endpoints
│   ├── constants.py      # Auth backend selection (Authup / Keycloak)
│   └── oauth.py          # Bearer token validation
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