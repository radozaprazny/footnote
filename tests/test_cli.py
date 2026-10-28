import argparse
import dataclasses
import functools
import inspect
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from importlib.metadata import entry_points

import anthropic
import httpx2
import pytest
import uvicorn
from agent_framework.exceptions import ChatClientException
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from matchlens import cli
from matchlens.events import MAX_PERIOD_MS, Event, MatchMeta, display_clock
from matchlens.explain import analyst, workflow
from matchlens.explain import summary as summary_module
from matchlens.explain.fake import FakeChatClient
from matchlens.explain.log import read_handoffs
from matchlens.explain.summary import chains
from matchlens.generator_v2 import generate_match_v2
from matchlens.mcp import create_server

cached_match = functools.cache(generate_match_v2)


@pytest.fixture(scope="module")
def match7():
    return cached_match(7)


@pytest.fixture
def fast(monkeypatch):
    """Matches come from a cache: the serve tests check wiring, not the generator."""
    monkeypatch.setattr("matchlens.cli.generate_match_v2", cached_match)


def run_generate(capsys, *args):
    code = cli.main(["generate", *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_every_match_the_cli_makes_is_generator_v2_s():
    """M9 item 8: the CLI's seven calls make v2's matches, and v1 is not imported here. Most CLI
    tests patch the generator (`fast`, `real.cli_on_v1`), so this pins the source itself."""
    source = inspect.getsource(cli)
    assert "matchlens.generator import" not in source
    assert source.count("generate_match_v2(") == 7


def test_generate_writes_the_match_as_json(capsys, match7):
    code, out, err = run_generate(capsys, "--seed", "7")
    assert code == 0
    doc = json.loads(out)
    assert set(doc) == {"meta", "events"}
    assert MatchMeta.from_dict(doc["meta"]) == match7.meta
    assert tuple(Event.from_dict(e) for e in doc["events"]) == match7.events
    home, away = match7.score()
    summary = (
        f"m7: {match7.meta.home} {home}-{away} {match7.meta.away}, {len(match7.events)} events"
    )
    assert err == summary + "\n"


def test_generate_is_byte_for_byte_deterministic(capsys):
    _, first, _ = run_generate(capsys, "--seed", "11")
    _, second, _ = run_generate(capsys, "--seed", "11")
    assert first == second and first.endswith("\n") and first.count("\n") == 1


def test_generate_with_chosen_clubs_and_an_output_file(capsys, tmp_path):
    path = tmp_path / "match.json"
    code, out, _ = run_generate(
        capsys, "--seed", "3", "--home", "cor", "--away", "vel", "--out", str(path)
    )
    assert code == 0 and out == ""
    meta = json.loads(path.read_text(encoding="utf-8"))["meta"]
    assert (meta["match_id"], meta["home"], meta["away"]) == ("m3corvel", "cor", "vel")
    umask = os.umask(0)
    os.umask(umask)
    assert stat.S_IMODE(path.stat().st_mode) == 0o666 & ~umask
    assert [p.name for p in tmp_path.iterdir()] == ["match.json"]  # no temp file left


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["generate", "--seed", "-1"], "seed must not be negative: -1"),
        (["generate", "--seed", "x"], "invalid seed value: 'x'"),
        (["generate"], "the following arguments are required: --seed"),
        (
            ["generate", "--seed", "1", "--home", "xyz"],
            "unknown home club 'xyz'; choose from cor, qrd, slt, vel",
        ),
        (["generate", "--seed", "1", "--away", "XYZ"], "unknown away club 'XYZ'"),
        (
            ["generate", "--seed", "1", "--home", "cor", "--away", "cor"],
            "home and away are both cor",
        ),
        (["serve", "--seed", "7", "--seed", "8", "--seed", "7"], "duplicate seed: 7"),
        (["serve", "--port", "eighty"], "invalid port value: 'eighty'"),
        (["serve", "--port", "65536"], "port must be in 0-65535: 65536"),
        (["serve", "--graceful-timeout", "-1"], "seconds must not be negative: -1"),
        (["mcp", "--seed", "7", "--seed", "7"], "duplicate seed: 7"),
        (["mcp", "--port", "65536"], "port must be in 0-65535: 65536"),
        (["mcp", "--seed", "7", "--port", "8123"], "--host and --port need --http"),
        (["mcp", "--seed", "7", "--host", "0.0.0.0"], "--host and --port need --http"),
        ([], "the following arguments are required: command"),
        (["explain", "7"], "a match id is m<seed>, such as m7: '7'"),
        (["explain", "m07"], "a match id is m<seed>, such as m7: 'm07'"),
        (["explain", "m7", "--until", "90:00"], "a broadcast clock such as 67:23"),
        (["explain", "m7", "--max-calls", "-1"], "calls must not be negative: -1"),
        (["explain", "m7", "--pace", "-1"], "seconds must not be negative: -1"),
        (["explain", "m7", "--fake", "--deployment", "x"], "--deployment names a real model"),
    ],
)
def test_bad_arguments_exit_2_with_a_message(capsys, args, message):
    with pytest.raises(SystemExit) as stop:
        cli.main(args)
    assert stop.value.code == 2
    assert message in capsys.readouterr().err


