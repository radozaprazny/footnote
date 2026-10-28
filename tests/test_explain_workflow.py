import ast
import asyncio
import dataclasses
import functools
import itertools
import tempfile
import time
from pathlib import Path
from unittest import mock

import anthropic
import httpx2
import pytest
from agent_framework import ChatResponse, Message
from agent_framework.exceptions import ChatClientException
from hypothesis import given, settings
from hypothesis import strategies as st
from real import match

import matchlens
from matchlens.explain import detector, guard, workflow
from matchlens.explain.analyst import FatalCallError
from matchlens.explain.detector import detect
from matchlens.explain.fake import FakeChatClient, by_moment, echo
from matchlens.explain.guard import check, moment_evidence, stats_only_draft
from matchlens.explain.log import HandoffLog, Role, read_handoffs
from matchlens.explain.state import (
    MAX_ATTEMPTS,
    PERSONA_ATTEMPTS,
    Attempt,
    CallError,
    CallFailure,
    Draft,
    MomentOutcome,
    Persona,
    RenditionOutcome,
)
from matchlens.explain.summary import chains, summarize
from matchlens.explain.workflow import BREAKER_AFTER, CallBudget, explain
from matchlens.facts import facts_at

UNTIL = (1, 1_700_000)  # m7 up to 28:20: three moments (04:18, 12:34, 26:53)
REQUEST = httpx2.Request("POST", "https://test-resource.services.ai.azure.com/anthropic/")
KINDS = ("pass", "rejected", "invalid", "refusal", "transport", "timeout", "rate_limited")
NO_ANSWER = {"transport", "timeout", "rate_limited"}

_facts: dict = {}


def memo_facts_at(m, period, clock_ms):
    """`facts_at`, once per instant (it reads only the events up to then)."""
    key = (m.meta.match_id, period, clock_ms)
    if key not in _facts:
        _facts[key] = facts_at(m, period, clock_ms)
    return _facts[key]


@functools.cache
def moments(until=UNTIL):
    return tuple(detect(match(7), "r1", until))


def caused(cause: Exception, text: str) -> ChatClientException:
    error = ChatClientException(text)
    error.__cause__ = cause
    return error


def reply(kind: str):
    """A scripted reply of `kind`; exceptions are new each time."""
    if kind == "pass":
        return echo
    if kind == "rejected":
        return '{"text": "A moment to remember.", "claims": []}'
    if kind == "invalid":
        return "not json"
    if kind == "refusal":
        return ChatResponse(
            messages=[Message(role="assistant", contents=[""])], finish_reason="content_filter"
        )
    if kind == "transport":
        return ChatClientException("Anthropic chat request failed: Connection error.")
    if kind == "timeout":
        return caused(anthropic.APITimeoutError(request=REQUEST), "Request timed out.")
    if kind == "rate_limited":
        limited = httpx2.Response(429, request=REQUEST)
        return caused(anthropic.RateLimitError("slow", response=limited, body=None), "429")
    raise AssertionError(kind)


def kind_of(attempt) -> str:
    if attempt.error is not None:
        return {"invalid_reply": "invalid"}.get(attempt.error.code.value, attempt.error.code.value)
    return "pass" if attempt.verdict.passed else "rejected"


def simulate(ids, kinds, max_calls):
    """The recovery policy, written out: rounds of attempts in moment order; a moment closes on
    a pass, on its third attempt or on a skipped one; no call after `BREAKER_AFTER` calls in a
    row without an answer or once `max_calls` are spent."""
    calls = in_row = 0
    done = {m: [] for m in ids}
    outcome = {}
    waiting = list(ids)
    for n in range(MAX_ATTEMPTS):
        retry = []
        for m in waiting:
            if in_row >= BREAKER_AFTER or calls >= max_calls:
                done[m].append("skipped")
                outcome[m] = MomentOutcome.STATS_ONLY
                continue
            kind = kinds[m][n]
            calls += 1
            in_row = in_row + 1 if kind in NO_ANSWER else 0
            done[m].append(kind)
            if kind == "pass":
                outcome[m] = MomentOutcome.NARRATIVE
            elif n == MAX_ATTEMPTS - 1:
                outcome[m] = MomentOutcome.STATS_ONLY
            else:
                retry.append(m)
        waiting = retry
    return done, outcome, calls


