"""The Analyst on fake clients only: the scripted `FakeChatClient`, and the real Foundry client of
agent-framework-anthropic over a mock HTTP transport. No test reaches a model or the network: a
fake identity endpoint on loopback stands in for Azure Container Apps' managed identity."""

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import anthropic
import httpx2
import pytest
from agent_framework import ChatResponse, Message
from agent_framework.exceptions import ChatClientException
from agent_framework_anthropic import AnthropicFoundryClient
from azure.core.exceptions import ClientAuthenticationError
from azure.identity.aio import AzureCliCredential as AioAzureCliCredential
from azure.identity.aio import ManagedIdentityCredential, get_bearer_token_provider
from explain_strategies import DRAFT, attempts, claims, json_values, rejections
from hypothesis import given, settings
from hypothesis import strategies as st
from real import match

from matchlens.events import EventType, display_clock
from matchlens.explain import analyst
from matchlens.explain.analyst import (
    DRAFT_SCHEMA,
    EFFORT,
    INSTRUCTIONS,
    MAX_TOKENS,
    Analyst,
    moment_prompt,
    window,
    write_as,
)
from matchlens.explain.fake import FakeChatClient, ScriptExhausted
from matchlens.explain.guard import MAX_CLAIMS, MAX_TEXT, check, judge, moment_evidence
from matchlens.explain.state import MAX_ATTEMPTS, CallError, Claim, Draft, MomentCase
from matchlens.facts import facts_at
from matchlens.league import load_league

KINDS = (EventType.GOAL, EventType.SAVE)


def moment(seed: int, kind: EventType, nth: int = 0, attempts_so_far=()) -> MomentCase:
    """A real moment as the Detector will make it: a goal or save, its facts at that clock."""
    m = match(seed)
    e = [e for e in m.events if e.type is kind][nth]
    return MomentCase(
        run_id="r1",
        match_id=m.meta.match_id,
        moment_id=f"{m.meta.match_id}-k{nth}",
        trigger_ids=(e.related, e.event_id) if e.related else (e.event_id,),
        period=e.period,
        start_ms=max(0, e.clock_ms - 10_000),
        end_ms=e.clock_ms,
        display_clock=display_clock(e.period, e.clock_ms),
        facts=tuple(f.to_dict() for f in facts_at(m, e.period, e.clock_ms)),
        attempts=tuple(attempts_so_far),
    )


def run(coro):
    return asyncio.run(coro)


def fact(case: MomentCase, name: str, team: str | None = None) -> dict:
    return next(f for f in case.facts if f["name"] == name and f["team"] == team)


def goal_reply(case: MomentCase) -> Draft:
    """A narrative the Guard passes: score and minute, cited, with the goal as evidence."""
    score, minute = fact(case, "score"), fact(case, "minute")
    claim = Claim(
        f"it is {score['display']} in the {write_as(minute).split(' or ')[1]}",
        (score["fact_id"], minute["fact_id"]),
        (case.trigger_ids[-1],),
    )
    return Draft(f"Goal, and {claim.text}.", (claim,))


# --- the attempt -----------------------------------------------------------------------------


def test_a_real_goal_draft_from_the_analyst_passes_the_guard():
    case = moment(7, EventType.GOAL)
    reply = goal_reply(case)
    client = FakeChatClient([json.dumps(reply.to_dict())])
    attempt = run(Analyst(client, match(7)).attempt(case))
    assert (attempt.n, attempt.model, attempt.draft, attempt.error) == (1, "fake", reply, None)
    assert check(attempt.draft, case, moment_evidence(match(7), case)).passed
    assert attempt.tokens_in > len(INSTRUCTIONS) and attempt.tokens_out == len(
        json.dumps(reply.to_dict())
    )
    assert attempt.latency_ms >= 0


def test_the_request_carries_instructions_schema_effort_and_the_moment():
    case = moment(7, EventType.GOAL)
    client = FakeChatClient([json.dumps(goal_reply(case).to_dict())])
    run(Analyst(client, match(7)).attempt(case))
    [(messages, options)] = client.requests
    assert options["instructions"] == INSTRUCTIONS
    assert options["response_format"] == DRAFT_SCHEMA
    assert options["output_config"] == {"effort": EFFORT} and EFFORT == "low"  # the M3 plan
    assert options["max_tokens"] == MAX_TOKENS == 4000
    assert (analyst.REQUEST_TIMEOUT_S, analyst.MAX_RETRIES, analyst.CALL_TIMEOUT_S) == (120, 0, 300)
    assert Analyst(client, match(7)).timeout_s == analyst.CALL_TIMEOUT_S
    assert [m.text for m in messages] == [moment_prompt(case, match(7))]


