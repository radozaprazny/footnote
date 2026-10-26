#!/usr/bin/env python3
"""Gate before every Bash command.

DENY: exit 2, the command never runs and Claude gets the reason. `git push` is always DENY:
      only the owner pushes, from a terminal outside Claude (owner decision, 20 Oct).
ASK:  the owner must confirm in the UI, in every permission mode: publishing, billed Azure,
      printing secrets, destructive git, merges into main, writes to the harness.
Fails closed: any error in this script denies the command.
"""

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

# `git` followed by global options (-C dir, -c k=v, --no-pager, ...) before the subcommand
GIT = r"\bgit(?:\s+(?:-[Cc]\s+\S+|--?[\w-]+(?:=\S+)?))*\s+"
GH = r"\bgh(?:\s+(?:-R|--repo)(?:=|\s+)\S+)*\s+"
HARNESS = r"(\.claude/|\.githooks/|\.github/|scripts/ci\.sh|pyproject\.toml|conftest\.py|\.git/)"
AZ_VERBS = (
    r"(create|delete|update|deploy|up|purge|start|restart|stop|scale|assign|import|upload|add|"
    r"remove|regenerate|renew|invoke|run|build|push|enable|disable|restore|recover|approve|"
    r"reject|apply|set)(-[\w-]+)?(?=\s|$)"
)

DENY = [
    (GIT + r"push\b.*\s(--force(-with-lease)?|-\w*f\w*)(\s|$)", "force push rewrites history"),
    (GIT + r"push\b.*[\s:+](main|master)(\s|$)", "push to main, go through a PR"),
    (r"(?<![\w.-])\.env(\.[\w-]+)*(?![\w.-])", "reading secrets from .env"),
    (GIT + r"push\b.*\s--no-v\w*", "skipping the judge"),
    (
        GIT + r"(commit|merge|rebase|am|cherry-pick|revert)\b.*\s(--no-v\w*|-[a-zA-Z]*n[a-zA-Z]*)"
        r"(\s|$)",
        "skipping the judge",
    ),
    (r"(?i:core\.hooksPath)", "changing where git hooks live disables the judge"),
    (GIT + r"push\b", "only the owner pushes, from a terminal outside Claude"),
]

ASK = [
    (
        GH + r"(repo|pr|release|gist|secret|variable|workflow)\s+"
        r"(create|edit|delete|rename|merge|upload|set|archive|close|reopen|ready|enable|disable)\b",
        "changes something on GitHub",
    ),
    (
        r"\bgh\s+api\b.*(\s(-X|--method)[=\s]*(?i:post|put|patch|delete)\b)",
        "changes GitHub via API",
    ),
    (r"\bgh\s+api\b.*\s(-f|-F|--field|--raw-field|--input)(\s|=)", "changes GitHub via API"),
    (r"\bdocker\s+push\b", "push publishes an image"),
    (r"\bazd\s+(up|provision|deploy|down)\b", "creates, changes or deletes Azure resources"),
    (
        r"\baz\s+rest\b.*\s(-m|--method)[=\s]+(?i:put|post|patch|delete)\b",
        "changes Azure resources",
    ),
    (r"\baz\s+rest\b.*\s(-b|--body)(\s|=)", "changes Azure resources"),
    (
        r"\baz\b.*(\bkeys\s+list\b|\bsecret\s+show\b|show-connection-string|\bcredential\s+show\b"
        r"|get-access-token|list-keys|list-secrets|list-credentials)",
        "prints secrets; prefer keyless Entra ID auth",
    ),
    (
        r"\baz\s+(?!login\b|logout\b|account\s+set\b|config\s+set\b|extension\s+add\b)"
        r"(\S+\s+)*?" + AZ_VERBS,
        "creates or changes Azure resources (possibly billed)",
    ),
    (GIT + r"switch\b.*\s(-f|--force|--discard-changes|-C)(\s|$)", "may discard work"),
    (GIT + r"branch\b.*\s(-D|-f|--force|-M|-C|--delete)(\s|$)", "deletes or moves a branch"),
    (GIT + r"reset\b.*\s--hard\b", "discards work"),
    (GIT + r"clean\b.*\s-\w*f", "deletes untracked files"),
    (GIT + r"checkout\b.*(\s--(\s|$)|\s(-f|--force)(\s|$)|\s\.(\s|$))", "may discard work"),
    (GIT + r"(restore|update-ref|filter-branch|filter-repo)\b", "may discard work or history"),
    (GIT + r"(stash\s+(drop|clear)|reflog\s+expire)\b", "discards work"),
    (r">>?\s*['\"]?[^\s;&|]*" + HARNESS, "writes to the harness"),
    (
        r"(\bsed\s+-\w*i|\btee\b|\bmv\b|\brm\b|\bchmod\b|\btruncate\b|\bln\b|\bperl\s+-\w*i)"
        r".*" + HARNESS,
        "writes to the harness",
    ),
]
REDIRECT = r"(\d*|&)>>?|<"


