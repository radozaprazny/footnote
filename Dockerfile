# The Footnote app (package `matchlens`) as one container (M6): seeds 0, 1 and 3 replayed with their Sonnet 5.5 runs.
# Build, run and smoke test as Azure Container Apps runs it: scripts/container.sh
# Base and uv images pinned by digest (23 Oct): the same build on every machine.
FROM python:3.12-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONUNBUFFERED=1

WORKDIR /app

# the devbox's uv, mounted for the two syncs only (the running app never needs it);
# dependencies first: that layer is rebuilt only when pyproject.toml or uv.lock changes
COPY pyproject.toml uv.lock ./
RUN --mount=from=ghcr.io/astral-sh/uv:0.11.25@sha256:1e3808aa9023d0980e7c15b1fa7c1ac16ff35925780cf5c459858b2d693f01a9,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable --no-install-project

# the project as a wheel (web page and league data inside), then the runs it replays
COPY README.md ./
COPY src ./src
RUN --mount=from=ghcr.io/astral-sh/uv:0.11.25@sha256:1e3808aa9023d0980e7c15b1fa7c1ac16ff35925780cf5c459858b2d693f01a9,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable
COPY demo/runs ./demo/runs

RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin matchlens
USER 10001

EXPOSE 8000
# exec form, the venv's script itself: SIGTERM reaches it; during the cold start `_serve`'s own
# handler ends it (Python as PID 1 ignores a signal it has no handler for), then uvicorn's
# graceful shutdown runs
CMD ["/app/.venv/bin/matchlens", "serve", "--host", "0.0.0.0", "--port", "8000", \
     "--seed", "0", "--seed", "1", "--seed", "3", \
     "--run", "/app/demo/runs/m0", "--run", "/app/demo/runs/m1", "--run", "/app/demo/runs/m3"]
