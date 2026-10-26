import dataclasses

import pytest
from explain_strategies import DRAFT, NO_DRAFT, REJECT, case

from matchlens.explain.log import Handoff, Role
from matchlens.explain.state import Attempt, CallError, CallFailure, Verdict
from matchlens.explain.summary import PRICES, check_chain, summarize

TS = "2026-10-22T00:00:00.000+00:00"
D, A, G, R = Role.DETECTOR, Role.ANALYST, Role.GUARD, Role.RENDER
PASS = Verdict(True)


def tried(n, verdict, model="claude-haiku-5-5", tokens=(1000, 100), latency=500, error=None):
    """Attempt `n` as the Guard judged it; a failed call when `error` is a code."""
    draft = None if error else DRAFT
    failure = None if error is None else CallFailure(error, "x")
    return Attempt(n, model, draft, failure, verdict, tokens[0], tokens[1], latency)


def chain(moment="m7-k1", attempts=(), end=True, **changes):
    """The lines of one moment: in, then per attempt one to the Guard and one back or out."""
    c = case(moment_id=moment, **changes)
    lines = [Handoff(TS, D, A, c)]
    for i, a in enumerate(attempts):
        c = c.with_attempt(dataclasses.replace(a, verdict=None))
        lines.append(Handoff(TS, A, G, c))
        c = c.with_verdict(a.verdict)
        if i < len(attempts) - 1:
            lines.append(Handoff(TS, G, A, c))
        elif end:
            lines.append(Handoff(TS, G, R, c.stats_only() if c.is_open else c))
    return lines


def test_a_run_s_counts_rates_tokens_and_cost():
    lines = (
        chain("m7-k1", [tried(1, PASS)])
        + chain("m7-k2", [tried(1, REJECT), tried(2, PASS, tokens=(2000, 300), latency=700)])
        + chain("m7-k3", [tried(1, REJECT), tried(2, REJECT), tried(3, REJECT)])
        + chain("m7-k4", [tried(1, NO_DRAFT, tokens=(0, 0), latency=900, error="timeout")])
    )
    s = summarize(lines)
    assert (s.run_id, s.match_id, s.models) == ("r1", "m7", ("claude-haiku-5-5",))
    assert (s.moments, s.narratives, s.stats_only, s.crashed) == (4, 2, 2, ())
    assert (s.first_attempt_passed, s.first_attempt_pass_rate, s.final_pass_rate) == (1, 0.25, 0.5)
    assert (s.attempts, s.model_calls, s.skipped) == (7, 7, 0)
    assert s.errors == {"timeout": 1}
    assert s.reasons == {"no_draft": 1, "number_not_cited": 4}
    assert (s.tokens_in, s.tokens_out) == (1000 * 5 + 2000, 100 * 5 + 300)
    price_in, price_out = PRICES["claude-haiku-5-5"]
    assert s.cost_usd == round((7000 * price_in + 800 * price_out) / 1e6, 6)
    # a moment's latency is the sum of its attempts': 500, 1200, 1500, 900
    assert (s.latency_ms_p50, s.latency_ms_p95) == (900, 1500)


@pytest.mark.parametrize(
    ("latencies", "p50", "p95"),
    [([7], 7, 7), ([1, 2], 1, 2), (list(range(1, 21)), 10, 19), (list(range(1, 22)), 11, 20)],
)
def test_percentiles_are_nearest_rank(latencies, p50, p95):
    lines = [
        line
        for i, ms in enumerate(latencies)
        for line in chain(f"m7-k{i}", [tried(1, PASS, latency=ms)])
    ]
    s = summarize(lines)
    assert (s.latency_ms_p50, s.latency_ms_p95) == (p50, p95)


def test_a_moment_without_its_render_line_is_crashed_not_counted():
    lines = chain("m7-k1", [tried(1, PASS)]) + chain("m7-k2", [tried(1, REJECT)], end=False)
    s = summarize(lines, stopped="AuthenticationError: expired")
    assert (s.moments, s.narratives, s.crashed) == (1, 1, ("m7-k2",))
    assert (s.attempts, s.tokens_in) == (2, 2000)  # a crashed moment's calls count too
    assert s.stopped == "AuthenticationError: expired"
    assert summarize(chain("m7-k3"), stopped="x").crashed == ("m7-k3",)


def test_every_reason_of_a_rejected_attempt_counts():
    two = Verdict(False, (*REJECT.reasons, dataclasses.replace(REJECT.reasons[0], code="too_long")))
    s = summarize(chain(attempts=[tried(1, two), tried(2, PASS)]))
    assert s.reasons == {"number_not_cited": 1, "too_long": 1}