def run_workflow(client, until=UNTIL, max_calls=40, m=None, pace_s=0.0, personas=()):
    with tempfile.TemporaryDirectory() as tmp:
        log = HandoffLog(Path(tmp) / "handoffs.jsonl")
        with (
            mock.patch.object(detector, "facts_at", memo_facts_at),
            mock.patch.object(guard, "facts_at", memo_facts_at),
        ):
            coro = explain(
                m or match(7),
                client,
                log,
                run_id="r1",
                until=until,
                max_calls=max_calls,
                pace_s=pace_s,
                personas=personas,
            )
            explained = asyncio.run(coro)
        return explained, read_handoffs(log.path)


def scripted(kinds: dict[str, list[str]]) -> FakeChatClient:
    return FakeChatClient(by_moment({m: [reply(k) for k in ks] for m, ks in kinds.items()}))


# properties


@settings(deadline=None)  # an event loop and a workflow per example
@given(
    st.lists(st.lists(st.sampled_from(KINDS), min_size=3, max_size=3), min_size=3, max_size=3),
    st.integers(0, 10),
)
def test_the_workflow_follows_the_recovery_policy(drawn, max_calls):
    ids = [c.moment_id for c in moments()]
    kinds = dict(zip(ids, drawn, strict=True))
    client = scripted(kinds)
    explained, handoffs = run_workflow(client, max_calls=max_calls)
    want, outcome, calls = simulate(ids, kinds, max_calls)
    assert [e.case.moment_id for e in explained] == ids
    assert len(client.requests) == calls <= max_calls
    for e in explained:
        case = e.case
        assert len(case.attempts) <= MAX_ATTEMPTS
        assert [kind_of(a) for a in case.attempts] == want[case.moment_id]
        assert case.outcome is outcome[case.moment_id]
        evidence = moment_evidence(match(7), case)
        if case.outcome is MomentOutcome.NARRATIVE:  # a narrative is the draft that passed
            assert case.attempts[-1].verdict.passed and e.cue == case.narrative
        else:  # stats-only: no attempt passed, and the cue is made of facts
            assert not any(a.verdict.passed for a in case.attempts)
            assert e.cue == stats_only_draft(case, evidence)
        assert check(e.cue, case, evidence).passed
    # a log line for every transition: one in, one per attempt to the Guard and one back or out
    assert len(handoffs) == sum(1 + 2 * len(e.case.attempts) for e in explained)
    lines = chains(handoffs)  # each moment's lines form one chain
    assert [ls[-1].case for ls in lines.values()] == [e.case for e in explained]
    assert all(ls[-1].receiver is Role.RENDER for ls in lines.values())
    # the run summary counts what happened
    s = summarize(handoffs)
    narratives = sum(outcome[m] is MomentOutcome.NARRATIVE for m in ids)
    assert (s.moments, s.narratives, s.stats_only, s.crashed) == (3, narratives, 3 - narratives, ())
    assert (s.attempts, s.model_calls) == (sum(map(len, want.values())), calls)
    assert s.model_requests == calls  # no facts tool: one request per call
    assert s.skipped == sum(w.count("skipped") for w in want.values())
    assert s.first_attempt_passed == sum(w[0] == "pass" for w in want.values())


@settings(deadline=None)
@given(
    st.integers(0, 24),
    st.sampled_from([1, 2]),
    st.lists(st.tuples(st.sampled_from(KINDS), st.integers(1, 2)), min_size=12, max_size=12),
)
def test_the_breaker_and_the_budget_hold_on_any_call_sequence(max_calls, per_attempt, calls):
    """An attempt starts only when its worst case fits: the requests never pass `max_calls`;
    an attempt that made more requests than it may stops the run."""
    budget = CallBudget(max_calls, per_attempt)
    made = in_row = 0
    for kind, requests in calls:
        if requests > per_attempt:
            with pytest.raises(RuntimeError, match="model requests"):
                budget.count(attempt_with(None, requests))
            continue
        why = budget.why_not()
        assert (why is None) == (in_row < BREAKER_AFTER and made + per_attempt <= max_calls)
        if why is None:
            failure = None if kind in ("pass", "rejected") else CallError(kind_code(kind))
            budget.count(attempt_with(failure, requests))
            made += requests
            in_row = in_row + 1 if kind in NO_ANSWER else 0
    assert budget.calls == made <= max_calls and budget.reserved == 0