def segments(command: str) -> list[str]:
    return [s.strip() for s in re.split(r"&&|\|\||[;|\n]", command) if s.strip()]


def dangerous_rm(segment: str) -> bool:
    """Recursive rm of /, home, the project, its parents, or a bare wildcard."""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        tokens = segment.split()
    if "rm" not in tokens:
        return False
    args = tokens[tokens.index("rm") + 1 :]
    flags = [a for a in args if a.startswith("-")]
    recursive = any(
        f == "--recursive" or (not f.startswith("--") and "r" in f.lower()) for f in flags
    )
    if not recursive:
        return False
    project = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    for target in (a for a in args if not a.startswith("-")):
        if target in {"/", "/*", ".", "./", "..", "*", "./*"} or target.startswith(
            ("~", "$HOME", "../")
        ):
            return True
        resolved = Path(target).resolve() if target.startswith("/") else None
        if resolved is not None and (resolved == project or resolved in project.parents):
            return True
    return False


def copy_into_harness(segment: str) -> bool:
    """`cp` writes only to its destination, so copying a harness file out is not a write.

    Anything the destination cannot be read from for certain (no parse, several `cp`, `-t`,
    a variable, glob or `~` in the destination) still counts as a write.
    """
    if not re.search(r"\bcp\b.*" + HARNESS, segment):
        return False
    try:
        tokens = shlex.split(segment)
    except ValueError:
        return True
    starts = [i for i, t in enumerate(tokens) if os.path.basename(t) == "cp"]
    if len(starts) != 1:
        return True
    operands, options_done, skip = [], False, False
    for token in tokens[starts[0] + 1 :]:
        if skip:
            skip = False
        elif re.fullmatch(REDIRECT, token):
            skip = True
        elif re.match(REDIRECT, token):
            continue
        elif not options_done and token == "--":
            options_done = True
        elif not options_done and token.startswith("-"):
            # -t / --target-directory (or any abbreviation of it) names the destination first
            if token.startswith("--t") or re.fullmatch(r"-[^-]*t.*", token):
                return True
            # -S / --suffix takes the next token as its value
            skip = bool(re.fullmatch(r"-[^-]*S|--su[a-z]*", token))
        else:
            operands.append(token)
    if len(operands) < 2:
        return True
    return bool(re.search(HARNESS + r"|[$`*?\[{~]", operands[-1]))


def merge_into_main(command: str) -> bool:
    if not re.search(GIT + r"merge\b", command):
        return False
    if re.search(GIT + r"(switch|checkout)\s+(main|master)\b", command):
        return True
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=os.environ.get("CLAUDE_PROJECT_DIR") or None,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return True
    return branch in {"main", "master", ""}


def decide(command: str) -> tuple[str, str]:
    for segment in segments(command):
        if dangerous_rm(segment):
            return "deny", "recursive delete of root, home or the project"
        for pattern, reason in DENY:
            if re.search(pattern, segment):
                return "deny", reason
    if merge_into_main(command):
        return "ask", "only the owner merges into main"
    for segment in segments(command):
        for pattern, reason in ASK:
            if re.search(pattern, segment):
                return "ask", reason
        if copy_into_harness(segment):
            return "ask", "writes to the harness"
    return "allow", ""


def main() -> None:
    command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    if not isinstance(command, str):
        raise TypeError("command is not a string")
    decision, reason = decide(command)
    if decision == "deny":
        print(f"Blocked: {reason}. Propose a safer approach.", file=sys.stderr)
        sys.exit(2)
    if decision == "ask":
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": f"Owner OK required: {reason}.",
            }
        }
        print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # fail closed
        print(f"Blocked: guard.py failed ({exc!r}). Fix the guard first.", file=sys.stderr)
        sys.exit(2)
