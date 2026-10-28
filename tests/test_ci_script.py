"""scripts/ci.sh runs the tests on 6 workers, then those marked serial on their own (27 Oct)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# the pre-commit hook runs HEAD's ci.sh in its copy and leaves the staged one in CI_STAGED, so
# that a changed ci.sh is what these tests test
CI = Path(os.environ.get("CI_STAGED") or ROOT / "scripts" / "ci.sh")
PARALLEL = ["run", "pytest", "-q", "-n", "6", "-m", "not serial"]
SERIAL = ["run", "pytest", "-q", "-m", "serial"]


def run_ci(
    tmp_path: Path, parallel: int, serial: int, *args: str, stdin: str = "", picked: str = ""
) -> tuple[subprocess.CompletedProcess, list[list[str]]]:
    """Runs a copy of ci.sh with a fake `uv` that logs its arguments; pytest's two runs exit
    with `parallel` and `serial`. Returns the result and the pytest calls."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(CI, tmp_path / "scripts" / "ci.sh")
    log = tmp_path / "uv.log"
    fake = tmp_path / "bin" / "uv"
    fake.parent.mkdir()
    fake.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" "--" >> "$UV_LOG"\n'
        '[ "$2" = pytest ] || exit 0\n'
        'case "$*" in *"not serial"*) exit "$PARALLEL_EXIT";;\n'
        '  *serial*) exit "$SERIAL_EXIT";; esac\n'
        "exit 0\n"
    )
    fake.chmod(0o755)
    select = tmp_path / "select.py"
    select.write_text(f"print({picked!r})\n")
    env = {
        **{k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        "PATH": f"{fake.parent}:{os.environ['PATH']}",
        "UV_LOG": str(log),
        "PARALLEL_EXIT": str(parallel),
        "SERIAL_EXIT": str(serial),
        "CI_SELECT": str(select),
    }
    result = subprocess.run(
        ["bash", str(tmp_path / "scripts" / "ci.sh"), *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
    )
    calls = [c.splitlines() for c in log.read_text().split("--\n") if c] if log.exists() else []
    return result, [c for c in calls if c[:2] == ["run", "pytest"]]


@pytest.mark.parametrize(
    ("parallel", "serial", "code"),
    [
        (0, 0, 0),
        # 5: none of the tests is of that kind, so the other run decides
        (5, 0, 0),
        (0, 5, 0),
        # nothing ran at all
        (5, 5, 5),
        (0, 1, 1),
        (5, 1, 1),
    ],
)
def test_both_runs_decide_the_verdict(tmp_path: Path, parallel: int, serial: int, code: int):
    result, calls = run_ci(tmp_path, parallel, serial)
    assert result.returncode == code, result.stderr
    assert calls == [PARALLEL, SERIAL]


@pytest.mark.parametrize("parallel", [1, 2, 4])
def test_a_red_parallel_run_ends_ci_before_the_serial_one(tmp_path: Path, parallel: int):
    result, calls = run_ci(tmp_path, parallel, 0)
    assert result.returncode == parallel, result.stderr
    assert calls == [PARALLEL]


def test_the_changed_files_tests_go_to_both_runs(tmp_path: Path):
    picked = "tests/test_a.py\ntests/test_b.py"
    result, calls = run_ci(tmp_path, 0, 5, "--changed", stdin="src/a.py\nsrc/b.py\n", picked=picked)
    assert result.returncode == 0, result.stderr
    files = ["tests/test_a.py", "tests/test_b.py"]
    assert calls == [PARALLEL + files, SERIAL + files]


def test_an_empty_selection_runs_every_test(tmp_path: Path):
    result, calls = run_ci(tmp_path, 0, 0, "--changed", stdin="pyproject.toml\n")
    assert result.returncode == 0, result.stderr
    assert "every test" in result.stderr
    assert calls == [PARALLEL, SERIAL]


@pytest.mark.parametrize(("parallel", "serial"), [(1, 0), (0, 1), (5, 5)])
def test_a_red_selection_is_red(tmp_path: Path, parallel: int, serial: int):
    result, _ = run_ci(tmp_path, parallel, serial, "--changed", stdin="a\n", picked="t.py")
    assert result.returncode != 0