@settings(deadline=None)
@given(
    st.integers(0, 12),
    st.sampled_from([1, 2]),
    st.lists(
        st.tuples(st.booleans(), st.integers(1, 2), st.integers(0, 2), st.sampled_from(KINDS)),
        max_size=24,
    ),
)
def test_reservations_in_flight_never_pass_the_cap(max_calls, per_attempt, steps):
    """Attempts of two agents interleave: each reserves before it calls and counts after; at
    every step what is spent and held fits the cap, and at the end nothing stays held."""
    budget = CallBudget(max_calls, per_attempt)
    in_flight = []  # (need held, requests it will make)
    made = 0
    for start, need, requests, kind in steps:
        if start or not in_flight:
            held = min(need, per_attempt)
            fits = budget.calls + budget.reserved + held <= max_calls
            open_breaker = budget.no_answer_in_row >= BREAKER_AFTER
            why = budget.reserve(need)
            assert (why is None) == (fits and not open_breaker)
            if why is None:
                in_flight.append((need, min(requests, held)))
        else:
            need, requests = in_flight.pop(0)
            failure = None if kind in ("pass", "rejected") else CallError(kind_code(kind))
            budget.count(attempt_with(failure, requests), need)
            made += requests
        assert budget.calls + budget.reserved <= max_calls and budget.reserved >= 0
    for need, requests in in_flight:
        budget.count(attempt_with(None, requests), need)
        made += requests
    assert budget.reserved == 0 and budget.calls == made <= max_calls


def test_a_count_releases_only_what_was_held():
    budget = CallBudget(2, per_attempt=1)
    assert budget.reserve(2) is None and budget.reserved == 1  # a need above per_attempt holds 1
    with pytest.raises(RuntimeError, match="model requests"):
        budget.count(attempt_with(None, 2), 2)  # it may make 1, the one it holds
    budget.count(attempt_with(None, 1), 2)
    assert (budget.reserved, budget.calls) == (0, 1)
    with pytest.raises(RuntimeError, match="1 requests, 0 are held"):
        budget.count(attempt_with(None, 1), 1)  # nothing reserved for it
    assert budget.reserve() is None
    assert budget.why_not() == "the run's 2 model calls are spent or held by attempts in flight (1)"


def kind_code(kind: str) -> str:
    return {"invalid": "invalid_reply"}.get(kind, kind)


def attempt_with(code: CallError | None, requests: int = 1) -> Attempt:
    if code is None:
        return Attempt(1, "fake", Draft("x", ()), requests=requests)
    return Attempt(1, "fake", None, error=CallFailure(code, "x"), requests=requests)


# examples


def test_every_moment_of_seeds_0_to_4_gets_the_echo_narrative():
    """Real run, whole matches: the `--fake` Analyst's draft passes the Guard on every moment."""
    for seed in range(5):
        m = match(seed)
        explained, handoffs = run_workflow(FakeChatClient(echo), until=None, m=m)
        assert [e.case.moment_id for e in explained] == [c.moment_id for c in detect(m, "r1")]
        assert all(e.case.outcome is MomentOutcome.NARRATIVE for e in explained)
        assert all(len(e.case.attempts) == 1 for e in explained)
        summary = summarize(handoffs)
        assert (summary.moments, summary.narratives, summary.crashed) == (
            len(explained),
            len(explained),
            (),
        )


def test_two_calls_without_an_answer_then_one_keep_the_breaker_shut():
    ids = [c.moment_id for c in moments()]
    kinds = {ids[0]: ["transport", "pass"], ids[1]: ["timeout", "pass"], ids[2]: ["pass"]}
    explained, _ = run_workflow(scripted(kinds))
    assert [e.case.outcome for e in explained] == [MomentOutcome.NARRATIVE] * 3
    assert [len(e.case.attempts) for e in explained] == [2, 2, 1]


def test_the_third_call_without_an_answer_in_a_row_opens_the_breaker():
    ids = [c.moment_id for c in moments()]
    kinds = {ids[0]: ["transport"], ids[1]: ["rate_limited"], ids[2]: ["timeout"]}
    client = scripted(kinds)
    explained, _ = run_workflow(client)
    assert len(client.requests) == 3
    for e in explained:  # each moment's second attempt is skipped: stats-only at once
        assert [kind_of(a) for a in e.case.attempts][1:] == ["skipped"]
        assert "circuit breaker" in e.case.attempts[1].error.detail
        assert e.case.outcome is MomentOutcome.STATS_ONLY