@settings(deadline=None)  # an event loop and an AF agent per example: wall time follows load
@given(st.builds(Draft, st.text(max_size=80), st.lists(claims("m7"), max_size=4)))
def test_any_draft_the_model_returns_is_the_attempt_draft(draft):
    case = moment(7, EventType.GOAL)
    attempt = run(Analyst(FakeChatClient([json.dumps(draft.to_dict())]), match(7)).attempt(case))
    assert attempt.draft == draft and attempt.error is None


FINISH = st.sampled_from([None, "stop", "length", "content_filter", "tool_calls"])
REPLIES = (
    st.text(max_size=60)
    | json_values.map(json.dumps)
    | st.builds(
        lambda d, extra: json.dumps(d.to_dict() | extra),
        st.builds(Draft, st.text(max_size=20), st.lists(claims("m7"), max_size=2)),
        st.dictionaries(st.sampled_from(["text", "claims", "x"]), json_values, max_size=1),
    )
)


@settings(deadline=None)  # an event loop and an AF agent per example: wall time follows load
@given(REPLIES, FINISH)
def test_any_reply_gives_a_draft_or_the_reason_why_not(text, finish):
    reply = ChatResponse(
        messages=[Message(role="assistant", contents=[text])],
        finish_reason=finish,
        usage_details={"input_token_count": 7, "output_token_count": 3},
    )
    attempt = run(Analyst(FakeChatClient([reply]), match(7)).attempt(moment(7, EventType.GOAL)))
    assert (attempt.tokens_in, attempt.tokens_out) == (7, 3)  # a bad reply is billed too
    if finish == "content_filter":
        assert attempt.error.code is CallError.REFUSAL
    elif finish == "length":
        assert attempt.error.code is CallError.INVALID_REPLY
        assert str(MAX_TOKENS) in attempt.error.detail
    else:
        try:
            expected = Draft.from_dict(json.loads(text))
        except ValueError:
            expected = None
        assert attempt.draft == expected
        if expected is None:
            assert attempt.error.code is CallError.INVALID_REPLY
            assert attempt.error.detail.startswith("no Draft: ")


def test_a_reply_that_does_not_come_in_time_is_a_timeout():
    class Slow(FakeChatClient):
        async def _inner_get_response(self, **kwargs):
            await asyncio.sleep(5)

    analyst_ = Analyst(Slow([]), match(7), timeout_s=0.01)
    attempt = run(analyst_.attempt(moment(7, EventType.GOAL)))
    assert attempt.error.code is CallError.TIMEOUT
    assert attempt.error.detail == "no reply within 0.01 s"
    assert (attempt.tokens_in, attempt.tokens_out) == (0, 0)
    assert 10 <= attempt.latency_ms < 5_000


def test_a_script_that_runs_out_stops_the_test_instead_of_failing_an_attempt():
    with pytest.raises(ScriptExhausted):
        run(Analyst(FakeChatClient([]), match(7)).attempt(moment(7, EventType.GOAL)))


def test_the_attempt_number_follows_the_earlier_attempts():
    case = moment(7, EventType.GOAL)
    client = FakeChatClient(["no json", json.dumps(goal_reply(case).to_dict())])
    a = Analyst(client, match(7))
    first = run(a.attempt(case))
    rejected = case.with_attempt(first)
    rejected = rejected.with_verdict(judge(rejected, moment_evidence(match(7), rejected)))
    second = run(a.attempt(rejected))
    assert (first.n, first.error.code, second.n, second.error) == (1, "invalid_reply", 2, None)
    assert "Attempt 1: no draft, invalid_reply: no Draft: " in client.requests[1][0][0].text


