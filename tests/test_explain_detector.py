import dataclasses
import functools
import json
from collections import Counter
from unittest import mock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from real import match

from matchlens.events import MAX_PERIOD_MS, PERIODS, EventType, Outcome, display_clock
from matchlens.explain import detector
from matchlens.explain.analyst import moment_prompt
from matchlens.explain.detector import detect
from matchlens.explain.guard import check, moment_evidence, stats_only_draft
from matchlens.explain.state import MomentCase
from matchlens.facts import brief, display_minute, facts_at
from matchlens.generator import generate_match

SEEDS = (0, 1, 2, 7)  # each has a shot that hits the woodwork; 7 has five goals
KINDS = {EventType.GOAL: "goal", EventType.SAVE: "save"}

_facts: dict = {}


def memo_facts_at(m, period, clock_ms):
    """`facts_at`, computed once per instant: it counts only the events up to `clock_ms`
    (`test_facts_at_know_only_the_past`), so a prefix of the match has the same facts there;
    `test_a_cut_match_gives_the_same_moments` runs the real one on a prefix."""
    key = (m.meta.match_id, period, clock_ms)
    if key not in _facts:
        _facts[key] = facts_at(m, period, clock_ms)
    return _facts[key]


def fast_detect(m, run_id="r1", until=None):
    with mock.patch.object(detector, "facts_at", memo_facts_at):
        return detect(m, run_id, until)


@functools.cache
def full(seed: int) -> tuple[MomentCase, ...]:
    return tuple(detect(match(seed), "r1"))


def kind(m, case: MomentCase) -> str:
    events = {e.event_id: e for e in m.events}
    last = events[case.trigger_ids[-1]]
    return KINDS.get(last.type, "woodwork")


def prefix(m, until):
    return dataclasses.replace(
        m, events=tuple(e for e in m.events if (e.period, e.clock_ms) <= until)
    )


@st.composite
def untils(draw):
    """A seed and an instant: anywhere, or on a moment's start or end, or one millisecond off."""
    seed = draw(st.sampled_from(SEEDS))
    if draw(st.booleans()):
        case = draw(st.sampled_from(full(seed)))
        clock = draw(st.sampled_from((case.start_ms, case.end_ms))) + draw(
            st.sampled_from((-1, 0, 1))
        )
        return seed, (case.period, min(MAX_PERIOD_MS, max(0, clock)))
    return seed, (draw(st.sampled_from(PERIODS)), draw(st.integers(0, MAX_PERIOD_MS)))


# properties


@settings(deadline=None)  # the first examples generate the matches
@given(untils())
def test_a_prefix_yields_the_full_match_s_moments_that_end_inside_it(drawn):
    seed, until = drawn
    got = fast_detect(match(seed), until=until)
    assert got == [c for c in full(seed) if (c.period, c.end_ms) <= until]


@settings(deadline=None)  # the first examples generate the matches
@given(untils())
def test_the_detector_reads_only_the_prefix(drawn):
    seed, until = drawn
    m = match(seed)
    cut = prefix(m, until)
    assert fast_detect(cut, until=until) == fast_detect(m, until=until)
    # without `until`, a prefix ends at its latest event
    latest = max(((e.period, e.clock_ms) for e in cut.events), default=(1, 0))
    assert fast_detect(cut) == fast_detect(m, until=latest)


@settings(deadline=None)  # the first examples generate the matches
@given(untils())
def test_triggers_lie_in_the_prefix(drawn):
    seed, until = drawn
    m = match(seed)
    events = {e.event_id: e for e in m.events}
    for case in fast_detect(m, until=until):
        triggers = [events[t] for t in case.trigger_ids]
        assert all((t.period, t.clock_ms) <= (case.period, case.end_ms) <= until for t in triggers)
        shot = triggers[0]
        assert shot.type is EventType.SHOT and shot.period == case.period
        assert case.start_ms == shot.clock_ms
        if len(triggers) == 2:
            end = triggers[1]
            assert end.type in KINDS and end.related == shot.event_id
            assert (
                shot.outcome
                is {EventType.GOAL: Outcome.GOAL, EventType.SAVE: Outcome.SAVED}[end.type]
            )
            assert case.end_ms == end.clock_ms
        else:
            assert len(triggers) == 1 and shot.outcome is Outcome.WOODWORK
            assert case.end_ms == shot.clock_ms + shot.duration_ms


@settings(deadline=None)  # the first examples generate the matches
@given(untils())
def test_the_detector_is_deterministic(drawn):
    seed, until = drawn
    first = fast_detect(match(seed), until=until)
    assert fast_detect(match(seed), until=until) == first
    assert [MomentCase.from_dict(json.loads(json.dumps(c.to_dict()))) for c in first] == first


# examples


def test_a_fresh_match_gives_the_same_moments():
    for seed in SEEDS:  # the properties reuse one cached match per seed
        assert detect(generate_match(seed), "r1") == list(full(seed))


def test_every_goal_save_and_woodwork_is_one_moment():
    for seed in SEEDS:
        m = match(seed)
        cases = full(seed)
        want = Counter(KINDS.get(e.type) for e in m.events if e.type in KINDS)
        want["woodwork"] = sum(
            e.outcome is Outcome.WOODWORK for e in m.events if e.type is EventType.SHOT
        )
        assert Counter(kind(m, c) for c in cases) == want
        assert len({c.moment_id for c in cases}) == len(cases)
        assert [(c.period, c.end_ms) for c in cases] == sorted((c.period, c.end_ms) for c in cases)
        assert all(c.run_id == "r1" and c.match_id == m.meta.match_id and c.is_open for c in cases)


