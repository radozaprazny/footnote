"""The README is what a judge reads first: its link to the app, its commands and its paths must
be the repo's own, so a renamed option or a moved file fails here and not in front of a judge."""

import re
import shlex
from pathlib import Path

import pytest

from matchlens import cli
from matchlens import mcp as mcp_server

REPO = Path(__file__).resolve().parents[1]
README = (REPO / "README.md").read_text(encoding="utf-8")
APP_URL = r"https://[\w.-]+\.azurecontainerapps\.io/"
PLACEHOLDER = r"<[\w-]+>"  # such as <run-id>: a value the reader fills in


def shell_blocks() -> list[str]:
    """The README's code blocks without a language: the commands a reader types. A fence opens a
    block and the next fence closes it; a block in any language but the diagram's fails, so no
    command hides from the tests below."""
    blocks, lang, lines = [], None, []
    for line in README.splitlines():
        if line.startswith("```"):
            if lang is None:
                lang, lines = line[3:].strip(), []
                assert lang in {"", "mermaid"}, f"a code block in {lang}: write commands bare"
            else:
                if not lang:
                    blocks.append("\n".join(lines))
                lang = None
        elif lang is not None:
            lines.append(line)
    assert lang is None, "a code block is not closed"
    return blocks


def commands() -> list[list[str]]:
    """Every `uv run matchlens` command of the code blocks, as the CLI's arguments."""
    found = []
    for line in "\n".join(shell_blocks()).splitlines():
        words = shlex.split(line)
        while words and re.fullmatch(r"[A-Z_]+=\S*", words[0]):  # an environment variable
            words.pop(0)
        if words[:3] == ["uv", "run", "matchlens"]:
            found.append(words[3:])
    return found


def test_every_command_is_collected():
    """Each `uv run matchlens` of the code blocks is a command above: none slips the parser."""
    assert len(commands()) == "\n".join(shell_blocks()).count("uv run matchlens") >= 7


def test_the_readme_links_the_deployed_app():
    """One app URL, the runbook's."""
    runbook = (REPO / "docs" / "deploy.md").read_text(encoding="utf-8")
    assert set(re.findall(APP_URL, README)) == set(re.findall(APP_URL, runbook))
    assert len(set(re.findall(APP_URL, README))) == 1


def test_the_readme_shows_the_commands_a_judge_runs():
    """A demo run served locally, the agents without a model, and on Foundry over MCP."""
    shown = commands()
    assert ["serve", "--seed", "0", "--run", "demo/runs/m0"] in shown
    assert any(c[0] == "explain" and "--fake" in c for c in shown)
    assert any(c[0] == "explain" and "--deployment" in c and "--mcp" in c for c in shown)
    assert any(c[0] == "mcp" for c in shown)


def test_the_commands_fit_together(monkeypatch, capsys):
    """A command that calls a model caps its requests; the agents on Foundry reach the facts
    server the README starts, at its address and for its match (the README's `mcp` command is
    run, with a stand-in for the server)."""
    shown = commands()
    for c in shown:
        if c[0] in {"explain", "recap", "translate"} and "--fake" not in c:
            assert "--max-calls" in c, c
    started = {}

    class Server:
        def run(self, transport):
            started["transport"] = transport

    def create_server(matches, host, port):
        started.update(host=host, port=port)
        return Server()

    monkeypatch.setattr(mcp_server, "create_server", create_server)
    (served,) = [c for c in shown if c[0] == "mcp"]
    assert cli.main(served) == 0
    banner = capsys.readouterr().err
    url = f"http://{started['host']}:{started['port']}/mcp"
    assert started["transport"] == "streamable-http"
    assert re.search(rf" over MCP on {re.escape(url)}$", banner, re.MULTILINE), banner
    agents = [c for c in shown if "--mcp" in c]
    assert agents
    for c in agents:
        assert c[c.index("--mcp") + 1] == url
        assert f" {c[1]} " in banner  # "facts of m7 over MCP on ..."


def test_the_measured_numbers_are_in_the_metrics():
    """Every number in the tables of "Measured results" stands in PROGRESS.md's Metrics."""
    progress = (REPO / "PROGRESS.md").read_text(encoding="utf-8")
    metrics = progress.split("## Metrics", 1)[1].split("\n## ", 1)[0]
    section = README.split("## Measured results", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| ") and "---" not in line]
    number = r"(?<![\d.])\d+(?:\.\d+)?(?![\d.])"  # a whole number, not a part of one
    numbers = {n for row in rows[1:] for n in re.findall(number, row)}
    assert {"28", "35", "76", "4.73", "18.7", "3.73"} <= numbers
    assert sorted(numbers - set(re.findall(number, metrics))) == []


@pytest.mark.parametrize("args", commands(), ids=" ".join)
def test_every_command_in_the_readme_parses(args):
    """The CLI accepts it as written, with a placeholder for a value the reader fills in."""
    filled = [re.sub(PLACEHOLDER, "x", a) for a in args]
    parsed = cli._parser().parse_args(filled)
    assert callable(parsed.run)


def test_every_path_the_readme_names_exists():
    """Relative links, the paths in backticks (with a slash or a file suffix) and the paths in
    the commands; a path with a placeholder must exist up to it, but a run directory under
    `runs/` named by a placeholder, which the commands above write, is exempt."""
    links = re.findall(r"\]\((?!https?://|#)([^)\s]+)\)", README)
    ticked = re.findall(r"`([^`\s]+)`", README)
    in_commands = [a for c in commands() for a in c]
    paths = {p.rstrip("/") for p in links} | {
        p.rstrip("/")
        for p in ticked + in_commands
        if ("/" in p or re.search(r"\.(md|py|sh|yaml|json|jsonl)$", p)) and "://" not in p
    }
    assert "LICENSE" in paths  # a link without a slash or a suffix counts too
    assert "demo/runs/m0" in paths and "runs/m7/<run-id>" in paths
    missing = []
    for path in sorted(paths):
        head = re.split(PLACEHOLDER, path)[0].rstrip("/")
        # a run directory the commands above write, named by a placeholder
        generated = head.split("/")[0] == "runs" and head != path
        if head and not generated and not (REPO / head).exists():
            missing.append(path)
    assert missing == []
