#!/usr/bin/env bash
# Local CI: the independent judge. GitHub CI (.github/workflows/ci.yml) runs this same script.
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --locked -q
uv run ruff check .
uv run ruff format --check .
HYPOTHESIS_PROFILE=ci uv run pytest -q
