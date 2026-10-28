#!/usr/bin/env python3
"""Picks the tests the Stop hook runs for the changed files (owner decision, 21 Oct).

Reads changed paths (relative to the repo root, one per line) from stdin and prints the test
files to run, one per line. Prints nothing when every test has to run: a `conftest.py` changed,
or a changed file has no test of its own. A file's tests are the changed test file itself, or the
test files that import it (a `src/` module), import it as a helper (`tests/*.py`) or name it
(any other file, e.g. a hook or `league.json`); helpers in `tests/` are followed one hop. A
Markdown file outside `src/` and `tests/` (a skill, an agent, a doc) runs the tests that name it
and the tests that search every tracked file (`EVERY_FILE`), and no more (owner decision 27 Oct):
text runs no code.

With `--follow-imports` (the pre-commit hook, owner decision 27 Oct) a changed module in `src/`
also brings the tests of every module in `src/` that imports it, at any depth; such an importer
without tests of its own adds none (only a changed file without tests makes all tests run).
Without it (the Stop hook) imports between the modules in `src/` are not followed. The full
suite runs in GitHub CI and before a merge into main or a deploy (`scripts/ci.sh`).
"""

import re
import sys
from pathlib import Path

# the tests that search every tracked file (Microsoft's texts, the local copies' names)
EVERY_FILE = ("tests/test_public_repo.py",)


def is_document(path: str) -> bool:
    """A Markdown file outside `src/` and `tests/`: nothing imports or loads it unnamed."""
    p = Path(path)
    return p.suffix == ".md" and p.parts[0] not in ("src", "tests")


def patterns(path: str) -> list[re.Pattern[str]]:
    """Regexes that find a test or helper depending on the file at `path`."""
    p = Path(path)
    if p.suffix != ".py":
        return [re.compile(re.escape(p.name))]
    if p.parts[0] == "src":
        parts = list(p.with_suffix("").parts[1:])
        if parts[-1] == "__init__":
            parts.pop()
        dotted = re.escape(".".join(parts))
        found = [re.compile(rf"\b{dotted}\b")]
        if len(parts) > 1:
            package, name = re.escape(".".join(parts[:-1])), re.escape(parts[-1])
            found.append(re.compile(rf"from {package} import (\([^)]*|[^\n]*)\b{name}\b"))
        return found
    if p.parts[0] == "tests":
        return [re.compile(rf"^\s*(from|import) {re.escape(p.stem)}\b", re.MULTILINE)]
    return [re.compile(re.escape(p.name))]


def importers(changed: list[str], root: Path) -> list[str]:
    """The modules in `src/` that import a changed one, at any depth, sorted; not `changed`."""
    sources = {
        f.relative_to(root).as_posix(): f.read_text(encoding="utf-8")
        for f in sorted((root / "src").rglob("*.py"))
    }
    seen = set(changed)
    queue = [path for path in changed if path in sources]
    while queue:
        found = patterns(queue.pop())
        for name, text in sources.items():
            if name not in seen and any(f.search(text) for f in found):
                seen.add(name)
                queue.append(name)
    return sorted(seen - set(changed))


def select(changed: list[str], root: Path, follow_imports: bool = False) -> list[str]:
    """Test files to run for `changed`, sorted; empty means all tests."""
    files = {
        f.relative_to(root).as_posix(): f.read_text(encoding="utf-8")
        for f in sorted((root / "tests").rglob("*.py"))
    }
    tests = {name: text for name, text in files.items() if Path(name).name.startswith("test_")}
    helpers = {
        name: text
        for name, text in files.items()
        if name not in tests and Path(name).name != "conftest.py"
    }

    def users(found: list[re.Pattern[str]], pool: dict[str, str]) -> set[str]:
        return {name for name, text in pool.items() if any(f.search(text) for f in found)}

    picked: set[str] = set()
    for path in changed:
        name = Path(path).name
        if name == "conftest.py":
            return []
        if path in tests:
            picked.add(path)
            continue
        if name.startswith("test_") and name.endswith(".py") and not (root / path).exists():
            continue  # a deleted test file: nothing left to run for it
        found = patterns(path)
        own = users(found, tests)
        for helper in users(found, helpers) - {path}:
            own |= users(patterns(helper), tests)
        if is_document(path):
            own |= {test for test in EVERY_FILE if test in tests}
        if not own:
            return []
        picked |= own
    if follow_imports:
        for module in importers(changed, root):
            picked |= users(patterns(module), tests)
    return sorted(picked)


if __name__ == "__main__":
    lines = [line.strip() for line in sys.stdin if line.strip()]
    print("\n".join(select(lines, Path.cwd(), "--follow-imports" in sys.argv[1:])))
