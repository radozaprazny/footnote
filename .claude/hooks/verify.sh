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

# Only the tests of the changed files, data and config included; none picked means all tests
# (select_tests.py says when). The full suite runs in the pre-commit hook (scripts/ci.sh) and in
# the verifier.
note=""
if ! picked=$(changes '*.py' src tests pyproject.toml uv.lock | python3 "$hooks/select_tests.py"); then
  picked=""; note="select_tests.py failed, so all tests ran"
fi
tests=()
[ -n "$picked" ] && mapfile -t tests <<< "$picked"
if out=$(uv run ruff check . 2>&1 && uv run pytest -q -x "${tests[@]}" 2>&1); then
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