def test_skipped_attempts_are_no_calls():
    skipped = tried(1, NO_DRAFT, tokens=(0, 0), latency=0, error=CallError.SKIPPED)
    s = summarize(chain(attempts=[skipped]))
    assert (s.attempts, s.model_calls, s.skipped, s.stats_only) == (1, 0, 1, 1)
    assert s.errors == {"skipped": 1}


def test_an_unknown_model_has_no_cost_and_the_fake_costs_nothing():
    assert summarize(chain(attempts=[tried(1, PASS, model="gpt-x")])).cost_usd is None
    assert summarize(chain(attempts=[tried(1, PASS, model="fake")])).cost_usd == 0.0
    sonnet = summarize(chain(attempts=[tried(1, PASS, model="claude-sonnet-5-5")]))
    assert sonnet.cost_usd == round((1000 * 2.00 + 100 * 10.00) / 1e6, 6)


def test_an_empty_log_has_no_rates():
    s = summarize([])
    assert (s.run_id, s.moments, s.first_attempt_pass_rate, s.latency_ms_p50) == (
        None,
        0,
        None,
        None,
    )
    assert s.to_dict()["final_pass_rate"] is None


def test_the_summary_is_json():
    d = summarize(chain(attempts=[tried(1, PASS)])).to_dict()
    assert d["models"] == ["claude-haiku-5-5"] and d["crashed"] == []
    assert d["first_attempt_pass_rate"] == d["final_pass_rate"] == 1.0


# broken chains


def test_a_chain_starts_at_the_detector():
    with pytest.raises(ValueError, match="first line"):
        check_chain(chain(attempts=[tried(1, PASS)])[1:])


def test_each_line_is_sent_by_the_last_receiver():
    lines = chain(attempts=[tried(1, REJECT), tried(2, PASS)])  # D→A, A→G, G→A, A→G, G→R
    with pytest.raises(ValueError, match="sends"):
        check_chain([*lines[:2], *lines[3:]])  # the Guard's line back to the Analyst is gone


def test_a_case_keeps_its_identity():
    lines = chain(attempts=[tried(1, PASS)])
    facts = ({"fact_id": "m7/goal", "display": "2-0"}, lines[1].case.facts[1])
    changed = Handoff(TS, A, G, dataclasses.replace(lines[1].case, facts=facts))
    with pytest.raises(ValueError, match="identity"):
        check_chain([lines[0], changed, lines[2]])


def test_the_analyst_adds_one_attempt_and_leaves_the_earlier_ones():
    lines = chain(attempts=[tried(1, REJECT), tried(2, PASS)])
    first, second = lines[3].case.attempts
    rewritten = (dataclasses.replace(first, latency_ms=1), second)
    line = Handoff(TS, A, G, dataclasses.replace(lines[3].case, attempts=rewritten))
    with pytest.raises(ValueError, match="single step"):
        check_chain([*lines[:3], line])


def test_the_guard_adds_only_its_verdict():
    lines = chain(attempts=[tried(1, PASS)])  # D→A, A→G, G→R
    [judged] = lines[2].case.attempts
    edited = (dataclasses.replace(judged, tokens_in=1),)
    line = Handoff(TS, G, R, dataclasses.replace(lines[2].case, attempts=edited))
    with pytest.raises(ValueError, match="single step"):
        check_chain([*lines[:2], line])


def test_nothing_follows_the_render_line():
    lines = chain("m7-k1", [tried(1, PASS)])
    with pytest.raises(ValueError, match="first line|after"):
        summarize(lines + chain("m7-k1", [tried(1, PASS)]))


def test_one_log_is_one_run():
    with pytest.raises(ValueError, match="one run"):
        summarize(chain("m7-k1", [tried(1, PASS)]) + chain("m7-k2", [tried(1, PASS)], run_id="r2"))


def test_the_guard_leaves_the_earlier_attempts():
    lines = chain(attempts=[tried(1, REJECT), tried(2, PASS)])  # D→A, A→G, G→A, A→G, G→R
    first, second = lines[4].case.attempts
    rewritten = (dataclasses.replace(first, tokens_in=1), second)
    line = Handoff(TS, G, R, dataclasses.replace(lines[4].case, attempts=rewritten))
    with pytest.raises(ValueError, match="single step"):
        check_chain([*lines[:4], line])


# --- renditions (M5) ---------------------------------------------------------------------------

P = Role.PERSONA_EDITOR


