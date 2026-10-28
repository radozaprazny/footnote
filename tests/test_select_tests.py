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
        "tests/test_public_repo.py": 'git("grep", "--cached", "-F", "-l", "-e", text)\n',
        "tests/test_guide.py": 'REPO / "docs" / "guide.md"\n',
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
        # a document runs the tests that name it and those that search every tracked file
        (["docs/notes.md"], ["tests/test_public_repo.py"]),
        ([".claude/agents/helper.md"], ["tests/test_public_repo.py"]),
        (["README.md"], ["tests/test_public_repo.py"]),
        (["docs/guide.md"], ["tests/test_guide.py", "tests/test_public_repo.py"]),
        (
            ["docs/notes.md", "src/matchlens/cli.py"],
            ["tests/test_cli.py", "tests/test_public_repo.py"],
        ),
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
        # Markdown in src/ or tests/ may be data, and a file only named like a document is not
        ["src/matchlens/notes.md"],
        ["tests/notes.md"],
        ["docs/notes.txt"],
        ["docs/notes.md.orig"],
        ["docs/notes.md", "src/matchlens/league.py"],
    ],
)
def test_runs_all_tests_when_a_change_has_no_test_of_its_own(
    repo: Path, changed: list[str]
) -> None:
    assert select_tests.select(changed, repo) == []


def test_a_document_runs_all_tests_without_a_test_that_searches_every_file(repo: Path) -> None:
    (repo / "tests/test_public_repo.py").unlink()
    assert select_tests.select(["docs/notes.md"], repo) == []
    assert select_tests.select(["docs/guide.md"], repo) == ["tests/test_guide.py"]


def test_the_real_repo_has_the_tests_that_search_every_file() -> None:
    for name in select_tests.EVERY_FILE:
        assert "--cached" in (ROOT / name).read_text(encoding="utf-8"), name


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


def make_hook_repo(tmp_path: Path, lock: str = "") -> Path:
    """A git repo with two modules, data and their tests, and `lock` as its uv.lock if given;
    `uv` is a fake that logs its args."""
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
    if lock:
        files["uv.lock"] = lock
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
        '[ "$2" = pytest ] || exit 0\n'
        'case "$*" in *"not serial"*) exit "${PARALLEL_EXIT:-0}";;\n'
        '  *serial*) exit "${SERIAL_EXIT:-0}";; esac\n'
        'exit "${PYTEST_EXIT:-0}"\n'
    )
    fake.chmod(0o755)
    return repo


@pytest.fixture
def hook_repo(tmp_path: Path) -> Path:
    return make_hook_repo(tmp_path)


def run_hook_calls(
    repo: Path, pytest_exit: int = 0, parallel: int = 0, serial: int = 0
) -> tuple[subprocess.CompletedProcess, list[list[str]]]:
    """Runs verify.sh on `repo`; returns the result and the arguments of each pytest call. One
    run on one process exits with `pytest_exit`, the run on workers with `parallel` and the
    serial one after it with `serial`."""
    log = repo.parent / "uv.log"
    env = {
        **outside_git(),
        "PATH": f"{repo.parent / 'bin'}:{os.environ['PATH']}",
        "CLAUDE_PROJECT_DIR": str(repo),
        "UV_LOG": str(log),
        "PYTEST_EXIT": str(pytest_exit),
        "PARALLEL_EXIT": str(parallel),
        "SERIAL_EXIT": str(serial),
    }
    result = subprocess.run(
        [str(VERIFY)],
        input=json.dumps({"cwd": str(repo)}),
        capture_output=True,
        text=True,
        env=env,
    )
    calls = log.read_text().split("--\n") if log.exists() else []
    return result, [c.splitlines()[2:] for c in calls if c.startswith("run\npytest\n")]


def run_hook(repo: Path, pytest_exit: int = 0) -> tuple[subprocess.CompletedProcess, list[str]]:
    """Runs verify.sh on `repo`; returns the result and the arguments of the pytest call."""
    result, pytest_args = run_hook_calls(repo, pytest_exit)
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


XDIST_LOCK = 'version = 1\n\n[[package]]\nname = "pytest-xdist"\nversion = "3.8.0"\n'
ON_WORKERS = ["-q", "-x", "-n", "6", "-m", "not serial"]
SERIAL_ONLY = ["-q", "-x", "-m", "serial"]


@pytest.fixture
def xdist_repo(tmp_path: Path) -> Path:
    return make_hook_repo(tmp_path, lock=XDIST_LOCK)


def test_hook_runs_the_picked_tests_on_6_workers_then_the_serial_ones(xdist_repo: Path) -> None:
    (xdist_repo / "src/matchlens/cli.py").write_text("def main() -> int: ...\n")
    result, calls = run_hook_calls(xdist_repo, serial=5)
    assert result.returncode == 0, result.stderr
    assert calls == [[*ON_WORKERS, "tests/test_cli.py"], [*SERIAL_ONLY, "tests/test_cli.py"]]


def test_hook_with_xdist_runs_all_tests_in_both_for_a_change_without_tests(
    xdist_repo: Path,
) -> None:
    (xdist_repo / "src/matchlens/stats/other.py").write_text("X = 1\n")
    result, calls = run_hook_calls(xdist_repo)
    assert result.returncode == 0, result.stderr
    assert calls == [ON_WORKERS, SERIAL_ONLY]


@pytest.mark.parametrize(
    ("parallel", "serial", "code"),
    [(0, 0, 0), (0, 5, 0), (5, 0, 0), (5, 5, 2), (0, 1, 2), (5, 1, 2), (0, 2, 2)],
)
def test_both_runs_decide_the_hooks_verdict(
    xdist_repo: Path, parallel: int, serial: int, code: int
) -> None:
    (xdist_repo / "src/matchlens/cli.py").write_text("def main() -> int: ...\n")
    result, calls = run_hook_calls(xdist_repo, parallel=parallel, serial=serial)
    assert result.returncode == code, result.stderr
    assert ("attempt 1/3" in result.stderr) == (code == 2)
    assert len(calls) == 2


