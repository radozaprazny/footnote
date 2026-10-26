import dataclasses
import re

import pytest
import real
from hypothesis import given, settings
from hypothesis import strategies as st

from matchlens.events import EventType
from matchlens.explain.guard import _PHRASE
from matchlens.facts import facts_at
from matchlens.stats.flow import momentum
from matchlens.stats.readings import (
    VOCABULARY,
    chaos_reading,
    goal_reading,
    momentum_reading,
    possession_reading,
    score_reading,
)

MIRROR = {
    "leading": "trailing",
    "level": "level",
    "on_top": "pinned_back",
    "evenly_matched": "evenly_matched",
    "more_of_the_ball": "less_of_the_ball",
    "even_share": "even_share",
}
MIRROR |= {b: a for a, b in MIRROR.items()}


def test_the_vocabulary_is_the_shared_list_of_phrases():
    assert VOCABULARY == {
        "leading": "in the lead", "level": "on level terms", "trailing": "chasing the game",
        "take_the_lead": "take the lead", "equalise": "equalise",
        "extend_the_lead": "extend the lead", "pull_one_back": "pull one back",
        "on_top": "on top", "pinned_back": "pinned back", "evenly_matched": "evenly matched",
        "end_to_end": "end-to-end", "patient": "patient build-up", "steady": "a steady tempo",
        "more_of_the_ball": "more of the ball", "less_of_the_ball": "less of the ball",
        "even_share": "an even share of the ball",
    }  # fmt: skip
    phrases = list(VOCABULARY.values())
    assert len(set(phrases)) == len(phrases)
    for phrase in phrases:
        assert not re.search(r"\d", phrase) and phrase == phrase.lower()
        # the Guard finds each phrase whole, and no shorter one inside it
        assert [m.group() for m in _PHRASE.finditer(f"x {phrase} x")] == [phrase]


@pytest.mark.parametrize(
    ("difference", "code"), [(-2, "trailing"), (-1, "trailing"), (0, "level"), (1, "leading")]
)
def test_score_reading_on_both_sides_of_level(difference, code):
    assert score_reading(difference) == code


@pytest.mark.parametrize(
    ("before", "code"),
    [
        (-3, "pull_one_back"),
        (-2, "pull_one_back"),
        (-1, "equalise"),
        (0, "take_the_lead"),
        (1, "extend_the_lead"),
        (2, "extend_the_lead"),
    ],
)
def test_goal_reading_from_the_difference_before_the_goal(before, code):
    assert goal_reading(before) == code


@pytest.mark.parametrize(
    ("percent", "weight", "code"),
    [
        (100, 9, None),  # below the minimum weight nobody is on top
        (0, 9, None),
        (69, 10, "evenly_matched"),
        (70, 10, "on_top"),
        (30, 10, "pinned_back"),
        (31, 10, "evenly_matched"),
        (50, 54, "evenly_matched"),
    ],
)
def test_momentum_reading_on_both_sides_of_each_line(percent, weight, code):
    assert momentum_reading(percent, weight) == code


@pytest.mark.parametrize(
    ("chaos", "code"),
    [(43, "patient"), (44, "steady"), (56, "steady"), (57, "end_to_end"), (0, "patient")],
)
def test_chaos_reading_on_both_sides_of_each_line(chaos, code):
    assert chaos_reading(chaos) == code


@pytest.mark.parametrize(
    ("percent", "code"),
    [
        (45, "less_of_the_ball"),
        (46, "even_share"),
        (54, "even_share"),
        (55, "more_of_the_ball"),
    ],
)
def test_possession_reading_on_both_sides_of_each_line(percent, code):
    assert possession_reading(percent) == code


@given(st.integers(-20, 20))
def test_score_readings_of_the_two_teams_mirror_each_other(difference):
    assert MIRROR[score_reading(difference)] == score_reading(-difference)


@given(st.integers(0, 100), st.integers(0, 200))
def test_momentum_readings_of_the_two_teams_mirror_each_other(percent, weight):
    mine, theirs = momentum_reading(percent, weight), momentum_reading(100 - percent, weight)
    assert (mine is None) == (theirs is None) == (weight < 10)
    assert mine is None or MIRROR[mine] == theirs


@given(st.integers(0, 100))
def test_possession_readings_of_the_two_teams_mirror_each_other(percent):
    assert MIRROR[possession_reading(percent)] == possession_reading(100 - percent)