def test_m7_moments():
    """Pinned: the first goal, the woodwork and how many there are."""
    cases = full(7)
    first = cases[0]
    assert (first.moment_id, first.trigger_ids) == ("m7-k00072", ("m7-e00072", "m7-e00073"))
    assert (first.period, first.display_clock, first.end_ms) == (1, "04:18", 258_931)
    wood = next(c for c in cases if len(c.trigger_ids) == 1)
    assert (wood.moment_id, wood.trigger_ids) == ("m7-k01381", ("m7-e01381",))
    assert (wood.period, wood.start_ms, wood.end_ms) == (2, 1_883_402, 1_883_402 + 1_324)
    assert len(cases) == 15  # 5 goals, 9 saves, 1 woodwork


def test_a_goal_is_a_moment_from_its_goal_event_on():
    m = match(7)
    case = full(7)[0]
    shot_ms = case.start_ms
    assert [c.moment_id for c in fast_detect(m, until=(1, case.end_ms))][-1] == case.moment_id
    assert case.moment_id not in [c.moment_id for c in fast_detect(m, until=(1, case.end_ms - 1))]
    assert case.moment_id not in [c.moment_id for c in fast_detect(m, until=(1, shot_ms))]


def test_a_woodwork_shot_is_a_moment_once_the_ball_arrives():
    m = match(7)
    case = next(c for c in full(7) if len(c.trigger_ids) == 1)
    ids = lambda clock: [c.moment_id for c in fast_detect(m, until=(2, clock))]  # noqa: E731
    assert case.moment_id in ids(case.end_ms)
    assert case.moment_id not in ids(case.end_ms - 1)
    assert case.moment_id not in ids(
        case.start_ms
    )  # the shot is in the prefix, its flight is not over
    assert ids(case.end_ms) == ids(case.end_ms - 1) + [case.moment_id]


def test_the_facts_are_the_engine_s_at_the_moment_s_end():
    m = match(7)
    for case in full(7):
        engine = facts_at(m, case.period, case.end_ms)
        assert list(case.facts) == [json.loads(json.dumps(brief(f))) for f in engine]
        names = Counter(f["name"] for f in case.facts)
        assert names["clock"] == names["minute"] == 1 and names["shirt_number"] == 22
        minute = next(f for f in case.facts if f["name"] == "minute")
        assert minute["display"] == display_minute(case.period, case.end_ms)
        assert case.display_clock == display_clock(case.period, case.end_ms)
        assert all("event_ids" not in f and "frame_ids" not in f for f in case.facts)


def test_brief_drops_the_id_lists_and_counts_them():
    f = next(f for f in facts_at(match(7), 1, 258_931) if f.name == "possession")
    got = brief(f)
    assert (got["event_count"], got["frame_count"]) == (len(f.event_ids), len(f.frame_ids))
    assert got["event_count"] > 0
    assert {k: v for k, v in got.items() if not k.endswith("_count")} == {
        k: v for k, v in f.to_dict().items() if k not in ("event_ids", "frame_ids")
    }


def test_until_defaults_to_the_match_s_last_event():
    m = match(1)
    last = m.events[-1]
    assert fast_detect(m) == fast_detect(m, until=(last.period, last.clock_ms)) == list(full(1))
    assert fast_detect(dataclasses.replace(m, events=())) == []


def test_a_cut_match_gives_the_same_moments():
    """The real `facts_at`, unmemoized, on a match cut right after the woodwork of m7."""
    wood = next(c for c in full(7) if len(c.trigger_ids) == 1)
    until = (wood.period, wood.end_ms)
    got = detect(prefix(match(7), until), "r1", until)
    assert got == [c for c in full(7) if (c.period, c.end_ms) <= until]
    assert got[-1] == wood


def test_until_may_be_a_json_list():
    case = full(1)[0]
    until = [case.period, case.end_ms]
    assert fast_detect(match(1), until=until) == fast_detect(match(1), until=tuple(until))


def test_a_goal_without_its_shot_is_refused():
    m = match(7)
    shot = full(7)[0].trigger_ids[0]
    cut = dataclasses.replace(m, events=tuple(e for e in m.events if e.event_id != shot))
    with pytest.raises(ValueError, match=f"{shot} is no shot"):
        detect(cut, "r1")


@pytest.mark.parametrize("until", [(0, 0), (3, 0), (1, -1), (2, MAX_PERIOD_MS + 1)])
def test_an_impossible_instant_is_refused(until):
    with pytest.raises(ValueError):
        detect(match(1), "r1", until)


@pytest.mark.parametrize("until", [(1, 0), (2, MAX_PERIOD_MS)])
def test_the_edges_of_the_clock_are_instants(until):
    got = fast_detect(match(1), until=until)
    assert got == [c for c in full(1) if (c.period, c.end_ms) <= until]


def test_every_moment_goes_through_the_guard_and_the_analyst_prompt():
    """Real run: each moment's facts are the engine's to the Guard, its stats-only cue passes,
    and the Analyst's prompt names its triggers with the shot's outcome."""
    for seed in SEEDS:
        m = match(seed)
        for case in full(seed):
            evidence = moment_evidence(m, case)
            assert check(stats_only_draft(case, evidence), case, evidence).passed
            prompt = moment_prompt(case, m)
            assert all(f"- {t}: " in prompt for t in case.trigger_ids)
            if kind(m, case) == "woodwork":
                assert f"- {case.trigger_ids[0]}: shot by " in prompt and ", woodwork\n" in prompt