def test_a_spent_budget_skips_the_call_and_ends_the_moment_at_once():
    ids = [c.moment_id for c in moments()]
    client = scripted({ids[0]: ["pass"]})
    explained, _ = run_workflow(client, max_calls=1)
    assert len(client.requests) == 1
    assert [len(e.case.attempts) for e in explained] == [1, 1, 1]
    assert [e.case.outcome for e in explained] == [MomentOutcome.NARRATIVE] + [
        MomentOutcome.STATS_ONLY
    ] * 2
    assert {e.case.attempts[0].error.detail for e in explained[1:]} == {
        "the run's 1 model calls are spent"
    }
    assert not any(e.case.attempts[0].called_model for e in explained[1:])


def test_a_fatal_call_stops_the_run_and_its_moments_are_crashed():
    ids = [c.moment_id for c in moments()]
    denied = httpx2.Response(401, request=REQUEST)
    fatal = caused(anthropic.AuthenticationError("expired", response=denied, body=None), "401")
    client = FakeChatClient(by_moment({ids[0]: [echo], ids[1]: [fatal]}))
    with tempfile.TemporaryDirectory() as tmp:
        log = HandoffLog(Path(tmp) / "handoffs.jsonl")
        with pytest.raises(FatalCallError, match="AuthenticationError"):
            asyncio.run(explain(match(7), client, log, run_id="r1", until=UNTIL))
        summary = summarize(read_handoffs(log.path), stopped="401")
    assert len(client.requests) == 2  # no call after the fatal one
    assert (summary.moments, summary.crashed, summary.stopped) == (0, tuple(ids), "401")


def test_a_case_whose_facts_are_not_the_engine_s_stops_the_run():
    def tampered(m, run_id, until):
        case = detect(m, run_id, until)[0]
        facts = [f | {"display": "9–9"} if f["name"] == "score" else f for f in case.facts]
        return [dataclasses.replace(case, facts=tuple(facts))]

    client = FakeChatClient(echo)
    with mock.patch.object(workflow, "detect", tampered), pytest.raises(ValueError, match="9–9"):
        run_workflow(client)
    assert client.requests == []  # found by the Detector, before the first (billed) call


def test_max_calls_is_a_count():
    for bad in (-1, True, 1.0):
        with pytest.raises(ValueError, match="max_calls"):
            CallBudget(bad)
    for bad in (0, True, 2.0):
        with pytest.raises(ValueError, match="per_attempt"):
            CallBudget(5, bad)
    assert CallBudget(5, 1).why_not() is None
    assert CallBudget(0).why_not() == "the run's 0 model calls are spent"