def test_a_case_that_takes_no_further_attempt_is_refused_before_the_call():
    case = moment(7, EventType.GOAL)
    client = FakeChatClient(["no json"] * 3 + [json.dumps(goal_reply(case).to_dict())])
    a = Analyst(client, match(7))
    evidence = moment_evidence(match(7), case)
    unjudged = spent = case.with_attempt(run(a.attempt(case)))
    for _ in range(MAX_ATTEMPTS - 1):
        spent = spent.with_verdict(judge(spent, evidence))
        spent = spent.with_attempt(run(a.attempt(spent)))
    spent = spent.with_verdict(judge(spent, evidence))
    passed = case.with_attempt(run(a.attempt(case)))
    passed = passed.with_verdict(judge(passed, evidence))
    assert spent.is_open and len(spent.attempts) == MAX_ATTEMPTS and not passed.is_open
    asked = len(client.requests)
    for refused, why in (
        (unjudged, "not judged yet"),
        (spent, "no further attempt"),
        (passed, "no further attempt"),
        (spent.stats_only(), "no further attempt"),
    ):
        with pytest.raises(ValueError, match=why):
            run(a.attempt(refused))
    assert len(client.requests) == asked == MAX_ATTEMPTS + 1  # no call for a refused case


# --- the prompt ------------------------------------------------------------------------------


@st.composite
def open_cases(draw):
    """A real goal or save with 0–2 rejected attempts before it, all judged."""
    seed, kind = draw(st.sampled_from([0, 1, 7])), draw(st.sampled_from(KINDS))
    nth = draw(st.integers(0, sum(e.type is kind for e in match(seed).events) - 1))
    m_id = match(seed).meta.match_id
    n = draw(st.integers(0, 2))
    tried = [draw(attempts(m_id, i, draw(rejections))) for i in range(1, n + 1)]
    return moment(seed, kind, nth, tried), seed


@given(open_cases())
def test_the_prompt_carries_every_fact_trigger_name_and_earlier_reason(drawn):
    case, seed = drawn
    m = match(seed)
    prompt = moment_prompt(case, m)
    assert prompt.startswith(f"Moment {case.moment_id} at clock {case.display_clock}.\n")
    assert "\nTrigger events (cite at least one in every claim):\n" in prompt
    league = load_league()
    names = {p.id: p.name for c in league.clubs for p in c.players}
    clubs = {c.id: c.name for c in league.clubs}
    for f in case.facts:
        whose = names.get(f["player"]) or clubs.get(f["team"]) or "the match"
        counts = f"{f['name'].replace('_', ' ')} of {whose}"
        line = f"- {f['fact_id']} | {write_as(f)} | {counts} | {window(f['fact_id'])}\n"
        assert line in prompt + "\n"
        assert f["display"] in write_as(f)
    for t in case.trigger_ids:
        assert f"- {t}: " in prompt
    for p in m.meta.home_lineup + m.meta.away_lineup:
        assert names[p] in prompt
    assert f"Home: {clubs[m.meta.home]}. Away: {clubs[m.meta.away]}." in prompt
    for side, lineup in (("Home", m.meta.home_lineup), ("Away", m.meta.away_lineup)):
        assert f"{side} lineup: {', '.join(names[p] for p in lineup)}." in prompt
    events = {e.event_id: e for e in m.events}
    for t in case.trigger_ids:
        e = events[t]
        outcome = f", {e.outcome.value.replace('_', ' ')}" if e.outcome else ""
        line = f"- {t}: {e.type.value} by {names.get(e.player) or clubs[e.team]}{outcome}\n"
        assert line in prompt + "\n"
    for a in case.attempts:
        if a.draft is not None:
            assert f"Attempt {a.n}: {json.dumps(a.draft.text, ensure_ascii=False)}" in prompt
            for i, c in enumerate(a.draft.claims):
                cites = (
                    f"facts {', '.join(c.fact_ids) or '-'}; events {', '.join(c.event_ids) or '-'}"
                )
                assert f"  claim {i}: {json.dumps(c.text, ensure_ascii=False)} ({cites})" in prompt
            for r in a.verdict.reasons:
                tag = "" if r.claim is None else f"[claim {r.claim}] "
                assert f"  - {tag}{r.code.value}: {r.detail}" in prompt
        else:
            assert f"Attempt {a.n}: no draft, {a.error.code.value}: {a.error.detail}" in prompt
    assert ("Earlier attempts" in prompt) == bool(case.attempts)


def test_the_prompt_refuses_a_case_of_another_match():
    with pytest.raises(ValueError, match="not of match m1"):
        moment_prompt(moment(7, EventType.GOAL), match(1))


