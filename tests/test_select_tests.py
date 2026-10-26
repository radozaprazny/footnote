"""Tests for the Stop hook's test selection in .claude/hooks/select_tests.py."""

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".claude" / "hooks" / "select_tests.py"
VERIFY = ROOT / ".claude" / "hooks" / "verify.sh"
_spec = importlib.util.spec_from_file_location("select_tests", SCRIPT)
assert _spec and _spec.loader
select_tests = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(select_tests)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    files = {
        "tests/test_flow.py": "from matchlens.stats.flow import momentum\n",
        "tests/test_flows.py": "from matchlens.stats.flows import other\n",
        "tests/test_pkg.py": "from matchlens.stats import (\n    passing,\n    speed,\n)\n",
        "tests/test_cli.py": "from matchlens.cli import main\n",
        "tests/test_props.py": "from strategies import matches\n",
        "tests/test_hook.py": 'HOOK = ROOT / ".claude" / "hooks" / "guard.py"\n',
        "tests/test_gate.py": '("edit conftest.py", "ask")\n',
        "tests/test_near.py": "import strategies_x\n",
        "tests/test_real.py": "import real\n",
        "tests/test_league.py": 'files("matchlens") / "data" / "league.json"\n',
        "tests/unit/test_deep.py": "from matchlens.api import create_app\n",
        "tests/strategies.py": "from matchlens.events import Event\n",
        "tests/real.py": "from matchlens.facts import match_facts\n",
        "tests/conftest.py": "",
        "scripts/test_tool.py": "",
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    return tmp_path


@pytest.mark.parametrize(
    ("changed", "expected"),
    [
        # a changed test file runs itself
        (["tests/test_cli.py"], ["tests/test_cli.py"]),
        # a module runs the tests that import it, not one whose name only starts the same
        (["src/matchlens/stats/flow.py"], ["tests/test_flow.py"]),
        (["src/matchlens/stats/flows.py"], ["tests/test_flows.py"]),
        # `from package import (module, ...)` over several lines
        (["src/matchlens/stats/speed.py"], ["tests/test_pkg.py"]),
        # a package's __init__ runs every test that imports the package or a module in it
        (
            ["src/matchlens/stats/__init__.py"],
            ["tests/test_flow.py", "tests/test_flows.py", "tests/test_pkg.py"],
        ),
        # a helper runs the tests that import it (`from` or `import`, not a longer name); a
        # module runs, one hop through a helper, the tests of the helpers that import it
        (["tests/strategies.py"], ["tests/test_props.py"]),
        (["tests/real.py"], ["tests/test_real.py"]),
        (["src/matchlens/events.py"], ["tests/test_props.py"]),
        (["src/matchlens/facts.py"], ["tests/test_real.py"]),
        # the top package runs every test that names it, directly or through a helper
        (
            ["src/matchlens/__init__.py"],
            [
                "tests/test_cli.py",
                "tests/test_flow.py",
                "tests/test_flows.py",
                "tests/test_league.py",
                "tests/test_pkg.py",
                "tests/test_props.py",
                "tests/test_real.py",
                "tests/unit/test_deep.py",
            ],
        ),
        # data runs the tests that name it; a test in a subdirectory is a test, not deleted
        (["src/matchlens/data/league.json"], ["tests/test_league.py"]),
        (["src/matchlens/api.py"], ["tests/unit/test_deep.py"]),
        (
            ["tests/unit/test_deep.py", "src/matchlens/cli.py"],
            ["tests/test_cli.py", "tests/unit/test_deep.py"],
        ),
        # any other file runs the tests that name it
        ([".claude/hooks/guard.py"], ["tests/test_hook.py"]),
        # several files: the union
        (
            ["src/matchlens/cli.py", "src/matchlens/stats/flow.py"],
            ["tests/test_cli.py", "tests/test_flow.py"],
        ),
        # a deleted test file adds nothing, the other changes still pick theirs
        (["tests/test_gone.py", "src/matchlens/cli.py"], ["tests/test_cli.py"]),
    ],
)
def test_picks_the_tests_of_the_changed_files(
    repo: Path, changed: list[str], expected: list[str]
) -> None:
    assert select_tests.select(changed, repo) == expected


@pytest.mark.parametrize(
    "changed",
    [
        ["tests/conftest.py"],
        ["src/matchlens/cli.py", "tests/conftest.py"],
        # a conftest.py anywhere, even one a test names
        ["conftest.py"],
        # a file without a test of its own, alone or next to one with tests
        ["src/matchlens/league.py"],
        ["src/matchlens/cli.py", "src/matchlens/league.py"],
        ["scripts/tool.py"],
        # a test_*.py outside tests/ is not a deleted test
        ["scripts/test_tool.py", "src/matchlens/cli.py"],
        ["src/matchlens/data/other.json"],
        ["pyproject.toml"],
        # only deleted test files: nothing picked, so all tests
        ["tests/test_gone.py"],
    ],
)
def test_runs_all_tests_when_a_change_has_no_test_of_its_own(
    repo: Path, changed: list[str]
) -> None:
    assert select_tests.select(changed, repo) == []


def test_script_reads_stdin_and_prints_one_test_per_line(repo: Path) -> None:
    result = subprocess.run(
        ["python3", str(SCRIPT)],
        input="src/matchlens/cli.py\n\nsrc/matchlens/stats/flow.py\n",
        capture_output=True,
        text=True,
        cwd=repo,
        check=True,
    )
    assert result.stdout.splitlines() == ["tests/test_cli.py", "tests/test_flow.py"]


def test_real_repo_flow_module_picks_its_tests() -> None:
    picked = select_tests.select(["src/matchlens/stats/flow.py"], ROOT)
    assert {"tests/test_flow.py", "tests/test_facts.py"} <= set(picked)
    assert "tests/test_league.py" not in picked


def outside_git() -> dict[str, str]:
    """The environment without GIT_*: the pre-commit hook sets GIT_DIR and GIT_INDEX_FILE, and
    an inherited one sends git in a temporary repo to the real one (21 Oct it committed there
    and set core.bare)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def make_hook_repo(tmp_path: Path) -> Path:
    """A git repo with two modules, data and their tests; `uv` is a fake that logs its args."""
    repo = tmp_path / "repo"
    files = {
        "src/matchlens/stats/speed.py": "TOP = 1\n",
        "src/matchlens/cli.py": "def main() -> None: ...\n",
        "src/matchlens/data/league.json": "{}\n",
        "tests/test_speed.py": "from matchlens.stats.speed import TOP\n",
        "tests/test_facts.py": "from matchlens.stats.speed import TOP\n",
        "tests/test_cli.py": "from matchlens.cli import main\n",
        "tests/test_league.py": '"league.json"\n',
        "README.md": "hook repo\n",
    }
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text)
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.org"]
    env = outside_git()
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    subprocess.run([*git, "add", "."], check=True, env=env)
    subprocess.run([*git, "commit", "-qm", "base"], check=True, env=env)
    fake = tmp_path / "bin" / "uv"
    fake.parent.mkdir()
    fake.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$@" "--" >> "$UV_LOG"\n'
        '[ "$2" = pytest ] && exit "${PYTEST_EXIT:-0}"\nexit 0\n'
    )
    fake.chmod(0o755)
    return repo


@pytest.fixture
def hook_repo(tmp_path: Path) -> Path:
    return make_hook_repo(tmp_path)


def run_hook(repo: Path, pytest_exit: int = 0) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Runs verify.sh on `repo`; returns the result and the arguments of the pytest call."""
    log = repo.parent / "uv.log"
    env = {
        **outside_git(),
        "PATH": f"{repo.parent / 'bin'}:{os.environ['PATH']}",
        "CLAUDE_PROJECT_DIR": str(repo),
        "UV_LOG": str(log),
        "PYTEST_EXIT": str(pytest_exit),
    }
    result = subprocess.run(
        [str(VERIFY)],
        input=json.dumps({"cwd": str(repo)}),
        capture_output=True,
        text=True,
        env=env,
    )
    calls = log.read_text().split("--\n") if log.exists() else []
    pytest_args = [c.splitlines()[2:] for c in calls if c.startswith("run\npytest\n")]
    assert len(pytest_args) <= 1
    return result, (pytest_args[0] if pytest_args else [])


def test_hook_skips_a_change_without_python(hook_repo: Path) -> None:
    (hook_repo / "README.md").write_text("changed\n")
    result, _ = run_hook(hook_repo)
    assert result.returncode == 0
    assert not (hook_repo.parent / "uv.log").exists()


def test_hook_runs_the_importers_of_a_moved_module(hook_repo: Path) -> None:
    moved = ["src/matchlens/stats/speed.py", "src/matchlens/stats/motion.py"]
    subprocess.run(["git", "-C", str(hook_repo), "mv", *moved], check=True, env=outside_git())
    (hook_repo / "tests/test_speed.py").write_text("from matchlens.stats.motion import TOP\n")
    result, pytest_args = run_hook(hook_repo)
    assert result.returncode == 0, result.stderr
    assert pytest_args == ["-q", "-x", "tests/test_facts.py", "tests/test_speed.py"]


def test_hook_runs_the_tests_of_changed_data_one_argument_per_file(hook_repo: Path) -> None:
    (hook_repo / "src/matchlens/data/league.json").write_text('{"clubs": []}\n')
    (hook_repo / "src/matchlens/cli.py").write_text("def main() -> int: ...\n")
    (hook_repo / "tests/test_new feature.py").write_text("X = 1\n")
    result, pytest_args = run_hook(hook_repo)
    assert result.returncode == 0, result.stderr
    assert pytest_args == [
        "-q",
        "-x",
        "tests/test_cli.py",
        "tests/test_league.py",
        "tests/test_new feature.py",
    ]


def test_hook_runs_all_tests_for_a_change_without_tests(hook_repo: Path) -> None:
    (hook_repo / "src/matchlens/stats/other.py").write_text("X = 1\n")
    result, pytest_args = run_hook(hook_repo)
    assert result.returncode == 0, result.stderr
    assert pytest_args == ["-q", "-x"]


def test_hook_keeps_claude_working_when_a_picked_test_fails(hook_repo: Path) -> None:
    (hook_repo / "src/matchlens/cli.py").write_text("def main() -> int: ...\n")
    result, pytest_args = run_hook(hook_repo, pytest_exit=1)
    assert result.returncode == 2
    assert "attempt 1/3" in result.stderr
    assert pytest_args == ["-q", "-x", "tests/test_cli.py"]


def test_hook_tests_leave_the_repo_of_a_git_hook_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As in the pre-commit hook: GIT_DIR and GIT_INDEX_FILE point at another repo."""
    decoy = tmp_path / "decoy"
    subprocess.run(["git", "init", "-q", str(decoy)], check=True, env=outside_git())
    git_dir = decoy / ".git"
    monkeypatch.setenv("GIT_DIR", str(git_dir))
    monkeypatch.setenv("GIT_INDEX_FILE", str(git_dir / "index"))
    repo = make_hook_repo(tmp_path / "inner")
    (repo / "src/matchlens/cli.py").write_text("def main() -> int: ...\n")
    result, pytest_args = run_hook(repo)
    assert pytest_args == ["-q", "-x", "tests/test_cli.py"], result.stderr
    check = subprocess.run(
        ["git", "-C", str(decoy), "rev-parse", "--verify", "-q", "HEAD"],
        capture_output=True,
        env=outside_git(),
    )
    assert check.returncode != 0  # still no commit in the decoy
    bare = subprocess.run(
        ["git", "-C", str(decoy), "config", "core.bare"],
        capture_output=True,
        text=True,
        env=outside_git(),
    )
    assert bare.stdout.strip() == "false"
    assert not (git_dir / "index").exists()
