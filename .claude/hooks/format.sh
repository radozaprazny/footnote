#!/usr/bin/env bash
# After every edit, format the file (no jq on this box: parse the hook JSON with python3).
file=$(python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))')
[[ "$file" == *.py ]] || exit 0
cd "$CLAUDE_PROJECT_DIR" || exit 0
# fix first, then format: a fix (e.g. SIM905 turning "a b".split() into a list) can leave lines
# longer than 100 that only the formatter wraps
uv run ruff check --fix --unfixable F401 "$file" >/dev/null 2>&1   # keep imports used by the next edit
uv run ruff format "$file" >/dev/null 2>&1
exit 0