@pytest.mark.parametrize("seed", [0, 7])
def test_every_way_the_prompt_says_to_write_a_fact_passes_the_guard(seed):
    """The prompt's "write as" forms and windows agree with the Guard: each form, cited in a
    claim with the window it needs, passes; every goal and save of the match, so every window
    occurs."""
    windows = set()
    for kind in KINDS:
        for nth in range(sum(e.type is kind for e in match(seed).events)):
            windows |= _forms_pass(moment(seed, kind, nth), seed)
    assert windows == {"at this moment", "so far in the match", "last 5 minutes", "fixed"}


def _forms_pass(case: MomentCase, seed: int) -> set[str]:
    evidence = moment_evidence(match(seed), case)
    for f in case.facts:
        for form in write_as(f).split(" or "):
            said = (
                f"{form} in the last 5 minutes"
                if window(f["fact_id"]) == "last 5 minutes"
                else form
            )
            if f["name"].endswith("_reading") and f["team"]:  # its club right before the phrase
                club = next(c.name for c in load_league().clubs if c.id == f["team"])
                said = f"{club} {said}"
            claim = Claim(said, (f["fact_id"],), (case.trigger_ids[-1],))
            verdict = check(Draft(f"It is {said}.", (claim,)), case, evidence)
            assert verdict.passed, (f["fact_id"], form, verdict.reasons)
    return {window(f["fact_id"]) for f in case.facts}


def test_the_draft_schema_has_exactly_the_fields_of_a_draft():
    """Structured output fills the schema; `Draft.from_dict` refuses a missing or unknown key."""
    assert set(DRAFT_SCHEMA["properties"]) == set(DRAFT_SCHEMA["required"]) == set(DRAFT.to_dict())
    item = DRAFT_SCHEMA["properties"]["claims"]["items"]
    claim = DRAFT.to_dict()["claims"][0]
    assert set(item["properties"]) == set(item["required"]) == set(claim)
    assert DRAFT_SCHEMA["additionalProperties"] is item["additionalProperties"] is False
    assert DRAFT_SCHEMA["properties"]["text"] == item["properties"]["text"] == {"type": "string"}
    for name in ("fact_ids", "event_ids", "frame_ids"):
        assert item["properties"][name] == {"type": "array", "items": {"type": "string"}}


def test_a_long_error_message_is_cut_to_300_characters():
    failure = analyst.call_failure(ChatClientException("x" * 1000))
    assert failure.code is CallError.TRANSPORT
    assert len(failure.detail) == 300 and failure.detail.endswith("…")
    assert failure.detail.startswith("ChatClientException: xxx")


def test_the_sdk_error_is_found_anywhere_in_the_cause_chain():
    request = httpx2.Request("POST", "https://test-resource.services.ai.azure.com/anthropic/")
    limited = anthropic.RateLimitError(
        "slow down", response=httpx2.Response(429, request=request), body=None
    )
    try:
        try:
            raise RuntimeError("wrapped once") from limited
        except RuntimeError as inner:
            raise ChatClientException("wrapped twice") from inner
    except ChatClientException as outer:
        failure = analyst.call_failure(outer)
    assert failure.code is CallError.RATE_LIMITED
    assert failure.detail.startswith("RateLimitError: slow down")


@pytest.mark.parametrize(("length", "cut"), [(278, False), (279, False), (280, True)])
def test_an_error_detail_is_kept_up_to_300_characters_and_cut_above(length, cut):
    detail = analyst.call_failure(ChatClientException("x" * length)).detail  # 21-char prefix
    assert detail.endswith("…") is cut
    assert detail == (f"ChatClientException: {'x' * length}" if not cut else detail)
    assert len(detail) == min(21 + length, 300)


def test_write_as_and_window_examples():
    assert write_as({"name": "shirt_number", "display": "19", "unit": ""}) == "No. 19"
    assert write_as({"name": "minute", "display": "68'", "unit": ""}) == "68' or 68th minute"
    assert write_as({"name": "minute", "display": "45+2'", "unit": ""}) == "45+2'"
    assert write_as({"name": "average_possession_length", "display": "15.1", "unit": "s"}) == (
        "15.1 s"
    )
    assert write_as({"name": "possession", "display": "66%", "unit": "%"}) == "66%"
    assert window("m7/possession/to-1-258931/cor") == "so far in the match"
    assert window("m7/minute/at-1-258931/all") == "at this moment"
    assert window("m7/chaos/last5-2-300000/all") == "last 5 minutes"
    assert window("m7/shirt_number/league/cor-p18") == "fixed"


