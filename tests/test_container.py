"""The container (M6): the wheel it installs carries the page and the league, the runs it replays
fit their matches with every narrative shown, and its command serves exactly those runs. The
image itself is built and smoke-tested by scripts/container.sh, not in CI."""

import argparse
import json
import re
import select
import shutil
import signal
import socket
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import httpx
import pytest
import real
from test_league import famous_surname_hits, real_club_hits

from matchlens import cli
from matchlens.explain.log import Role, read_handoffs
from matchlens.explain.state import ANALYST, Lang, Persona
from matchlens.explain.summary import summarize
from matchlens.render import moments, recap
from matchlens.render.moments import FAN_VIEW, NARRATIVE, match_overlay, moment_cues

# a stop timed against STOP_LIMIT_S and a warm-up against a deadline: alone, after the rest
pytestmark = pytest.mark.serial

REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / "demo" / "runs"
DEMO_RUNS = sorted((p for p in RUNS.iterdir() if p.is_dir()), key=lambda p: int(p.name[1:]))
DEMO_MODEL = "claude-sonnet-5-5"  # the demo replays the Sonnet 5.5 runs (owner, 23 Oct)
# M5's run of each match (item 2): `matchlens explain --persona fan`, then `matchlens recap` and
# `matchlens translate --lang sk` into the same directory
DEMO_FILES = {
    "handoffs.jsonl",
    "summary.json",
    "recap.jsonl",
    "recap.json",
    "translate.sk.jsonl",
    "translate.sk.json",
}


def test_the_wheel_carries_the_page_and_the_league(tmp_path):
    """The image installs the project as a wheel (`--no-editable`): the app reads its page and
    the league from the installed package, so every file of `web` and `data` must be in it."""
    uv = shutil.which("uv")
    assert uv, "uv is not on PATH"
    subprocess.run([uv, "build", "--wheel", "--out-dir", str(tmp_path), "-q"], cwd=REPO, check=True)
    (wheel,) = tmp_path.glob("matchlens-*.whl")
    packaged = set(zipfile.ZipFile(wheel).namelist())
    src = REPO / "src"
    wanted = {
        p.relative_to(src).as_posix()
        for folder in ("web", "data")
        for p in (src / "matchlens" / folder).rglob("*")
        if p.is_file()
    }
    assert {"matchlens/web/index.html", "matchlens/data/league.json"} <= wanted
    assert wanted <= packaged


@pytest.mark.parametrize("run", DEMO_RUNS, ids=lambda p: p.name)
def test_a_demo_run_fits_its_match_and_shows_every_narrative(run):
    """A demo run is a Sonnet 5.5 run of the match its folder names; replayed against today's
    generator and engine, the Guard lets out every narrative the run logged."""
    seed = int(re.fullmatch(r"m(\d+)", run.name)[1])
    handoffs = read_handoffs(run / "handoffs.jsonl")
    summary = json.loads((run / "summary.json").read_text())
    assert {h.case.match_id for h in handoffs} == {run.name} == {summary["match_id"]}
    assert summary["models"] == [DEMO_MODEL]
    assert summarize(handoffs).models == (DEMO_MODEL,)  # what the attempts record
    logged = sum(h.receiver is Role.RENDER and h.case.narrative is not None for h in handoffs)
    assert logged == summary["narratives"] > 0
    cues = moment_cues(real.match_v2(seed), handoffs)
    shown = sum(c.lines[0].startswith(f"{NARRATIVE} · ") for c in cues)
    assert shown == logged


def served(run: Path) -> list:
    """The handoffs of a demo run as `matchlens serve --run` reads them: the agents' run, its
    recap and its translations."""
    runs = cli._runs(argparse.Namespace(error=pytest.fail), [run])
    assert list(runs) == [run.name]
    return runs[run.name]


@pytest.mark.parametrize("run", DEMO_RUNS, ids=lambda p: p.name)
def test_a_demo_run_shows_every_fan_rendition_recap_and_slovak_translation(run):
    """M5 on the page: replayed as the image serves it, a demo run shows a fan rendition of
    every moment, the Recap Writer's recap and its fan recap, and a Slovak translation of every
    narrative, rendition and recap; nothing falls back to the engine's or the English text."""
    assert {p.name for p in run.iterdir()} == DEMO_FILES
    for name in ("summary.json", "recap.json", "translate.sk.json"):
        assert json.loads((run / name).read_text())["models"] == [DEMO_MODEL], name
    handoffs = served(run)
    models = {
        attempt.model
        for h in handoffs
        for rewriting in (h.case, *h.case.renditions, *h.case.translations)
        for attempt in rewriting.attempts
    }
    assert models == {DEMO_MODEL}
    overlay = match_overlay(real.match_v2(int(run.name[1:])), handoffs)
    cues = {c.cue_id.rpartition("/")[2]: c for c in overlay.cues if c.kind == "moment"}
    closed = [c for c in recap.closed_cases(handoffs).values() if not c.is_recap]
    assert len(closed) == json.loads((run / "summary.json").read_text())["moments"] > 0
    assert set(cues) == {c.moment_id for c in closed}  # a run of the whole match, every moment
    fan, sk = Persona.FAN.value, Lang.SK
    heads = {ANALYST: moments.LABELS[sk][NARRATIVE], fan: moments.LABELS[sk][FAN_VIEW]}
    for case in closed:
        cue = cues[case.moment_id]
        assert cue.rendition(fan).lines[0].startswith(f"{FAN_VIEW} · "), case.moment_id
        for persona, head in heads.items():
            line = cue.translated(persona, sk).lines[0]
            assert line.startswith(f"{head} · "), (case.moment_id, persona, line)
    assert {p: label for p, (label, _) in overlay.recap.texts.items()} == {
        ANALYST: recap.WRITTEN,
        fan: recap.FAN_RECAP,
    }
    labels = recap.LABELS[sk]
    assert {p: label for p, (label, _) in overlay.recap.translations[sk.value].items()} == {
        ANALYST: labels[recap.WRITTEN],
        fan: labels[recap.FAN_RECAP],
    }