@pytest.mark.parametrize(
    ("args", "usage"),
    [
        (["generate", "--seed", "1", "--home", "xyz"], "usage: matchlens generate"),
        (["serve", "--seed", "7", "--seed", "7"], "usage: matchlens serve"),
    ],
)
def test_errors_after_parsing_show_the_subcommand_usage(capsys, args, usage):
    with pytest.raises(SystemExit):
        cli.main(args)
    assert capsys.readouterr().err.startswith(usage)


def test_unwritable_output_exits_1_without_a_traceback(capsys, tmp_path):
    target = tmp_path / "missing-dir" / "match.json"
    assert cli.main(["generate", "--seed", "2", "--out", str(target)]) == 1
    err = capsys.readouterr().err
    assert err == f"matchlens generate: cannot write {target}: No such file or directory\n"


def test_a_failed_write_keeps_the_old_file(capsys, tmp_path, monkeypatch):
    path = tmp_path / "match.json"
    path.write_text("old", encoding="utf-8")

    def disk_full(*_):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("matchlens.cli.os.replace", disk_full)
    assert cli.main(["generate", "--seed", "2", "--out", str(path)]) == 1
    assert path.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["match.json"]
    assert "No space left on device" in capsys.readouterr().err


def test_serve_runs_uvicorn_with_the_seeded_matches(fast, monkeypatch, capsys):
    calls, handlers = [], []
    before = signal.getsignal(signal.SIGTERM)

    def run(app, **kw):
        calls.append((app, kw))
        handlers.append(signal.getsignal(signal.SIGTERM))

    monkeypatch.setattr("uvicorn.run", run)
    assert cli.main(["serve", "--seed", "7", "--seed", "8", "--port", "8123"]) == 0
    assert handlers == [cli._stop]  # what uvicorn puts back and raises again after its shutdown
    assert signal.getsignal(signal.SIGTERM) is before
    ((app, kw),) = calls
    assert kw == {"host": "127.0.0.1", "port": 8123, "timeout_graceful_shutdown": 20}
    served = TestClient(app).get("/matches").json()
    assert [m["match_id"] for m in served] == ["m7", "m8"]
    # the public app's limits (issue #2): the whole match at once is refused, the page's most not
    assert TestClient(app).get("/matches/m7/live?speed=0").status_code == 422
    assert TestClient(app).get("/matches/m7/live?speed=60.2&hz=5").status_code == 422
    last = cached_match(7).events[-1].event_id  # the page's most is served: a short resume
    assert (
        TestClient(app).get(f"/matches/m7/live?speed=60&hz=5&last_event_id={last}").status_code
        == 200
    )
    assert "serving m7, m8 on http://127.0.0.1:8123" in capsys.readouterr().err


def test_serve_defaults(fast, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.append((app, kw)))
    assert cli.main(["serve", "--graceful-timeout", "5"]) == 0
    ((app, kw),) = calls
    assert kw == {"host": "127.0.0.1", "port": 8000, "timeout_graceful_shutdown": 5}
    assert [m["match_id"] for m in TestClient(app).get("/matches").json()] == ["m1", "m2", "m3"]
    assert "serving m1, m2, m3 on" in capsys.readouterr().err


