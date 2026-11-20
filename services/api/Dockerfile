# syntax=docker/dockerfile:1
# The API image: the FastAPI app (ADR-013) and its Alembic migrations. Build from the repo root:
#   docker build -f services/api/Dockerfile -t ghost-bus-la-api .
# Built in CI for linux/arm64 (the VM is a t4g) and pulled by the VM; never built on the VM.

# --- build: install locked dependencies and the API into a virtual environment ------------------
FROM python:3.12.16-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first, in their own layer. uv needs every workspace member's pyproject.toml to
# check the lockfile.
COPY pyproject.toml uv.lock ./
COPY packages/ghostbus_core/pyproject.toml packages/ghostbus_core/pyproject.toml
COPY pipeline/decode/pyproject.toml pipeline/decode/pyproject.toml
COPY services/api/pyproject.toml services/api/pyproject.toml
COPY services/publish/pyproject.toml services/publish/pyproject.toml
COPY services/ingest/pyproject.toml services/ingest/pyproject.toml
RUN uv sync --locked --no-dev --package ghostbus-api --no-install-workspace

COPY services/api/src services/api/src
RUN uv sync --locked --no-dev --package ghostbus-api --no-editable

# --- runtime ---------------------------------------------------------------------------------
FROM python:3.12.16-slim-bookworm
RUN useradd --system --uid 10002 --no-create-home ghostbus
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
WORKDIR /app
USER ghostbus

# Process up (API spec section 4.4). Readiness (/readyz) also needs fresh data, which is the
# pipeline's job, so a deploy checks it separately.
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2).status == 200 else 1)"]

EXPOSE 8000
# Behind Caddy, on the private Docker network only: trust its X-Forwarded-* headers.
CMD ["uvicorn", "--factory", "ghostbus_api.main:create_app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
