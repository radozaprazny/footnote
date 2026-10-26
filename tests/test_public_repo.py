"""The public repository holds no copy of Microsoft's texts: the hackathon's Official Rules and its
resource page stay local, gitignored, so a squashed commit of the repo does not publish them."""

import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
# the private repository's last commit that tracked both texts: where a local copy is missing, the
# sentences below are checked against it (the public repository has no such commit)
LAST_TRACKED = "5eb247eb1a1ee04442f1d308e297fda613aaa90f"
# sentences of each text, verbatim: the opening paragraph, the challenge (4.1) and our category's
# prize, so a copy of either file or a paste of those parts fails (a quote of another sentence does
# not); split so that this file does not hold them
LOCAL_ONLY = {
    "docs/RULES.md": (
        "NO PURCHASE OR PAYMENT " + "NECESSARY TO ENTER OR WIN",
        "Football stories do not start " + "and end with the scoreline",
        "Best demonstration of purposeful " + "multi-agent collaboration",
    ),
    "docs/resource-playlists.md": ("These AI Skills Navigator " + "playlists are designed",),
}
SENTENCES = [(path, sentence) for path, found in LOCAL_ONLY.items() for sentence in found]
# the only tracked files that may name a local copy's path
NAME_THEM = {".gitignore", "CLAUDE.md", "PROGRESS.md", "tests/test_public_repo.py"}


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)


def tracked_with(text: str) -> set[str]:
    """Tracked files whose staged content holds `text`: the index, which CI checks out and the
    pre-commit hook is about to commit."""
    found = git("grep", "--cached", "-F", "-l", "-e", text)
    assert found.returncode in (0, 1), found.stderr  # 1: no file holds it
    return set(found.stdout.splitlines())


def text_of(path: str) -> str:
    """The local copy, else the text at LAST_TRACKED; skipped only where that commit is missing (CI,
    the public repository), so any other failure of the fallback fails."""
    if (REPO / path).exists():
        return (REPO / path).read_text(encoding="utf-8")
    if git("cat-file", "-e", f"{LAST_TRACKED}^{{commit}}").returncode != 0:
        pytest.skip(f"no copy of {path} here")
    shown = git("show", f"{LAST_TRACKED}:{path}")
    assert shown.returncode == 0, shown.stderr
    return shown.stdout


def test_the_search_finds_tracked_text():
    assert "README.md" in tracked_with("Footnote")
    assert tracked_with("Footnote" + " is written nowhere") == set()


@pytest.mark.parametrize(("path", "sentence"), SENTENCES)
def test_no_tracked_file_holds_a_microsoft_text(path, sentence):
    assert tracked_with(sentence) == set(), path


@pytest.mark.parametrize("path", LOCAL_ONLY)
def test_only_a_few_files_name_a_local_copy(path):
    naming = tracked_with(path)
    assert "CLAUDE.md" in naming  # how to restore the copy
    assert naming <= NAME_THEM


@pytest.mark.parametrize("path", LOCAL_ONLY)
def test_a_local_copy_is_ignored(path):
    assert git("check-ignore", "-q", "--no-index", path).returncode == 0


@pytest.mark.parametrize("path", ["docs/deploy.md", "docs/submission.md", "docs/new.md"])
def test_the_other_docs_are_not(path):
    assert git("check-ignore", "-q", "--no-index", path).returncode == 1


@pytest.mark.parametrize(("path", "sentence"), SENTENCES)
def test_each_sentence_is_in_its_text(path, sentence):
    """The sentences the tests above look for are the texts' own."""
    assert sentence in text_of(path)