def test_python_dash_m_gives_the_same_bytes_in_a_fresh_process(capsys):
    out = subprocess.run(
        [sys.executable, "-m", "matchlens", "generate", "--seed", "2"],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONHASHSEED": "1"},
    )
    _, here, _ = run_generate(capsys, "--seed", "2")
    assert out.stdout == here
    assert out.stderr.startswith("m2: ")


def test_a_closed_pipe_ends_quietly():
    """`matchlens generate | head -c 100`: no traceback, exit 1 (the reader left early)."""
    gen = subprocess.Popen(
        [sys.executable, "-m", "matchlens", "generate", "--seed", "2"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    gen.stdout.read(100)
    gen.stdout.close()
    _, err = gen.communicate()
    assert gen.returncode == 1
    assert b"Traceback" not in err and b"BrokenPipeError" not in err


def test_the_matchlens_command_points_at_main():
    (script,) = [e for e in entry_points(group="console_scripts") if e.name == "matchlens"]
    assert script.value == "matchlens.cli:main"


def test_mcp_serves_the_seeded_matches_over_stdio(fast, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr("mcp.server.fastmcp.FastMCP.run", lambda s, t: calls.append((s, t)))
    assert cli.main(["mcp", "--seed", "7", "--seed", "8"]) == 0
    ((server, transport),) = calls
    assert transport == "stdio"
    out = capsys.readouterr()
    assert out.out == ""  # stdout carries the protocol
    assert "facts of m7, m8 over MCP on stdio" in out.err


def test_mcp_over_streamable_http(fast, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr("mcp.server.fastmcp.FastMCP.run", lambda s, t: calls.append((s, t)))
    assert cli.main(["mcp", "--seed", "7", "--http", "--port", "8123"]) == 0
    ((server, transport),) = calls
    assert transport == "streamable-http"
    assert (server.settings.host, server.settings.port) == ("127.0.0.1", 8123)
    assert "facts of m7 over MCP on http://127.0.0.1:8123/mcp" in capsys.readouterr().err


# explain

# three of v2's m7 moments end by 12:00 (01:27, 04:07, 11:12; the fourth at 14:56)
UNTIL = "12:00"


def explain_run(capsys, tmp_path, *args):
    code = cli.main(["explain", "m7", "--runs", str(tmp_path), *args])
    out = capsys.readouterr()
    [run_dir] = (tmp_path / "m7").iterdir()
    return code, out.out, out.err, run_dir


def test_explain_with_the_fake_analyst_writes_the_log_and_the_summary(fast, capsys, tmp_path):
    code, out, err, run_dir = explain_run(capsys, tmp_path, "--fake", "--until", UNTIL)
    assert code == 0
    lines = out.splitlines()
    assert lines[0] == "m7-k00026 01:27 narrative (1): The score is 0–0."
    s = json.loads((run_dir / "summary.json").read_text())
    assert len(lines) == 4 and lines[-1] == (
        "3 moments: 3 narratives, 0 stats-only, 0 crashed; pass rate 100% first attempt, 100% "
        f"final; 3 attempts, 3 model calls (3 requests), 0 skipped; tokens {s['tokens_in']} in / "
        f"{s['tokens_out']} out, $0.0000; latency p50 {s['latency_ms_p50']} ms, p95 "
        f"{s['latency_ms_p95']} ms"
    )
    assert f"log and summary: {run_dir}" in err
    summary = json.loads((run_dir / "summary.json").read_text())
    assert (summary["run_id"], summary["moments"], summary["models"]) == (
        run_dir.name,
        3,
        ["fake"],
    )
    assert summary["final_pass_rate"] == 1.0 and summary["cost_usd"] == 0.0
    handoffs = read_handoffs(run_dir / "handoffs.jsonl")
    assert len(handoffs) == 9 and len(chains(handoffs)) == 3


def test_explain_with_a_persona_prints_each_rendition_and_its_summary(fast, capsys, tmp_path):
    args = ("--fake", "--until", UNTIL, "--persona", "fan", "--persona", "fan")
    code, out, _, run_dir = explain_run(capsys, tmp_path, *args)
    assert code == 0
    lines = out.splitlines()
    assert lines[:2] == [
        "m7-k00026 01:27 narrative (1): The score is 0–0.",
        "  fan passed (1): The score is 0–0.",
    ]
    s = json.loads((run_dir / "summary.json").read_text())
    fan = s["personas"]["fan"]
    assert (fan["renditions"], fan["passed"], fan["model_requests"]) == (3, 3, 3)
    assert s["settings"]["personas"] == ["fan"]  # a persona named twice is asked for once
    assert lines[-2].startswith("fan: 3 renditions: 3 passed, 0 fallback to the narrative, 0 open")
    assert lines[-1].startswith("all agents: 6 requests, tokens ")
    assert s["total_requests"] == 6 and s["model_requests"] == 3


def test_explain_refuses_an_unknown_persona(capsys, tmp_path):
    with pytest.raises(SystemExit) as exit_:
        cli.main(["explain", "m7", "--fake", "--persona", "pundit", "--runs", str(tmp_path)])
    assert exit_.value.code == 2 and "invalid choice: 'pundit'" in capsys.readouterr().err


def test_explain_stops_calling_once_max_calls_are_spent(fast, capsys, tmp_path):
    args = ("--fake", "--until", UNTIL, "--max-calls", "1")
    code, out, _, run_dir = explain_run(capsys, tmp_path, *args)
    assert code == 0
    outcomes = [line.split()[2] for line in out.splitlines()[:3]]
    assert outcomes == ["narrative", "stats_only", "stats_only"]
    summary = json.loads((run_dir / "summary.json").read_text())
    assert (summary["model_calls"], summary["skipped"], summary["errors"]) == (1, 2, {"skipped": 2})


def test_explain_with_no_calls_allowed_gives_stats_only_cues(fast, capsys, tmp_path):
    args = ("--fake", "--until", UNTIL, "--max-calls", "0")
    code, out, err, run_dir = explain_run(capsys, tmp_path, *args)
    assert code == 0
    assert out.splitlines()[-1].startswith("3 moments: 0 narratives, 3 stats-only, 0 crashed")
    assert "3 attempts made no call (circuit breaker or --max-calls)" in err
    assert json.loads((run_dir / "summary.json").read_text())["model_calls"] == 0


def test_explain_allows_40_calls_by_default(capsys):
    with pytest.raises(SystemExit):
        cli.main(["explain", "--help"])
    assert "(required for a model; 40 with --fake)" in " ".join(capsys.readouterr().out.split())


def test_a_run_that_calls_a_model_names_its_cap(fast, capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(analyst, "foundry_client", lambda deployment: FakeChatClient([]))
    with pytest.raises(SystemExit) as stop:
        cli.main(["explain", "m7", "--runs", str(tmp_path)])
    assert stop.value.code == 2
    assert "a run that calls a model needs --max-calls" in capsys.readouterr().err
    assert not tmp_path.joinpath("m7").exists()


def test_a_moment_left_without_a_cue_exits_1(fast, capsys, tmp_path, monkeypatch):
    real = summary_module.summarize
    monkeypatch.setattr(
        summary_module,
        "summarize",
        lambda handoffs, stopped=None: dataclasses.replace(real(handoffs, stopped), crashed=("x",)),
    )
    code, _, err, _ = explain_run(capsys, tmp_path, "--fake", "--until", "05:00")
    assert code == 1 and "moments without a cue: ('x',)" in err


def test_explain_reads_the_facts_over_mcp(fast, capsys, tmp_path, mcp_url):
    args = ("--fake", "--until", UNTIL, "--mcp", mcp_url)
    code, out, _, run_dir = explain_run(capsys, tmp_path, *args)
    assert code == 0
    assert "3 attempts, 3 model calls (6 requests)" in out.splitlines()[-1]
    assert json.loads((run_dir / "summary.json").read_text())["model_requests"] == 6


def test_explain_over_mcp_with_a_persona_makes_one_request_a_rendition(
    fast, capsys, tmp_path, mcp_url
):
    args = ("--fake", "--until", UNTIL, "--mcp", mcp_url, "--persona", "fan")
    code, out, _, run_dir = explain_run(capsys, tmp_path, *args)
    assert code == 0
    s = json.loads((run_dir / "summary.json").read_text())
    assert (s["model_requests"], s["personas"]["fan"]["model_requests"]) == (6, 3)
    assert s["personas"]["fan"]["passed"] == 3 and s["total_requests"] == 9


def test_explain_without_its_mcp_server_stops_with_exit_1(fast, capsys, tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    args = ("--fake", "--mcp", f"http://127.0.0.1:{port}/mcp")
    code, out, err, run_dir = explain_run(capsys, tmp_path, *args)
    assert code == 1 and "run stopped: facts over MCP" in err
    assert json.loads((run_dir / "summary.json").read_text())["model_requests"] == 0


@pytest.fixture
def mcp_url():
    """`matchlens mcp --http --seed 7` in a thread, on a free port."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_server([cached_match(7)], port=port).streamable_http_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=10)


def test_explain_passes_its_pace_on(fast, capsys, tmp_path, monkeypatch):
    seen = {}
    real = workflow.explain

    async def spy(*args, **kwargs):
        seen.update(kwargs)
        return await real(*args, **kwargs)

    monkeypatch.setattr(workflow, "explain", spy)
    code, *_ = explain_run(capsys, tmp_path, "--fake", "--until", "05:00", "--pace", "2")
    assert code == 0 and seen["pace_s"] == 2


def test_explain_before_the_first_moment_has_nothing_to_explain(fast, capsys, tmp_path):
    code, out, _, run_dir = explain_run(capsys, tmp_path, "--fake", "--until", "01:00")
    assert code == 0 and out.startswith("0 moments: 0 narratives")
    assert not (run_dir / "handoffs.jsonl").exists()
    assert json.loads((run_dir / "summary.json").read_text())["moments"] == 0


def test_explain_needs_the_foundry_resource_without_fake(fast, capsys, tmp_path, monkeypatch):
    monkeypatch.delenv("MATCHLENS_FOUNDRY_RESOURCE", raising=False)
    with pytest.raises(SystemExit) as stop:
        cli.main(["explain", "m7", "--max-calls", "9", "--runs", str(tmp_path)])
    assert stop.value.code == 2
    assert "MATCHLENS_FOUNDRY_RESOURCE is not set" in capsys.readouterr().err
    assert not tmp_path.joinpath("m7").exists()


def test_a_fatal_call_stops_the_run_with_exit_1_and_a_summary(fast, capsys, tmp_path, monkeypatch):
    request = httpx2.Request("POST", "https://test-resource.services.ai.azure.com/anthropic/")
    denied = anthropic.AuthenticationError(
        "Error code: 401", response=httpx2.Response(401, request=request), body=None
    )
    error = ChatClientException("Anthropic authentication failed")
    error.__cause__ = denied
    monkeypatch.setattr(analyst, "foundry_client", lambda deployment: FakeChatClient([error]))
    code, out, err, run_dir = explain_run(capsys, tmp_path, "--until", UNTIL, "--max-calls", "9")
    assert code == 1
    assert "run stopped: AuthenticationError: Error code: 401" in err
    summary = json.loads((run_dir / "summary.json").read_text())
    assert summary["stopped"] == "AuthenticationError: Error code: 401"
    assert (summary["moments"], len(summary["crashed"])) == (0, 3)


@given(st.sampled_from([1, 2]), st.integers(0, MAX_PERIOD_MS // 1000))
def test_a_broadcast_clock_reads_back_as_its_instant(period, seconds):
    assert cli.clock(display_clock(period, seconds * 1000)) == (period, seconds * 1000)


@pytest.mark.parametrize(
    ("text", "instant"),
    [
        ("00:00", (1, 0)),
        ("44:59", (1, 2_699_000)),
        ("45:00", (2, 0)),
        ("45+0:00", (1, 2_700_000)),
        ("45+2:13", (1, 2_833_000)),
        ("45+15:00", (1, MAX_PERIOD_MS)),
        ("89:59", (2, 2_699_000)),
        ("90+0:00", (2, 2_700_000)),
        ("90+15:00", (2, MAX_PERIOD_MS)),
    ],
)
def test_broadcast_clocks_on_the_edges(text, instant):
    assert cli.clock(text) == instant


@pytest.mark.parametrize(
    "text",
    ["90:00", "45+15:01", "90+15:01", "5:00", "05:60", "00:00:00", "60+1:00", "135:00", "", "x"],
)
def test_impossible_broadcast_clocks_are_refused(text):
    with pytest.raises(argparse.ArgumentTypeError, match="broadcast clock"):
        cli.clock(text)


def test_match_ids_name_their_seed():
    assert [cli.match_id(t) for t in ("m0", "m7", "m123")] == [0, 7, 123]