def test_only_the_guard_executor_judges():
    """`MomentCase` checks consistency, not provenance: `with_verdict` is called in the Guard
    executor and nowhere else in the package, once for the Analyst's attempt, once for a
    rendition's and once for a translation's."""
    calls = []
    for path in Path(matchlens.__file__).parent.rglob("*.py"):
        tree = ast.parse(path.read_text())
        owner = {}  # each node's innermost enclosing class
        for cls in ast.walk(tree):
            if isinstance(cls, ast.ClassDef):
                owner |= {id(node): cls.name for node in ast.walk(cls)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "with_verdict":
                calls.append((path.name, owner.get(id(node))))
    assert calls == [("workflow.py", "GuardExecutor")] * 3


def test_a_stats_only_cue_the_guard_refuses_stops_the_run():
    """It passes by construction; should it not, that is a bug, not a cue to show."""
    no_claims = Draft("A moment.", ())
    with (
        mock.patch.object(workflow, "stats_only_draft", lambda case, evidence: no_claims),
        pytest.raises(RuntimeError, match="stats-only cue fails the Guard: no_claims"),
    ):
        run_workflow(FakeChatClient([]), max_calls=0)


def test_paced_attempts_start_at_least_the_pace_apart():
    starts = []

    def timed(prompt):
        starts.append(time.monotonic())
        return echo(prompt)

    run_workflow(FakeChatClient(timed), pace_s=0.3)
    gaps = [b - a for a, b in itertools.pairwise(starts)]
    assert len(starts) == 3 and min(gaps) >= 0.3 - 0.02  # timed at the request, not the start


@pytest.mark.parametrize(
    ("took", "waits"),
    [(0.0, [10.0, 10.0]), (4.0, [6.0, 6.0]), (10.0, [0.0, 0.0]), (11.0, [-1.0, -1.0])],
)
def test_the_pace_counts_from_the_previous_attempt_s_start(took, waits):
    """On a clock of its own: an attempt that took `took` s leaves `pace - took` to wait, none
    once it took the whole pace (a negative sleep returns at once)."""
    now, slept = [100.0], []

    async def sleep(seconds):
        slept.append(round(seconds, 6))
        now[0] += max(0.0, seconds)

    def slow(prompt):
        now[0] += took
        return echo(prompt)

    with (
        mock.patch.object(workflow, "_clock", lambda: now[0]),
        mock.patch.object(workflow, "_sleep", sleep),
    ):
        run_workflow(FakeChatClient(slow), pace_s=10.0)
    assert slept == waits


def test_without_a_pace_attempts_follow_at_once_and_skipped_ones_never_wait():
    """On the pace's own clock, not the wall's (wall time flaked under CPU load, 27 Oct): without
    a pace no attempt waits; with one, a run whose other attempts are skipped waits for none."""
    now, slept = [100.0], []

    async def sleep(seconds):
        slept.append(seconds)
        now[0] += max(0.0, seconds)

    with (
        mock.patch.object(workflow, "_clock", lambda: now[0]),
        mock.patch.object(workflow, "_sleep", sleep),
    ):
        run_workflow(FakeChatClient(echo))
        assert slept and all(s <= 0.0 for s in slept)  # the pace was asked, and waited nothing
        slept.clear()
        explained, _ = run_workflow(FakeChatClient(echo), max_calls=1, pace_s=5.0)
    assert all(s <= 0.0 for s in slept)  # one call, two skipped: nothing to wait for
    assert now[0] == 100.0
    assert [e.case.attempts[0].called_model for e in explained] == [True, False, False]


# --- the Persona Editor (M5) -------------------------------------------------------------------

ANSWERS = ("pass", "rejected", "invalid", "refusal")  # kinds that bring an answer: no breaker
FAN = Persona.FAN


def scripted_with_fan(analyst: dict[str, list[str]], fan: dict[str, list[str]]) -> FakeChatClient:
    script = {m: [reply(k) for k in ks] for m, ks in analyst.items()}
    script |= {f"{m}/fan": [reply(k) for k in ks] for m, ks in fan.items()}
    return FakeChatClient(by_moment(script))


def fan_policy(kinds: list[str]) -> tuple[list[str], RenditionOutcome]:
    """A rendition's attempts and outcome, written out: a pass ends it; one retry after a
    rejected or failed attempt; then the narrative stands in."""
    done = []
    for kind in kinds[:PERSONA_ATTEMPTS]:
        done.append(kind)
        if kind == "pass":
            return done, RenditionOutcome.PASSED
    return done, RenditionOutcome.FALLBACK


@settings(deadline=None)
@given(
    st.lists(st.lists(st.sampled_from(ANSWERS), min_size=3, max_size=3), min_size=3, max_size=3),
    st.lists(st.lists(st.sampled_from(ANSWERS), min_size=2, max_size=2), min_size=3, max_size=3),
)
def test_nothing_leaves_the_workflow_that_did_not_pass_the_guard(analyst_drawn, fan_drawn):
    ids = [c.moment_id for c in moments()]
    analyst, fan = (
        dict(zip(ids, analyst_drawn, strict=True)),
        dict(zip(ids, fan_drawn, strict=True)),
    )
    client = scripted_with_fan(analyst, fan)
    explained, handoffs = run_workflow(client, personas=(FAN,))
    want, outcome, analyst_calls = simulate(ids, analyst, 40)
    fan_calls = 0
    for e in explained:
        case, evidence = e.case, moment_evidence(match(7), e.case)
        assert case.outcome is outcome[case.moment_id]
        shown = e.for_persona(FAN)
        assert check(shown, case, evidence).passed  # whatever a fan sees passed the Guard
        if case.outcome is not MomentOutcome.NARRATIVE:  # no narrative: no rendition, the cue
            assert case.renditions == () and shown == e.cue
            continue
        (r,) = case.renditions
        kinds, end = fan_policy(fan[case.moment_id])
        assert [kind_of(a) for a in r.attempts] == kinds and r.outcome is end
        assert len(r.attempts) <= PERSONA_ATTEMPTS
        fan_calls += len(r.attempts)
        if end is RenditionOutcome.PASSED:  # the persona's own draft, the one that passed
            assert r.attempts[-1].verdict.passed and shown == r.attempts[-1].draft
        else:  # the narrative stands in; no rejected text is shown
            assert shown == case.narrative == e.cue
            assert not any(a.verdict.passed for a in r.attempts)
    assert len(client.requests) == analyst_calls + fan_calls
    # a log line for every transition: one in, two per attempt of either agent
    assert len(handoffs) == sum(
        1 + 2 * len(e.case.attempts) + 2 * sum(len(r.attempts) for r in e.case.renditions)
        for e in explained
    )
    lines = chains(handoffs)
    assert [ls[-1].case for ls in lines.values()] == [e.case for e in explained]
    s = summarize(handoffs)
    rendered = [r for e in explained for r in e.case.renditions]
    if rendered:
        f = s.personas["fan"]
        assert (f["renditions"], f["open"]) == (len(rendered), 0)
        assert f["passed"] == sum(r.outcome is RenditionOutcome.PASSED for r in rendered)
        assert f["fallback"] == sum(r.outcome is RenditionOutcome.FALLBACK for r in rendered)
        assert f["first_attempt_passed"] == sum(r.attempts[0].verdict.passed for r in rendered)
        assert f["model_requests"] == fan_calls
    else:
        assert s.personas == {}
    assert s.model_requests == analyst_calls and s.total_requests == len(client.requests)


def test_a_persona_attempt_needs_only_its_one_request_of_the_budget():
    budget = CallBudget(3, per_attempt=2)  # the Analyst reads the facts with a tool
    budget.calls = 2
    assert budget.why_not() == "the run's 3 model calls are spent"  # no room for the Analyst
    assert budget.why_not(1) is None  # one request left is enough for the Persona Editor
    assert budget.why_not(3) == budget.why_not()  # never more than an attempt may make
    budget.calls = 3
    assert budget.why_not(1) == "the run's 3 model calls are spent"


def test_the_budget_counts_the_persona_editor_s_requests():
    ids = [c.moment_id for c in moments()]
    client = scripted_with_fan({m: ["pass"] for m in ids}, {ids[0]: ["pass"]})
    explained, handoffs = run_workflow(client, max_calls=4, personas=(FAN,))
    assert len(client.requests) == 4  # 3 narratives, then 1 rendition: the cap holds
    outcomes = [e.case.renditions[0].outcome for e in explained]
    assert outcomes == [RenditionOutcome.PASSED] + [RenditionOutcome.FALLBACK] * 2
    for e in explained[1:]:  # no call, so no retry: the narrative stands in at once
        (a,) = e.case.renditions[0].attempts
        assert not a.called_model and "4 model calls are spent" in a.error.detail
        assert e.for_persona(FAN) == e.case.narrative
    s = summarize(handoffs)
    assert (s.personas["fan"]["skipped"], s.total_requests) == (2, 4)


def test_the_persona_editor_s_failures_count_for_the_breaker():
    ids = [c.moment_id for c in moments()]
    analyst = {m: ["pass"] for m in ids}
    fan = {ids[0]: ["transport"], ids[1]: ["timeout"], ids[2]: ["rate_limited"]}
    client = scripted_with_fan(analyst, fan)
    explained, _ = run_workflow(client, personas=(FAN,))
    assert len(client.requests) == 6  # 3 narratives, 3 renditions without an answer
    for e in explained:  # each rendition's retry is skipped: the narrative stands in
        r = e.case.renditions[0]
        assert [kind_of(a) for a in r.attempts][1:] == ["skipped"]
        assert "circuit breaker" in r.attempts[1].error.detail
        assert r.outcome is RenditionOutcome.FALLBACK


def test_without_personas_there_is_no_persona_editor_and_no_rendition():
    explained, handoffs = run_workflow(FakeChatClient(echo))
    assert all(e.case.renditions == () for e in explained)
    assert Role.PERSONA_EDITOR not in {h.receiver for h in handoffs}
    assert summarize(handoffs).personas == {}


def test_every_echo_rendition_of_seeds_0_and_3_passes():
    """Real run, whole matches: the `--fake` Persona Editor copies the caption, which passes."""
    for seed in (0, 3):
        m = match(seed)
        explained, handoffs = run_workflow(FakeChatClient(echo), until=None, m=m, personas=("fan",))
        assert all(e.case.renditions[0].outcome is RenditionOutcome.PASSED for e in explained)
        assert summarize(handoffs).personas["fan"]["passed"] == len(explained)


def test_one_pace_spaces_both_agents():
    ids = [c.moment_id for c in moments()]
    analyst = {ids[0]: ["rejected", "pass"], ids[1]: ["pass"], ids[2]: ["pass"]}
    # round 2: the Analyst's retry of the first moment and two renditions, side by side
    client = scripted_with_fan(analyst, {m: ["pass"] for m in ids})
    starts = []
    clock = itertools.count(0, 0.001)  # each request takes no time on this clock

    async def sleep(seconds):
        nonlocal now
        now += max(0.0, seconds)
        await asyncio.sleep(0)  # yield, as a real sleep does: the other agent may run meanwhile

    now = 0.0

    def tick():
        return now + next(clock)

    original = client._inner_get_response

    async def stamped(**kwargs):
        starts.append(tick())
        return await original(**kwargs)

    client._inner_get_response = stamped
    with mock.patch.object(workflow, "_clock", tick), mock.patch.object(workflow, "_sleep", sleep):
        run_workflow(client, personas=(FAN,), pace_s=35)
    gaps = [b - a for a, b in itertools.pairwise(starts)]
    assert len(starts) == 7 and all(g >= 35 - 1e-6 for g in gaps), gaps


def test_two_agents_side_by_side_never_pass_the_cap():
    """Round 2 holds the Analyst's retry and a rendition at once; with one request left, only
    one of them may call."""
    ids = [c.moment_id for c in moments()]
    analyst = {ids[0]: ["rejected", "pass"], ids[1]: ["pass"], ids[2]: ["pass"]}
    client = scripted_with_fan(analyst, {m: ["pass"] for m in ids})
    explained, handoffs = run_workflow(client, max_calls=4, personas=(FAN,))
    assert len(client.requests) == 4
    s = summarize(handoffs)
    assert s.total_requests == 4 and s.skipped + s.personas["fan"]["skipped"] >= 1
    for e in explained:
        assert check(e.for_persona(FAN), e.case, moment_evidence(match(7), e.case)).passed


@settings(deadline=None)
@given(
    st.lists(st.lists(st.sampled_from(KINDS), min_size=3, max_size=3), min_size=3, max_size=3),
    st.lists(st.lists(st.sampled_from(KINDS), min_size=2, max_size=2), min_size=3, max_size=3),
    st.integers(0, 12),
)
def test_any_script_and_cap_keep_the_cap_and_show_only_what_passed(analyst_drawn, fan_drawn, cap):
    ids = [c.moment_id for c in moments()]
    analyst = dict(zip(ids, analyst_drawn, strict=True))
    fan = dict(zip(ids, fan_drawn, strict=True))
    client = scripted_with_fan(analyst, fan)
    explained, handoffs = run_workflow(client, max_calls=cap, personas=(FAN,))
    assert len(client.requests) <= cap
    for e in explained:
        case = e.case
        assert check(e.for_persona(FAN), case, moment_evidence(match(7), case)).passed
        assert len(case.attempts) <= MAX_ATTEMPTS
        for r in case.renditions:
            assert not r.is_open and len(r.attempts) <= PERSONA_ATTEMPTS
            shown = e.for_persona(FAN)
            assert shown == (
                r.attempts[-1].draft if r.attempts[-1].verdict.passed else case.narrative
            )
    s = summarize(handoffs)  # every chain checks, including each fallback's policy
    assert s.total_requests == len(client.requests) and s.crashed == ()


def test_a_fatal_call_of_the_persona_editor_stops_the_run():
    ids = [c.moment_id for c in moments()]
    denied = httpx2.Response(401, request=REQUEST)
    fatal = caused(anthropic.AuthenticationError("expired", response=denied, body=None), "401")
    script = {m: [echo] for m in ids} | {f"{ids[0]}/fan": [fatal]}
    client = FakeChatClient(by_moment(script))
    with tempfile.TemporaryDirectory() as tmp:
        log = HandoffLog(Path(tmp) / "handoffs.jsonl")
        with pytest.raises(FatalCallError, match="AuthenticationError"):
            asyncio.run(explain(match(7), client, log, run_id="r1", until=UNTIL, personas=(FAN,)))
        summary = summarize(read_handoffs(log.path), stopped="401")
    assert len(client.requests) == 4  # the 3 narratives, then the fatal rendition: no call after
    assert summary.moments == 0 and set(summary.crashed) == set(ids)