def test_the_instructions_state_the_guard_limits():
    assert f"At most {MAX_CLAIMS} claims and {MAX_TEXT} characters." in INSTRUCTIONS
    assert '"last 5 minutes"' in INSTRUCTIONS
    for phrase in ("a goal ahead", "the only goal", "after 13 minutes", "79 percent", "4-4-2"):
        assert phrase in INSTRUCTIONS
    # words that state a count or judge the goals or the play: the prompt bans them, as the
    # Guard lets some through (Follow-ups); the readings' phrases are taught apart (Readings)
    for word in (
        *("first", "second", "his second", "again", "another", "half the"),  # counts
        *("lead", "level", "equaliser", "goalless", "draw"),  # the score
        *("more", "majority", "up from", "chaotic", "high", "despite", "only"),
        *("clean sheet", "opens the scoring", "hit back"),
        *("early", "late", "before half-time"),  # time without a fact
    ):
        assert f'"{word}"' in INSTRUCTIONS
    assert "cites that fact and states its number." in INSTRUCTIONS
    assert "Describe only what the trigger events and the facts say." in INSTRUCTIONS
    assert "No colon as punctuation (a clock such as 67:23 is fine)." in INSTRUCTIONS


# --- the real Foundry client over a mock transport -------------------------------------------


def foundry(handler, retries: int = 0) -> AnthropicFoundryClient:
    """agent-framework-anthropic's Foundry client as the factory builds it (resource name, Entra
    token), with HTTP answered by `handler`."""
    sdk = anthropic.AsyncAnthropicFoundry(
        resource="test-resource",
        azure_ad_token_provider=lambda: "entra-token",
        http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
        max_retries=retries,
    )
    return AnthropicFoundryClient(model="claude-haiku-5-5", anthropic_client=sdk)


def message(text: str, stop: str = "end_turn") -> dict:
    content = [{"type": "text", "text": text}] if text else []
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 2112, "output_tokens": 236},
    }


def test_the_foundry_request_and_reply_go_through_the_analyst():
    case = moment(7, EventType.GOAL)
    reply = goal_reply(case)
    seen = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(200, json=message(json.dumps(reply.to_dict())))

    attempt = run(Analyst(foundry(handler), match(7)).attempt(case))
    assert (attempt.model, attempt.draft, attempt.tokens_in, attempt.tokens_out) == (
        "claude-haiku-5-5",
        reply,
        2112,
        236,
    )
    [request] = seen
    assert request.url.host == "test-resource.services.ai.azure.com"
    assert request.url.path == "/anthropic/v1/messages"
    assert request.headers["authorization"] == "Bearer entra-token"
    body = json.loads(request.content)
    assert body["model"] == "claude-haiku-5-5" and body["max_tokens"] == MAX_TOKENS
    assert body["output_config"]["effort"] == EFFORT
    assert body["output_config"]["format"] == {"type": "json_schema", "schema": DRAFT_SCHEMA}
    system = body["system"] if isinstance(body["system"], str) else body["system"][0]["text"]
    assert system == INSTRUCTIONS
    assert body["messages"][0]["content"][0]["text"] == moment_prompt(case, match(7))
    assert "tool_choice" not in body or body["tool_choice"]["type"] == "auto"


@pytest.mark.parametrize(
    ("answer", "code"),
    [
        (
            httpx2.Response(429, json={"type": "error", "error": {"type": "rate_limit_error"}}),
            "rate_limited",
        ),
        (httpx2.Response(500, json={"type": "error", "error": {"type": "api_error"}}), "transport"),
        (
            httpx2.Response(529, json={"type": "error", "error": {"type": "overloaded_error"}}),
            "transport",
        ),
        (httpx2.Response(408, json={"type": "error", "error": {"type": "timeout"}}), "transport"),
        (httpx2.Response(409, json={"type": "error", "error": {"type": "conflict"}}), "transport"),
        (httpx2.ReadTimeout("read timed out"), "timeout"),
        (httpx2.ConnectError("connection refused"), "transport"),
        (httpx2.Response(200, json=message("", stop="refusal")), "refusal"),
        (httpx2.Response(200, json=message('{"text": "cut', stop="max_tokens")), "invalid_reply"),
        (httpx2.Response(200, json=message('{"text": "no claims"}')), "invalid_reply"),
    ],
)
def test_every_failed_foundry_call_is_a_failed_attempt_with_its_code(answer, code):
    def handler(request: httpx2.Request) -> httpx2.Response:
        if isinstance(answer, Exception):
            raise type(answer)(str(answer), request=request)
        return answer

    attempt = run(Analyst(foundry(handler), match(7)).attempt(moment(7, EventType.GOAL)))
    assert attempt.draft is None and attempt.error.code == code, attempt.error
    assert attempt.called_model
    assert len(attempt.error.detail) <= 300


