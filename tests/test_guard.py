"""Regression tests for the Bash gate in .claude/hooks/guard.py."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / ".claude" / "hooks" / "guard.py"


def run_guard(payload: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(ROOT)}
    return subprocess.run([str(GUARD)], input=payload, capture_output=True, text=True, env=env)


def decide(command: str) -> str:
    result = run_guard(json.dumps({"tool_input": {"command": command}}))
    if result.returncode == 2:
        return "deny"
    if '"ask"' in result.stdout:
        return "ask"
    assert result.returncode == 0, result.stderr
    return "allow"


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        # destructive or secret: never
        ("git push -u origin main", "deny"),
        ("git push origin HEAD:main", "deny"),
        ("git push --force origin feature", "deny"),
        ("git push -f origin feature", "deny"),
        ("git -C /some/repo push --force origin main", "deny"),
        ("git --no-pager push origin +main", "deny"),
        ("cat .env", "deny"),
        ("python3 -c \"print(open('.env').read())\"", "deny"),
        ("sed -n 1p ./.env.local", "deny"),
        ("cat infra/.env", "deny"),
        ("rm -rf ~", "deny"),
        ("rm -fr ~/*", "deny"),
        ("rm -r -f /", "deny"),
        ("rm --recursive $HOME", "deny"),
        ("rm -fr .", "deny"),
        ("rm -fr ../18_plhack", "deny"),
        (f"rm -r {ROOT}", "deny"),
        # skipping the judge: never
        ("git commit --no-verify -m x", "deny"),
        ("git commit --no-v -m x", "deny"),
        ("git commit -nm wip", "deny"),
        ("git commit -anm wip", "deny"),
        ("git -C . commit -n -m x", "deny"),
        ("git push --no-verify origin feature", "deny"),
        ("git -c core.hooksPath=/dev/null commit -m x", "deny"),
        ("git config core.hooksPath .githooks", "deny"),
        ("git config core.hookspath /dev/null", "deny"),
        # pushing: only the owner, from a terminal outside Claude (owner decision 20 Oct)
        ("git push -u origin feature-x", "deny"),
        ("git -c x=y push", "deny"),
        ("git push", "deny"),
        ("git -C /home/radoz/projects/18_plhack push origin m2-interpret", "deny"),
        ("uv run pytest -q && git push origin m2-interpret", "deny"),
        # publishing, billed Azure, secrets, destructive git: owner confirms
        ("gh repo create plhack --private --source .", "ask"),
        ("gh -R owner/repo pr create --fill", "ask"),
        ("gh api -X PATCH repos/o/r -f visibility=public", "ask"),
        ("gh api repos/o/r -f visibility=public", "ask"),
        ("docker push registry/image:tag", "ask"),
        ("azd up", "ask"),
        ("az rest -m put --url https://management.azure.com/x", "ask"),
        ("az rest --method=post --url https://management.azure.com/x", "ask"),
        ("az group create -n rg-x -l swedencentral", "ask"),
        ("az containerapp up --name x", "ask"),
        ("az cognitiveservices account deployment create -n x -g y", "ask"),
        ("az ad sp create-for-rbac -n x", "ask"),
        ("az storage blob upload-batch -d c -s .", "ask"),
        ("az cognitiveservices account keys list -n x -g y", "ask"),
        ("az keyvault secret show --vault-name v -n s", "ask"),
        ("az account get-access-token", "ask"),
        ("git switch --discard-changes m1", "ask"),
        ("git switch -C main", "ask"),
        ("git branch -D feature", "ask"),
        ("git branch -f main abc123", "ask"),
        ("git reset --hard HEAD~1", "ask"),
        ("git clean -fd", "ask"),
        ("git checkout -- .", "ask"),
        ("git restore src/x.py", "ask"),
        ("git switch main && git merge --ff-only m1-ingest", "ask"),
        ("sed -i s/a/b/ scripts/ci.sh", "ask"),
        ("chmod -x .githooks/pre-commit", "ask"),
        ("echo x >> .claude/settings.json", "ask"),
        ("mv .githooks hooks-off && mv x .githooks/", "ask"),
        ("mv pyproject.toml /tmp/", "ask"),
        ("cp evil.json .claude/settings.json", "ask"),
        ("/bin/cp -r hooks/ .githooks/", "ask"),
        ("cp x .claude/hooks/guard.py 2>/dev/null", "ask"),
        ("cp x .claude/hooks/guard.py 2> /dev/null", "ask"),
        ("cp a /tmp/a && cp b scripts/ci.sh", "ask"),
        ("cp -t .githooks/ pre-commit", "ask"),
        ("cp -rt.githooks/ pre-commit", "ask"),
        ("cp --target-directory=.github/workflows ci.yml", "ask"),
        ("cp --target .github/workflows ci.yml", "ask"),
        ("cp x pyproject.toml -S .bak", "ask"),
        ("cp x pyproject.toml --suffix .bak", "ask"),
        ('cp pyproject.toml "$DEST"', "ask"),
        ("cp pyproject.toml ~/x", "ask"),
        ("cp 'pyproject.toml /tmp/x", "ask"),
        ("echo cp pyproject.toml", "ask"),
        # normal work: no prompt
        ("uv run pytest -q", "allow"),
        ("cat example.env", "allow"),
        ("git log -n 5", "allow"),
        ("git commit -m 'feat: add possession shares'", "allow"),
        ("git switch -c item-x", "allow"),
        ("git branch -d merged-item", "allow"),
        ("git stash push -u -m wip-tag", "allow"),
        ("cat pyproject.toml 2>/dev/null", "allow"),
        ("rm -rf /tmp/plhack-scratch", "allow"),
        ("cp -r src tests pyproject.toml /tmp/verify/mut/", "allow"),
        ("cp -- .claude/hooks/guard.py /tmp/guard.py 2> /dev/null", "allow"),
        ("cp pyproject.toml /tmp/x --suffix=.bak", "allow"),
        # the verifier's copy that waited 5 h for the owner on 20 Oct
        (
            "ls /tmp/verify-passing/ && mkdir /tmp/verify-passing/mut && cp -r src tests "
            "pyproject.toml /tmp/verify-passing/mut/ && ls /tmp/verify-passing/mut "
            "/tmp/verify-passing/mut/tests | head -40; ls -a tests | grep -i conftest; "
            'grep -n "profile" -r tests/conftest.py pyproject.toml 2>/dev/null | head',
            "allow",
        ),
        ("az group list -o table", "allow"),
        ("az consumption usage list --start-date 2026-10-01", "allow"),
        ("az cognitiveservices model list --location swedencentral", "allow"),
        ("az account set --subscription 00000000-0000-0000-0000-000000000000", "allow"),
        ("az login --use-device-code", "allow"),
        ("gh api repos/o/r", "allow"),
    ],
)
def test_guard_decision(command, expected):
    assert decide(command) == expected


def test_merge_on_branch():
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True, cwd=ROOT
    ).stdout.strip()
    expected = "ask" if branch in {"main", "master", ""} else "allow"
    assert decide("git merge --ff-only item-x") == expected


def test_guard_is_executable():
    assert os.access(GUARD, os.X_OK)


@pytest.mark.parametrize("payload", ["not json", '{"tool_input": {"command": null}}'])
def test_guard_fails_closed(payload):
    assert run_guard(payload).returncode == 2
