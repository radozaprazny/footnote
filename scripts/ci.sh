#!/usr/bin/env bash
# Local CI: the independent judge. GitHub CI (.github/workflows/ci.yml) runs this same script in
# full, and so does anyone before a merge into main or a deploy. With --changed it reads the
# changed paths from stdin and runs the lint and only their tests, imports between the modules in
# src/ followed (.claude/hooks/select_tests.py --follow-imports); the pre-commit hook does that
# (owner decision, 27 Oct). A selection that comes back empty means every test.
set -euo pipefail
cd "$(dirname "$0")/.."
changed=""
if [ "${1:-}" = "--changed" ]; then
  changed=$(cat)
fi
# The tests on 6 workers, then those marked serial on their own: their timing flakes under load
# (owner decision, 27 Oct). pytest's 5 means none of the selection is of that kind; both 5 means
# nothing ran, which is red.
run_tests() {
  local parallel=0 serial=0
  HYPOTHESIS_PROFILE=ci uv run pytest -q -n 6 -m "not serial" "$@" || parallel=$?
  if [ "$parallel" -ne 0 ] && [ "$parallel" -ne 5 ]; then
    return "$parallel"
  fi
  HYPOTHESIS_PROFILE=ci uv run pytest -q -m serial "$@" || serial=$?
  if [ "$serial" -eq 5 ] && [ "$parallel" -eq 0 ]; then
    return 0
  fi
  return "$serial"
}
uv sync --locked -q
uv run ruff check .
uv run ruff format --check .
if [ "${1:-}" = "--changed" ]; then
  # the pre-commit hook passes HEAD's selection in CI_SELECT, so a commit cannot loosen it
  picked=$(printf '%s\n' "$changed" | python3 "${CI_SELECT:-.claude/hooks/select_tests.py}" --follow-imports)
  if [ -n "$picked" ]; then
    echo "ci: the tests of the changed files: $(echo "$picked" | wc -l) files" >&2
    # shellcheck disable=SC2086  # one test file per word
    run_tests $picked
    exit 0
  fi
  echo "ci: every test (a change needs them all)" >&2
fi
run_tests
