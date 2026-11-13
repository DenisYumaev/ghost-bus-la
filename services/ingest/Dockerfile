# syntax=docker/dockerfile:1
# The ingest service image. Build from the repository root:
#   docker build -f services/ingest/Dockerfile -t ghost-bus-la-ingest .
# Built in CI for linux/arm64 (the VM is a t4g) and pulled by the VM; never built on the VM.

# --- build: install locked dependencies and ingest into a virtual environment ---------------------
FROM python:3.12.16-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first, in their own layer, so code changes don't reinstall them. uv needs every
# workspace member's pyproject.toml to check the lockfile.
COPY pyproject.toml uv.lock ./
COPY packages/ghostbus_core/pyproject.toml packages/ghostbus_core/pyproject.toml
COPY services/ingest/pyproject.toml services/ingest/pyproject.toml
RUN uv sync --locked --no-dev --package ghostbus-ingest --no-install-workspace

# Then ingest itself, installed as a normal (non-editable) package. ghostbus_core is never
# copied: ingest doesn't depend on it (hard rule 3).
COPY services/ingest/src services/ingest/src
RUN uv sync --locked --no-dev --package ghostbus-ingest --no-editable

# --- runtime: just Python, the virtual environment, and the feed config ---------------------------
FROM python:3.12.16-slim-bookworm
RUN useradd --system --uid 10001 --no-create-home ghostbus \
    && mkdir -p /var/lib/ghostbus/spool \
    && chown ghostbus /var/lib/ghostbus/spool
COPY --from=build /app/.venv /app/.venv
COPY config/feeds.toml /app/config/feeds.toml

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    GHOSTBUS_FEEDS_CONFIG=/app/config/feeds.toml \
    GHOSTBUS_SPOOL_DIR=/var/lib/ghostbus/spool
WORKDIR /app
USER ghostbus
VOLUME /var/lib/ghostbus/spool

# Healthy once every feed has succeeded within three of its intervals (spec 2.6). The service
# itself grants a 3-interval grace at startup, so start_period only needs to cover boot.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8081/healthz', timeout=4).status == 200 else 1)"]

# docker stop sends SIGTERM: final cuts, then a final upload pass (service.py).
STOPSIGNAL SIGTERM
CMD ["python", "-m", "ghostbus_ingest"]
