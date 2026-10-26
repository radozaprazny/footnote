"""The Analyst reads a moment's facts over MCP from a real `matchlens mcp` streamable HTTP server
(in a thread); the model is the fake."""

import asyncio
import contextlib
import json
import socket
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

import anthropic
import httpx2
import pytest
import uvicorn
from agent_framework import (
    Agent,
    ChatResponse,
    Content,
    FunctionTool,
    MCPStreamableHTTPTool,
    Message,
)
from agent_framework.exceptions import ChatClientException, ToolException
from real import match

from matchlens.explain.analyst import FACTS_TOOL, MAX_REQUESTS, Analyst, moment_prompt
from matchlens.explain.detector import detect
from matchlens.explain.fake import TOOL_RESULT, FakeChatClient, by_moment, echo
from matchlens.explain.guard import check, moment_evidence
from matchlens.explain.log import HandoffLog, read_handoffs
from matchlens.explain.state import CallError, MomentOutcome
from matchlens.explain.summary import summarize
from matchlens.explain.workflow import FactsUnavailable, explain
from matchlens.facts import brief, facts_at
from matchlens.mcp import create_server

SEEDS = (0, 1, 2, 3, 4, 7)


@contextlib.contextmanager
def serving(seeds):
    """`matchlens mcp --http` for the seeds in a thread, on a free port; yields its URL and a
    function that stops it."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_server([match(seed) for seed in seeds], port=port).streamable_http_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)

    def stop():
        server.should_exit = True
        thread.join(timeout=10)

    try:
        yield f"http://127.0.0.1:{port}/mcp", stop
    finally:
        stop()


@pytest.fixture(scope="module")
def url():
    with serving(SEEDS) as (served, _):
        yield served


def tool(url):
    return MCPStreamableHTTPTool(
        name="matchlens", url=url, allowed_tools=[FACTS_TOOL], approval_mode="never_require"
    )


def first_goal():
    return detect(match(7), "r1", (1, 300_000))[0]


def attempt_over_mcp(url, client, case=None):
    case = case or first_goal()

    async def go():
        async with tool(url) as facts:
            return await Analyst(client, match(7), facts_tool=facts).attempt(case)

    return asyncio.run(go())


def call(name=FACTS_TOOL, **args) -> ChatResponse:
    content = Content.from_function_call(
        call_id=f"c{time.monotonic_ns()}", name=name, arguments=args
    )
    return ChatResponse(
        messages=[Message(role="assistant", contents=[content])], finish_reason="tool_calls"
    )


def test_the_analyst_reads_the_moment_s_facts_with_one_tool_call(url):
    case = first_goal()
    client = FakeChatClient(echo)
    attempt = attempt_over_mcp(url, client, case)
    assert attempt.requests == len(client.requests) == MAX_REQUESTS
    first, second = client.requests
    assert [t.name for t in first[1]["tools"]] == [FACTS_TOOL]  # the one tool it may call
    [result] = [c for m in second[0] for c in m.contents if c.type == "function_result"]
    served = json.loads(result.result)["result"]
    assert served == [json.loads(json.dumps(brief(f))) for f in facts_at(match(7), 1, case.end_ms)]
    assert second[1]["tool_choice"] == "none"  # the answer, no second call
    assert check(attempt.draft, case, moment_evidence(match(7), case)).passed


def test_the_tool_prompt_names_the_call_and_lists_no_facts():
    case = first_goal()
    prompt = moment_prompt(case, match(7), tool=True)
    assert (
        f'call the tool facts_at once, with match_id "m7", period 1 and clock_ms {case.end_ms}'
        in prompt
    )
    assert not any(f["fact_id"] in prompt for f in case.facts)
    assert "Saltreach FC (slt)" in prompt and "(cor-p18)" in prompt  # the ids the facts use
    assert "(cor-p18)" not in moment_prompt(case, match(7))


def test_an_attempt_without_the_tool_makes_one_request():
    client = FakeChatClient(echo)
    attempt = asyncio.run(Analyst(client, match(7)).attempt(first_goal()))
    assert attempt.requests == len(client.requests) == 1
    assert "tools" not in client.requests[0][1] or not client.requests[0][1]["tools"]


def test_a_model_that_keeps_calling_the_tool_gets_two_requests_and_no_draft(url):
    case = first_goal()
    args = {"match_id": "m7", "period": 1, "clock_ms": case.end_ms}
    client = FakeChatClient([call(**args), call(**args), call(**args), "{}"])
    attempt = attempt_over_mcp(url, client, case)
    assert attempt.requests == len(client.requests) == MAX_REQUESTS
    assert attempt.draft is None and attempt.error.code is CallError.INVALID_REPLY


def test_a_fact_read_at_another_clock_is_refused_by_the_guard(url):
    """The tool would serve any instant; the Guard checks the facts of the moment itself."""
    case = first_goal()

    def later(prompt):
        if TOOL_RESULT not in prompt:
            return call(match_id="m7", period=2, clock_ms=2_700_000)
        facts = json.loads(prompt.split(TOOL_RESULT)[-1])["result"]
        score = next(f for f in facts if f["name"] == "score" and "/to-" in f["fact_id"])
        text = f"The score is {score['display']}."
        claim = {"text": text, "fact_ids": [score["fact_id"]], "event_ids": [case.trigger_ids[0]]}
        return json.dumps({"text": text, "claims": [claim | {"frame_ids": []}]})

    attempt = attempt_over_mcp(url, FakeChatClient(later), case)
    verdict = check(attempt.draft, case, moment_evidence(match(7), case))
    assert not verdict.passed
    unknown = [r.token for r in verdict.reasons if r.code.value == "unknown_fact"]
    assert unknown == list(attempt.draft.claims[0].fact_ids)  # the score at 90+0:00, not at 04:18
    assert unknown[0].endswith("/score/to-2-2700000/all")


def run_explain(url, seed, client, **kwargs):
    with tempfile.TemporaryDirectory() as tmp:
        log = HandoffLog(Path(tmp) / "handoffs.jsonl")
        explained = asyncio.run(
            explain(match(seed), client, log, run_id="r1", facts_url=url, **kwargs)
        )
        return explained, read_handoffs(log.path) if log.path.exists() else []


def test_every_moment_of_seeds_0_to_4_gets_its_facts_over_mcp(url):
    """Real run, whole matches: the echo Analyst reads each moment's score with the tool."""
    for seed in range(5):
        client = FakeChatClient(echo)
        explained, handoffs = run_explain(url, seed, client)
        assert [e.case.moment_id for e in explained] == [
            c.moment_id for c in detect(match(seed), "r1")
        ]
        assert all(e.case.outcome is MomentOutcome.NARRATIVE for e in explained)
        s = summarize(handoffs)
        assert (s.model_calls, s.model_requests) == (len(explained), 2 * len(explained))
        assert {t.name for _, options in client.requests for t in options["tools"]} == {FACTS_TOOL}
        assert len(client.requests) == s.model_requests