# generator v1's runs, kept for the record and public, though no longer served (M9 item 8)
V1_RUNS = sorted(p for p in (REPO / "demo" / "runs-v1").iterdir() if p.is_dir())


@pytest.mark.parametrize("run", DEMO_RUNS + V1_RUNS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_demo_text_names_a_real_club_or_player(run):
    """The demo runs go public with the repo and on the page: no text of theirs (narratives,
    renditions, recaps, translations and their claims; drafts the Guard refused too) names a real
    club or a famous player: whole words, the last one also in a Slovak case."""
    texts = {
        text
        for h in served(run)
        for rewriting in (h.case, *h.case.renditions, *h.case.translations)
        for attempt in rewriting.attempts
        if attempt.draft is not None
        for text in (attempt.draft.text, *(c.text for c in attempt.draft.claims))
    }
    assert len(texts) > 0
    for text in texts:
        assert real_club_hits(text) == set(), text
        assert famous_surname_hits(text) == set(), text


def test_the_image_serves_the_demo_runs():
    """The image's command is one the CLI accepts, serves every demo run's match and replays
    every demo run, from the venv's script in exec form with no entrypoint in front (so SIGTERM
    reaches uvicorn), with a graceful shutdown that ends before ACA's SIGKILL at 30 s."""
    dockerfile = (REPO / "Dockerfile").read_text().replace("\\\n", "")
    (line,) = [ln for ln in dockerfile.splitlines() if ln.startswith("CMD ")]
    command = json.loads(line.removeprefix("CMD "))
    assert command[0] == "/app/.venv/bin/matchlens"
    assert re.search(r"^WORKDIR /app$", dockerfile, re.MULTILINE)
    assert "ENTRYPOINT" not in dockerfile
    args = cli._parser().parse_args(command[1:])
    assert args.run is cli._serve
    assert (args.host, args.port) == ("0.0.0.0", 8000)
    assert args.graceful_timeout == cli.GRACEFUL_TIMEOUT_S < 30
    assert re.search(r"^EXPOSE 8000$", dockerfile, re.MULTILINE)
    assert [f"m{s}" for s in args.seeds] == [p.name for p in DEMO_RUNS]
    assert args.runs == [Path("/app/demo/runs", p.name) for p in DEMO_RUNS]
    assert re.search(r"^COPY demo/runs \./demo/runs$", dockerfile, re.MULTILINE)


# `matchlens serve` held in its cold start (at `_serve`'s first import, uvicorn's, the earliest
# point its handler covers) or its warm-up (a cue timeline computing in the worker); SIG_IGN
# stands in for PID 1, which ignores a signal it has no handler for
STOP_SCRIPT = """
import signal, sys, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
from matchlens import cli
def hold(*_):
    print("holding", flush=True)
    time.sleep(600)
    return []
class HoldUvicorn:
    def find_spec(self, name, path=None, target=None):
        if name == "uvicorn":
            hold()
if sys.argv[1] == "cold":
    assert "uvicorn" not in sys.modules
    sys.meta_path.insert(0, HoldUvicorn())
else:
    from matchlens import api
    api.match_overlay = hold
sys.exit(cli.main(["serve", "--seed", "7", "--port", sys.argv[2], "--graceful-timeout", "1"]))
"""
# the exit after SIGTERM, measured 0.06 s cold and 0.21-0.27 s warm (5 runs each, devbox);
# ACA's SIGKILL comes at 30 s
STOP_LIMIT_S = 2.0


@pytest.mark.parametrize("phase", ["cold", "warm"])
def test_a_stop_while_the_server_starts_ends_it_at_once(phase):
    """A stop during the cold start waited for SIGKILL (Python as PID 1 had no SIGTERM handler
    before uvicorn's), and one during the warm-up too (the interpreter joined the pool thread
    computing a cue timeline, about a minute at 0.25 vCPU). Warming, the server is live but not
    ready."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    command = [sys.executable, "-c", STOP_SCRIPT, phase, str(port)]
    proc = subprocess.Popen(
        command, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        assert select.select([proc.stdout], [], [], 30)[0], "the server did not start within 30 s"
        assert proc.stdout.readline() == "holding\n", proc.communicate(timeout=10)[1]
        if phase == "warm":
            deadline = time.monotonic() + 30
            while True:
                try:
                    if httpx.get(f"{base}/healthz").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                assert time.monotonic() < deadline, "no /healthz within 30 s"
                time.sleep(0.05)
            r = httpx.get(f"{base}/readyz")
            assert (r.status_code, r.json()) == (503, {"status": "warming", "pending": ["m7"]})
        t0 = time.monotonic()
        proc.send_signal(signal.SIGTERM)
        code = proc.wait(timeout=10)
        took = time.monotonic() - t0
    finally:
        proc.kill()
        _, err = proc.communicate()
    assert code == 143, err
    assert took < STOP_LIMIT_S, f"exit took {took:.2f} s"