def with_fan(lines, fan_attempts, model="claude-sonnet-5-5"):
    """`lines` of a narrative, its render line replaced by the fan's rendition: the Guard opens
    it, then per attempt one line to the Guard and one back or out."""
    *body, last = lines
    c = last.case.with_personas(["fan"])
    out = [*body, Handoff(TS, G, P, c)]
    for a in fan_attempts:
        r = c.pending_rendition.with_attempt(dataclasses.replace(a, verdict=None, model=model))
        c = c.with_rendition(r)
        out.append(Handoff(TS, P, G, c))
        r = r.with_verdict(a.verdict)
        if r.is_open and not r.can_retry:
            r = r.fallback()
        c = c.with_rendition(r)
        out.append(Handoff(TS, G, P if c.pending_rendition else R, c))
    return out


def test_each_persona_is_counted_like_the_analyst_and_the_totals_add_every_agent():
    lines = (
        with_fan(chain("m7-k1", [tried(1, PASS)]), [tried(1, PASS, tokens=(500, 50), latency=300)])
        + with_fan(chain("m7-k2", [tried(1, PASS)]), [tried(1, REJECT), tried(2, PASS)])
        + with_fan(chain("m7-k3", [tried(1, PASS)]), [tried(1, REJECT), tried(2, REJECT)])
        + chain("m7-k4", [tried(1, REJECT), tried(2, REJECT), tried(3, REJECT)])
    )
    s = summarize(lines)
    assert (s.moments, s.narratives, s.attempts) == (4, 3, 6)  # the Analyst's, as before
    fan = s.personas["fan"]
    assert (fan["renditions"], fan["passed"], fan["fallback"], fan["open"]) == (3, 2, 1, 0)
    assert (fan["first_attempt_passed"], fan["attempts"], fan["model_calls"]) == (1, 5, 5)
    assert fan["reasons"] == {"number_not_cited": 3}
    assert (fan["tokens_in"], fan["tokens_out"]) == (500 + 4 * 1000, 50 + 4 * 100)
    sonnet_in, sonnet_out = PRICES["claude-sonnet-5-5"]
    assert fan["cost_usd"] == round((4500 * sonnet_in + 450 * sonnet_out) / 1e6, 6)
    # a rendition's latency is the sum of its attempts': 300, 1000, 1000
    assert (fan["latency_ms_p50"], fan["latency_ms_p95"]) == (1000, 1000)
    assert s.total_tokens_in == s.tokens_in + fan["tokens_in"]
    assert s.total_cost_usd == round(s.cost_usd + fan["cost_usd"], 6)


def test_a_persona_step_adds_one_attempt_to_its_rendition_and_nothing_else():
    lines = with_fan(chain(attempts=[tried(1, PASS)]), [tried(1, PASS)])  # D A G→P P→G G→R
    sent = lines[3]
    [judged] = sent.case.attempts
    edited = dataclasses.replace(sent.case, attempts=(dataclasses.replace(judged, tokens_in=1),))
    with pytest.raises(ValueError, match="single step"):
        check_chain([*lines[:3], Handoff(TS, P, G, edited)])
    r = sent.case.renditions[0]
    twice = r.with_verdict(REJECT).with_attempt(dataclasses.replace(tried(2, REJECT), verdict=None))
    with pytest.raises(ValueError, match="single step"):
        check_chain([*lines[:3], Handoff(TS, P, G, sent.case.with_rendition(twice))])


def test_the_guard_adds_only_its_verdict_to_a_rendition():
    lines = with_fan(chain(attempts=[tried(1, PASS)]), [tried(1, PASS)])
    out = lines[4]
    r = out.case.renditions[0]
    edited = dataclasses.replace(r, attempts=(dataclasses.replace(r.attempts[0], latency_ms=1),))
    with pytest.raises(ValueError, match="single step"):
        check_chain([*lines[:4], Handoff(TS, G, R, out.case.with_rendition(edited))])


def test_the_guard_opens_renditions_fresh_and_falls_back_only_without_a_retry():
    lines = with_fan(chain(attempts=[tried(1, PASS)]), [tried(1, REJECT), tried(2, REJECT)])
    # D→A, A→G, G→P (fresh), P→G, G→P (retry), P→G, G→R (fallback)
    opened = lines[2].case
    early = opened.with_rendition(
        opened.renditions[0]
        .with_attempt(dataclasses.replace(tried(1, REJECT), verdict=None))
        .with_verdict(REJECT)
    )
    with pytest.raises(ValueError, match="single step"):  # opened with an attempt already in it
        check_chain([*lines[:2], Handoff(TS, G, P, early)])
    first_judged = lines[4].case.renditions[0]  # rejected once, a retry left
    too_soon = lines[4].case.with_rendition(first_judged.fallback())
    with pytest.raises(ValueError, match="single step"):  # a fallback while a retry is left
        check_chain([*lines[:4], Handoff(TS, G, R, too_soon)])
    check_chain(lines)  # the policy's own fallback, after the retry