@pytest.mark.parametrize("parallel", [1, 2, 4])
def test_a_red_run_on_workers_keeps_claude_working_without_the_serial_one(
    xdist_repo: Path, parallel: int
) -> None:
    (xdist_repo / "src/matchlens/cli.py").write_text("def main() -> int: ...\n")
    result, calls = run_hook_calls(xdist_repo, parallel=parallel)
    assert result.returncode == 2
    assert "attempt 1/3" in result.stderr
    assert calls == [[*ON_WORKERS, "tests/test_cli.py"]]


@pytest.mark.parametrize(
    "lock",
    [
        "",
        'version = 1\n\n[[package]]\nname = "pytest"\n',
        'dependencies = [\n    { name = "pytest-xdist" },\n]\n',
        '[[package]]\nname = "pytest-xdist-extra"\n',
        '[[package]]\nname = "pytest-xdis"\n',
    ],
)
def test_a_tree_whose_lock_has_no_xdist_runs_on_one_process(tmp_path: Path, lock: str) -> None:
    repo = make_hook_repo(tmp_path, lock=lock)
    (repo / "src/matchlens/cli.py").write_text("def main() -> int: ...\n")
    result, calls = run_hook_calls(repo, pytest_exit=1, parallel=0, serial=0)
    assert result.returncode == 2
    assert calls == [["-q", "-x", "tests/test_cli.py"]]


def index_lock(tree: Path) -> Path:
    """The lock `git commit` holds on `tree`'s index while its pre-commit hook runs."""
    out = subprocess.run(
        ["git", "-C", str(tree), "rev-parse", "--path-format=absolute", "--git-path", "index.lock"],
        check=True,
        capture_output=True,
        text=True,
        env=outside_git(),
    )
    return Path(out.stdout.strip())


def test_hook_leaves_the_tests_to_a_commit_in_progress(hook_repo: Path) -> None:
    (hook_repo / "src/matchlens/cli.py").write_text("def main() -> int: ...\n")
    lock = index_lock(hook_repo)
    lock.touch()
    result, _ = run_hook(hook_repo, pytest_exit=1)
    assert result.returncode == 0, result.stderr
    assert not (hook_repo.parent / "uv.log").exists()  # neither the lint nor the tests
    lock.unlink()
    result, pytest_args = run_hook(hook_repo, pytest_exit=1)
    assert result.returncode == 2
    assert pytest_args == ["-q", "-x", "tests/test_cli.py"]


def test_a_commit_in_another_tree_leaves_the_hook_running(hook_repo: Path) -> None:
    """A worktree has its own index lock: a commit in the main tree tests none of its changes."""
    tree = hook_repo.parent / "tree"
    subprocess.run(
        ["git", "-C", str(hook_repo), "worktree", "add", "-q", str(tree)],
        check=True,
        env=outside_git(),
    )
    (tree / "src/matchlens/cli.py").write_text("def main() -> int: ...\n")
    index_lock(tree).touch()
    result, _ = run_hook(tree)
    assert result.returncode == 0, result.stderr
    assert not (tree.parent / "uv.log").exists()
    index_lock(tree).unlink()
    index_lock(hook_repo).touch()
    result, pytest_args = run_hook(tree)
    assert result.returncode == 0, result.stderr
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


@pytest.fixture
def chain(tmp_path: Path) -> Path:
    """a <- b <- c <- d in src/ (each imports the one before, three spellings); e alone."""
    files = {
        "src/matchlens/a.py": "",
        "src/matchlens/b.py": "from matchlens.a import x\n",
        "src/matchlens/c.py": "from matchlens import b\n",
        "src/matchlens/d.py": "import matchlens.c\n",
        "src/matchlens/e.py": "",
        "tests/test_a.py": "from matchlens.a import x\n",
        "tests/test_c.py": "from matchlens.c import y\n",
        "tests/test_e.py": "from matchlens.e import z\n",
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    return tmp_path


def test_the_importers_of_a_module_at_any_depth(chain: Path):
    assert select_tests.importers(["src/matchlens/a.py"], chain) == [
        "src/matchlens/b.py",
        "src/matchlens/c.py",
        "src/matchlens/d.py",
    ]
    assert select_tests.importers(["src/matchlens/c.py"], chain) == ["src/matchlens/d.py"]
    assert select_tests.importers(["src/matchlens/e.py"], chain) == []


def test_following_imports_adds_the_importers_tests(chain: Path):
    a = ["src/matchlens/a.py"]
    assert select_tests.select(a, chain) == ["tests/test_a.py"]
    # b and d have no tests of their own and add none; c's come through b
    assert select_tests.select(a, chain, follow_imports=True) == [
        "tests/test_a.py",
        "tests/test_c.py",
    ]
    assert select_tests.select(["src/matchlens/e.py"], chain, follow_imports=True) == [
        "tests/test_e.py"
    ]


def test_a_changed_module_without_tests_still_means_all_when_following(chain: Path):
    assert select_tests.select(["src/matchlens/b.py"], chain, follow_imports=True) == []


def test_the_script_follows_imports_only_when_asked(chain: Path):
    def run(*args: str) -> list[str]:
        out = subprocess.run(
            ["python3", str(SCRIPT), *args],
            input="src/matchlens/a.py\n",
            cwd=chain,
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.split()

    assert run() == ["tests/test_a.py"]
    assert run("--follow-imports") == ["tests/test_a.py", "tests/test_c.py"]