@pytest.mark.parametrize(("max_calls", "attempted"), [(1, 0), (2, 1), (3, 1), (4, 2)])
def test_an_attempt_starts_only_when_both_its_requests_fit(url, max_calls, attempted):
    client = FakeChatClient(echo)
    explained, _ = run_explain(url, 7, client, until=(1, 1_700_000), max_calls=max_calls)
    assert len(client.requests) == 2 * attempted <= max_calls
    assert [e.case.attempts[0].called_model for e in explained] == [True] * attempted + [False] * (
        3 - attempted
    )


def test_a_server_without_the_match_stops_the_run_before_any_call(url):
    client = FakeChatClient(echo)
    with pytest.raises(FactsUnavailable, match="not m5"):
        run_explain(url, 5, client)
    assert client.requests == []


def test_no_server_stops_the_run_before_any_call():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]  # nothing listens here once the socket is closed
    client = FakeChatClient(echo)
    with pytest.raises(FactsUnavailable, match="facts over MCP"):
        run_explain(f"http://127.0.0.1:{port}/mcp", 7, client)
    assert client.requests == []


def test_retries_keep_reading_the_facts_with_the_tool(url):
    case = first_goal()
    client = FakeChatClient(by_moment({case.moment_id: ["not json", echo]}))
    [e], _ = run_explain(url, 7, client, until=(1, 300_000))
    assert [a.requests for a in e.case.attempts] == [1, 2]  # "not json" came without the tool
    assert e.case.outcome is MomentOutcome.NARRATIVE and e.cue == e.case.narrative


