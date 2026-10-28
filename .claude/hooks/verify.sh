#!/usr/bin/env bash
# Stop hook: Claude may stop only when lint and the tests of the changed files are green.
# At most 3 rounds.
# The session may work in a git worktree (/ship step 2): verify the tree it is in, taken from
# the hook input's cwd, not the project root the hook is registered in.
hooks=$(cd "$(dirname "$0")" && pwd)
cwd=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("cwd", ""))' 2>/dev/null)
root=$(git -C "${cwd:-$CLAUDE_PROJECT_DIR}" rev-parse --show-toplevel 2>/dev/null) \
  || root=$CLAUDE_PROJECT_DIR
cd "$root" || exit 0
counter=.claude/state/stop-attempts
max=3
mkdir -p .claude/state

# Changed and new files; --no-renames also lists a moved file's old path, so its importers run
changes() {
  { git diff --name-only --no-renames HEAD -- "$@"; git ls-files --others --exclude-standard -- "$@"; } \
    | sort -u
}

# No Python changes, nothing to verify
if [ -z "$(changes '*.py')" ]; then
  rm -f "$counter"; exit 0
fi

# A commit in progress in this tree holds its index lock: its pre-commit hook runs the tests of
# the change, and a second run beside it loads the CPU its timing tests need (owner decision,
# 27 Oct)
if [ -e "$(git rev-parse --git-path index.lock)" ]; then
  exit 0
fi

# Only the tests of the changed files, data and config included; none picked means all tests
# (select_tests.py says when). The full suite runs in the pre-commit hook (scripts/ci.sh) and in
# the verifier.
note=""
if ! picked=$(changes '*.py' src tests pyproject.toml uv.lock | python3 "$hooks/select_tests.py"); then
  picked=""; note="select_tests.py failed, so all tests ran"
fi
tests=()
[ -n "$picked" ] && mapfile -t tests <<< "$picked"

# A tree whose lock has pytest-xdist runs them as scripts/ci.sh does: on 6 workers, then those
# marked serial on their own, a 5 (none of that kind) green unless both runs have it (owner, 27
# Oct). An older tree, without it, on one process.
run_tests() {
  if ! grep -qx 'name = "pytest-xdist"' uv.lock 2>/dev/null; then
    uv run pytest -q -x "$@"; return
  fi
  local parallel=0 serial=0
  uv run pytest -q -x -n 6 -m "not serial" "$@" || parallel=$?
  if [ "$parallel" -ne 0 ] && [ "$parallel" -ne 5 ]; then
    return "$parallel"
  fi
  uv run pytest -q -x -m serial "$@" || serial=$?
  if [ "$serial" -eq 5 ] && [ "$parallel" -eq 0 ]; then
    return 0
  fi
  return "$serial"
}

if out=$(uv run ruff check . 2>&1 && run_tests "${tests[@]}" 2>&1); then
  rm -f "$counter"; exit 0            # green: may stop
fi
out="$note${note:+$'\n'}$out"

n=$(( $(cat "$counter" 2>/dev/null || echo 0) + 1 ))
echo "$n" > "$counter"

if [ "$n" -gt "$max" ]; then          # stop rule: a human decides
  rm -f "$counter"; exit 0
fi
if [ "$n" -eq "$max" ]; then
  echo "Attempt $max/$max failed. Stop fixing, tell the owner what blocks, and finish." >&2
  echo "$out" | tail -n 20 >&2
  exit 2
fi

echo "Verification failed (attempt $n/$max). Fix the cause, do not weaken tests:" >&2
echo "$out" | tail -n 40 >&2
exit 2                                # exit 2 = may not stop, keep working