@pytest.mark.parametrize("status", [400, 401, 403, 404, 407, 410, 413, 422, 428, 430, 499])
def test_a_4xx_the_sdk_does_not_retry_stops_the_run(status):
    """Credentials or the request itself: no retry mends them, so no attempt is recorded."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={"type": "error", "error": {"type": "x"}})

    with pytest.raises(analyst.FatalCallError, match=f"Error code: {status}") as raised:
        run(Analyst(foundry(handler), match(7)).attempt(moment(7, EventType.GOAL)))
    assert len(str(raised.value)) <= 300


def test_an_entra_token_that_cannot_be_fetched_stops_the_run():
    def expired():
        raise ClientAuthenticationError("Please run 'az login' to set up an account")

    sdk = anthropic.AsyncAnthropicFoundry(
        resource="test-resource",
        azure_ad_token_provider=expired,
        http_client=anthropic.DefaultAsyncHttpxClient(
            transport=httpx2.MockTransport(lambda r: httpx2.Response(200, json=message("{}")))
        ),
        max_retries=0,
    )
    client = AnthropicFoundryClient(model="claude-haiku-5-5", anthropic_client=sdk)
    with pytest.raises(analyst.FatalCallError, match="az login"):
        run(Analyst(client, match(7)).attempt(moment(7, EventType.GOAL)))


def status_error(status: int) -> ChatClientException:
    request = httpx2.Request("POST", "https://test-resource.services.ai.azure.com/anthropic/")
    response = httpx2.Response(status, request=request)
    wrapped = ChatClientException("wrapped")
    wrapped.__cause__ = anthropic.APIStatusError("x", response=response, body=None)
    return wrapped


@pytest.mark.parametrize(
    ("status", "fatal"),
    [(399, False), (400, True), (407, True), (408, False), (409, False), (410, True)]
    + [(428, True), (429, False), (430, True), (499, True), (500, False)],
)
def test_fatal_is_a_4xx_but_408_409_and_429(status, fatal):
    error = status_error(status)
    assert (analyst.fatal_cause(error) is error.__cause__) is fatal


def test_a_429_is_one_request_and_rate_limited():
    seen = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        error = {"type": "error", "error": {"type": "rate_limit_error"}}
        return httpx2.Response(429, headers={"retry-after-ms": "1"}, json=error)

    analyst_ = Analyst(foundry(handler, retries=analyst.MAX_RETRIES), match(7))
    attempt = run(analyst_.attempt(moment(7, EventType.GOAL)))
    assert attempt.error.code is CallError.RATE_LIMITED
    assert len(seen) == analyst.MAX_RETRIES + 1 == attempt.requests  # every HTTP request counted


# --- the factory -----------------------------------------------------------------------------


def test_the_factory_needs_the_foundry_resource(monkeypatch):
    monkeypatch.delenv(analyst.FOUNDRY_RESOURCE_ENV, raising=False)
    with pytest.raises(RuntimeError, match=analyst.FOUNDRY_RESOURCE_ENV):
        analyst.foundry_client()


def test_the_factory_cannot_build_the_real_client_in_a_test(monkeypatch):
    monkeypatch.setenv(analyst.FOUNDRY_RESOURCE_ENV, "aif-matchlens")
    with pytest.raises(AssertionError, match="real Foundry client"):
        analyst.foundry_client()


def test_the_factory_builds_an_entra_client_for_the_chosen_deployment(monkeypatch):
    built, scopes = [], []

    async def tokens() -> str:
        return "entra-token"

    monkeypatch.setattr(analyst, "AnthropicFoundryClient", lambda **kw: built.append(kw))
    monkeypatch.setattr(
        analyst,
        "get_bearer_token_provider",
        lambda cred, scope: scopes.append((type(cred), scope)) or tokens,
    )
    monkeypatch.setenv(analyst.FOUNDRY_RESOURCE_ENV, " aif-matchlens ")
    monkeypatch.delenv(analyst.DEPLOYMENT_ENV, raising=False)
    monkeypatch.delenv(analyst.IDENTITY_ENDPOINT_ENV, raising=False)
    analyst.foundry_client()
    monkeypatch.setenv(analyst.DEPLOYMENT_ENV, "claude-sonnet-5-5")
    analyst.foundry_client()
    analyst.foundry_client("other")
    assert [b["model"] for b in built] == ["claude-haiku-5-5", "claude-sonnet-5-5", "other"]
    sdks = [b["anthropic_client"] for b in built]
    assert {str(s.base_url) for s in sdks} == {
        "https://aif-matchlens.services.ai.azure.com/anthropic/"
    }
    assert (
        {(s.timeout, s.max_retries) for s in sdks}
        == {(analyst.REQUEST_TIMEOUT_S, analyst.MAX_RETRIES)}
        == {(120, 0)}
    )
    assert {s._azure_ad_token_provider for s in sdks} == {tokens}
    assert set(scopes) == {(AioAzureCliCredential, "https://ai.azure.com/.default")}


def test_the_instructions_teach_the_readings_as_the_only_judgement():
    readings = INSTRUCTIONS.split("Readings\n", 1)[1].split("\nClaims\n", 1)[0]
    assert "name ends in _reading" in readings
    for phrase in ('"take the lead"', '"on top"', '"more of the ball"'):
        assert phrase in readings
    for other_form in ('"equalises"', '"pulls one back"', '"took the lead"'):
        assert other_form in readings  # forms the Guard refuses
    assert '"last 5 minutes"; any other reading into a claim that does not' in readings
    assert '"Vellbridge Town take the lead"' in readings  # the club right before the phrase
    assert "Say why the moment matters" in readings
    # a phrase of the vocabulary is no longer among the bans
    bans = INSTRUCTIONS.split("Readings\n", 1)[0]
    for phrase in ('"take the lead"', '"equalise"', '"end-to-end"', '"extend"'):
        assert phrase not in bans
    # "one" is a banned number word, so the phrase that holds it is named as the exception
    assert (
        bans.count('"pull one back"') == 1
        and 'phrase such as "pull one back" is the exception' in bans
    )


def test_a_reading_is_written_as_its_phrase_and_the_tool_lines_say_so():
    fact = {"name": "goal_reading", "display": "take the lead", "unit": "", "fact_id": "x"}
    assert write_as(fact) == "take the lead"
    case = moment(7, EventType.GOAL)
    assert "_reading judges another" in moment_prompt(case, match(7), tool=True)


@pytest.mark.parametrize("endpoint", [None, "", "  "])
def test_off_azure_the_credential_is_the_cli_login(monkeypatch, endpoint):
    if endpoint is None:
        monkeypatch.delenv(analyst.IDENTITY_ENDPOINT_ENV, raising=False)
    else:
        monkeypatch.setenv(analyst.IDENTITY_ENDPOINT_ENV, endpoint)
    assert type(analyst.foundry_credential()) is AioAzureCliCredential


def test_in_azure_container_apps_the_token_comes_from_the_managed_identity(monkeypatch):
    """With the variables Azure Container Apps sets, the token comes from its identity endpoint
    (App Service protocol), over azure-core's requests transport: no aiohttp needed."""
    seen = []

    class Endpoint(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append((self.path, self.headers["X-IDENTITY-HEADER"]))
            body = json.dumps(
                {
                    "access_token": "mi-token",
                    "expires_on": str(int(time.time()) + 3600),
                    "resource": "https://ai.azure.com",
                    "token_type": "Bearer",
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Endpoint)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{server.server_port}/msi/token"
    monkeypatch.setenv(analyst.IDENTITY_ENDPOINT_ENV, endpoint)
    monkeypatch.setenv("IDENTITY_HEADER", "header-secret")
    for other in ("IDENTITY_SERVER_THUMBPRINT", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(other, raising=False)  # Service Fabric's variant; no proxy to loopback
        monkeypatch.delenv(other.lower(), raising=False)
    credential = analyst.foundry_credential()
    assert type(credential) is ManagedIdentityCredential

    async def token() -> str:
        try:
            return await get_bearer_token_provider(credential, analyst.TOKEN_SCOPE)()
        finally:
            await credential.close()

    try:
        assert asyncio.run(token()) == "mi-token"
    finally:
        server.shutdown()
        server.server_close()
    assert seen == [
        ("/msi/token?api-version=2019-08-01&resource=https://ai.azure.com", "header-secret")
    ]