def test_a_facts_server_that_dies_mid_run_fails_attempts_not_the_run():
    """No facts from the tool: the attempt fails (AF reports the tool's error to the model, or
    raises when it cannot reconnect), the breaker or the retries end the moments stats-only,
    and the run itself finishes."""
    with serving([7]) as (served, stop):

        def script(prompt):
            stop()  # the server goes away while the first attempt is under way
            return echo(prompt)

        client = FakeChatClient(script)
        started = time.monotonic()
        explained, handoffs = run_explain(served, 7, client, until=(1, 1_700_000))
    assert time.monotonic() - started < 60
    attempts = [a for e in explained for a in e.case.attempts]
    assert {a.error.code for a in attempts} == {CallError.TRANSPORT, CallError.SKIPPED}
    first = [e.case.attempts[0] for e in explained]  # round 1: three calls, each failed
    assert all(a.error.detail.startswith("the facts tool failed") for a in first)
    s = summarize(handoffs)
    assert (s.narratives, s.stats_only, s.crashed) == (0, 3, ())
    assert s.errors == {"skipped": 3, "transport": 3}  # the breaker opened after 3
    assert s.model_requests == len(client.requests) <= 3 * 3 * 2


def test_a_tool_that_raises_is_a_transport_failure():
    analyst = Analyst(FakeChatClient(echo), match(7), facts_tool=FunctionTool(name=FACTS_TOOL))
    with mock.patch.object(Agent, "run", side_effect=ToolException("MCP server failed")):
        attempt = asyncio.run(analyst.attempt(first_goal()))
    assert attempt.error.code is CallError.TRANSPORT
    assert attempt.error.detail == "the facts tool failed: MCP server failed"


def test_words_before_the_tool_call_are_no_part_of_the_draft(url):
    case = first_goal()

    def chatty(prompt):
        reply = echo(prompt)
        if isinstance(reply, ChatResponse):  # the tool call, with a sentence before it
            reply.messages[0].contents.insert(0, Content.from_text("I'll fetch the facts."))
        return reply

    attempt = attempt_over_mcp(url, FakeChatClient(chatty), case)
    assert attempt.error is None and attempt.requests == 2
    assert check(attempt.draft, case, moment_evidence(match(7), case)).passed


def test_the_tokens_of_an_answered_request_count_when_the_next_one_fails(url):
    case = first_goal()
    args = {"match_id": "m7", "period": 1, "clock_ms": case.end_ms}
    first = call(**args)
    first.usage_details = {"input_token_count": 4071, "output_token_count": 90}
    limited = httpx2.Response(429, request=httpx2.Request("POST", "https://x.test/anthropic/"))
    error = ChatClientException("429")
    error.__cause__ = anthropic.RateLimitError("slow", response=limited, body=None)
    attempt = attempt_over_mcp(url, FakeChatClient([first, error]), case)
    assert attempt.error.code is CallError.RATE_LIMITED
    assert (attempt.requests, attempt.tokens_in, attempt.tokens_out) == (2, 4071, 90)


def test_a_tool_that_fails_inside_the_loop_is_a_transport_failure():
    """AF hands a failed tool's error to the model and asks again; the attempt still fails as
    transport, so the breaker sees a dead facts server."""

    def broken(match_id: str, period: int, clock_ms: int) -> str:
        raise RuntimeError("connection refused")

    facts = FunctionTool(name=FACTS_TOOL, description="facts", func=broken)
    client = FakeChatClient(echo)
    attempt = asyncio.run(Analyst(client, match(7), facts_tool=facts).attempt(first_goal()))
    assert attempt.error.code is CallError.TRANSPORT and attempt.requests == 2
    assert attempt.error.detail.startswith("the facts tool failed")