@given(st.integers(-20, 20), st.integers(0, 100), st.integers(0, 200))
def test_every_reading_is_a_code_of_the_vocabulary(difference, value, weight):
    codes = [
        score_reading(difference),
        goal_reading(difference),
        chaos_reading(value),
        possession_reading(value),
        momentum_reading(value, weight),
    ]
    assert all(c in VOCABULARY for c in codes if c is not None)


# --- readings among the facts of real matches ----------------------------------------------------

SEEDS = (0, 1, 3)  # the matches of the measured Foundry runs
READS = {
    "score_reading": "goals",
    "possession_reading": "possession",
    "momentum_reading": "momentum",
    "chaos_reading": "chaos",
}


def instants(seed: int) -> list[tuple[int, int]]:
    return sorted({(e.period, e.clock_ms) for e in real.match(seed).events})


@settings(deadline=None)
@given(st.data())
def test_a_reading_exists_exactly_where_its_fact_does(data):
    seed = data.draw(st.sampled_from(SEEDS))
    m = real.match(seed)
    period, clock_ms = data.draw(st.sampled_from(instants(seed)))
    got = {f.fact_id: f for f in facts_at(m, period, clock_ms)}
    readings = {i: f for i, f in got.items() if f.name.endswith("_reading")}
    for fact_id, f in readings.items():
        assert f.display == VOCABULARY[f.value] and f.unit == "" and f.source == "engine"
        if f.name == "goal_reading":
            continue  # checked below
        read = got[fact_id.replace(f"/{f.name}/", f"/{READS[f.name]}/")]
        assert (f.team, f.start, f.end, f.event_ids) == (
            read.team,
            read.start,
            read.end,
            read.event_ids if f.name != "score_reading" else got[_score_id(fact_id)].event_ids,
        )
    for fact_id, f in got.items():
        if f.name in ("possession", "chaos", "goals"):
            name = {"possession": "possession_reading", "chaos": "chaos_reading"}
            reading_id = fact_id.replace(f"/{f.name}/", f"/{name.get(f.name, 'score_reading')}/")
            assert reading_id in readings, reading_id
        if f.name == "momentum":
            scope = fact_id.split("/")[2]
            events = [e for e in m.events if (e.period, e.clock_ms) <= (period, clock_ms)]
            window = () if scope.startswith("to-") else (clock_ms - 300_000, clock_ms)
            weight = sum(momentum(m.meta, events, period if window else None, *window).weights)
            assert (fact_id.replace("/momentum/", "/momentum_reading/") in readings) == (
                weight >= 10
            )
    goals_now = [
        e
        for e in m.events
        if e.type is EventType.GOAL and (e.period, e.clock_ms) == (period, clock_ms)
    ]
    goal_readings = [f for f in readings.values() if f.name == "goal_reading"]
    assert [(f.team, f.end) for f in goal_readings] == [
        (g.team, (g.period, g.clock_ms)) for g in goals_now
    ]


def _score_id(reading_id: str) -> str:
    """The score fact of a score reading's scope."""
    match_id, _, scope, _ = reading_id.split("/")
    return f"{match_id}/score/{scope}/all"


@settings(deadline=None, max_examples=20)
@given(st.data())
def test_readings_are_deterministic_over_a_prefix(data):
    seed = data.draw(st.sampled_from(SEEDS))
    period, clock_ms = data.draw(st.sampled_from(instants(seed)))
    m = real.match(seed)
    past = tuple(e for e in m.events if (e.period, e.clock_ms) <= (period, clock_ms))
    cut = dataclasses.replace(m, events=past)
    mine = [f for f in facts_at(m, period, clock_ms) if f.name.endswith("_reading")]
    assert mine == [f for f in facts_at(cut, period, clock_ms) if f.name.endswith("_reading")]
    assert mine == [f for f in facts_at(m, period, clock_ms) if f.name.endswith("_reading")]


GOAL_ORDER = ["pull_one_back", "equalise", "take_the_lead", "extend_the_lead"]
CHAOS_ORDER = ["patient", "steady", "end_to_end"]


@given(st.integers(-10, 10), st.integers(-10, 10))
def test_a_bigger_difference_before_a_goal_never_reads_as_less(a, b):
    lo, hi = sorted((a, b))
    assert GOAL_ORDER.index(goal_reading(lo)) <= GOAL_ORDER.index(goal_reading(hi))


@given(st.integers(0, 100), st.integers(0, 100))
def test_more_chaos_never_reads_as_calmer(a, b):
    lo, hi = sorted((a, b))
    assert CHAOS_ORDER.index(chaos_reading(lo)) <= CHAOS_ORDER.index(chaos_reading(hi))
