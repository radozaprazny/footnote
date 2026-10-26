import dataclasses
import functools
from fractions import Fraction
from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from strategies import CLUBS, event_streams

from matchlens.events import (
    MAX_PERIOD_MS,
    PERIODS,
    Event,
    EventType,
    Outcome,
    Point,
    Restart,
    make_event_id,
)
from matchlens.generator import generate_match
from matchlens.stats.possession import Possession, Spell, percent_shares, possession, spells

# up to 10**30 so float arithmetic (exact only below 2**53) would be caught
counts_lists = st.lists(st.integers(min_value=0, max_value=10**30), min_size=1, max_size=150)
zero_lists = st.lists(st.just(0), min_size=1, max_size=150)
any_counts = st.one_of(counts_lists, zero_lists)


def exact_proportions(counts):
    total = sum(counts)
    if total == 0:
        return [Fraction(100, len(counts))] * len(counts)
    return [Fraction(100 * c, total) for c in counts]


@given(any_counts)
def test_shares_are_ints(counts):
    assert all(type(share) is int for share in percent_shares(counts))


@given(any_counts)
def test_sums_to_100(counts):
    assert sum(percent_shares(counts)) == 100


@given(any_counts)
def test_each_share_within_1_of_exact_proportion(counts):
    for share, exact in zip(percent_shares(counts), exact_proportions(counts), strict=True):
        assert abs(share - exact) < 1


@given(any_counts)
def test_length_preserved(counts):
    assert len(percent_shares(counts)) == len(counts)


@given(any_counts)
def test_order_preserved_ties_to_lower_index(counts):
    shares = percent_shares(counts)
    for i in range(len(counts)):
        for j in range(i + 1, len(counts)):
            if counts[i] >= counts[j]:
                assert shares[i] >= shares[j]
            else:
                assert shares[i] <= shares[j]


@given(any_counts)
def test_extra_points_go_to_largest_remainders(counts):
    exact = exact_proportions(counts)
    fractions = [e - int(e) for e in exact]
    got_extra = [share > int(e) for share, e in zip(percent_shares(counts), exact, strict=True)]
    for i in range(len(counts)):
        for j in range(len(counts)):
            if got_extra[i] and not got_extra[j]:
                assert fractions[i] > fractions[j] or (fractions[i] == fractions[j] and i < j)


@given(any_counts)
def test_deterministic_and_input_untouched(counts):
    before = list(counts)
    first = percent_shares(counts)
    assert percent_shares(tuple(counts)) == first
    assert counts == before


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        ([1, 1, 1], [34, 33, 33]),
        ([0, 0], [50, 50]),
        ([0, 0, 0], [34, 33, 33]),
        ([3, 0], [100, 0]),
        ([7], [100]),
        ([1, 2], [33, 67]),
        ([2, 1, 1], [50, 25, 25]),
        # largest remainder, not largest count: 57.14, 28.57, 14.29
        ([4, 2, 1], [57, 29, 14]),
        # equal remainders (0.5, 1.5): the lower index wins
        ([1, 3, 196], [1, 1, 98]),
        # exact 33.5, 16.5 + 5e-17, 50 - 5e-17: float division would round the last up to 50.0
        ([670000000000000000, 330000000000000001, 999999999999999999], [33, 17, 50]),
    ],
)
def test_examples(counts, expected):
    assert percent_shares(counts) == expected


def test_more_teams_than_points():
    shares = percent_shares([1] * 101)
    assert shares == [1] * 100 + [0]


@given(
    st.lists(st.integers(min_value=0), max_size=20),
    st.integers(max_value=-1),
    st.integers(min_value=0),
)
def test_any_negative_count_raises(counts, negative, position):
    counts.insert(position % (len(counts) + 1), negative)
    with pytest.raises(ValueError):
        percent_shares(counts)


def test_empty_raises():
    with pytest.raises(ValueError):
        percent_shares([])


def test_float_raises():
    with pytest.raises(TypeError):
        percent_shares([1.5, 2.5])


def test_accepts_an_iterator():
    assert percent_shares(c for c in [1, 2]) == [33, 67]


def test_bool_raises():
    with pytest.raises(TypeError):
        percent_shares([True, False])


# --- spells ------------------------------------------------------------------------------------

H, A = CLUBS[:2]
SPOT = Point(52.5, 34.0)
GAINS = {
    EventType.PASS,
    EventType.SHOT,
    EventType.CLEARANCE,
    EventType.INTERCEPTION,
    EventType.SAVE,
    EventType.RECOVERY,
}


def gains_ball(e: Event) -> bool:
    return e.type in GAINS or e.outcome in (Outcome.WON, Outcome.REGAIN)


def on_ball(seq, clock, kind, team, **fields):
    player = f"{team}-p09"
    return Event(make_event_id("m1", seq), 1, clock, kind, team, player, SPOT, **fields)


def flight(seq, clock, kind, team, outcome, ms=1000, **fields):
    recipient = f"{team}-p10" if outcome is Outcome.COMPLETE else None
    return on_ball(
        seq, clock, kind, team, end=SPOT, duration_ms=ms, outcome=outcome, recipient=recipient,
        **fields,
    )  # fmt: skip


E = EventType
EXAMPLE = [
    flight(0, 0, E.PASS, H, Outcome.COMPLETE, restart=Restart.KICK_OFF),
    flight(1, 3_000, E.PASS, H, Outcome.INCOMPLETE),  # lands loose at 4 000
    on_ball(2, 5_000, E.RECOVERY, A),
    on_ball(3, 6_000, E.PRESSURE, H, outcome=Outcome.RESISTED),  # A keeps the ball
    flight(4, 7_000, E.PASS, A, Outcome.OUT),  # out of play at 8 000
    flight(5, 15_000, E.PASS, H, Outcome.COMPLETE, restart=Restart.THROW_IN),
    on_ball(6, 20_000, E.TACKLE, A, outcome=Outcome.WON),
    on_ball(7, 25_000, E.FOUL, H),
    flight(8, 35_000, E.SHOT, A, Outcome.SAVED, restart=Restart.FREE_KICK),  # lands at 36 000
    on_ball(9, 36_000, E.SAVE, H, related="m1-e00008"),  # parried out for the corner
    flight(10, 60_000, E.PASS, A, Outcome.COMPLETE, restart=Restart.CORNER),
    flight(11, 62_000, E.SHOT, A, Outcome.GOAL, ms=500),
    on_ball(12, 62_500, E.GOAL, A, related="m1-e00011"),
    Event("m1-e00013", 1, 70_000, E.PERIOD_END),
]


def ids(*seqs):
    return tuple(make_event_id("m1", s) for s in seqs)


def test_example_spells():
    assert spells(EXAMPLE) == [
        Spell(H, 1, 0, 4_000, ids(0, 1)),
        Spell(None, 1, 4_000, 5_000, ()),  # loose
        Spell(A, 1, 5_000, 8_000, ids(2, 3, 4)),
        Spell(None, 1, 8_000, 15_000, ()),  # out of play until the throw-in
        Spell(H, 1, 15_000, 20_000, ids(5)),
        Spell(A, 1, 20_000, 25_000, ids(6)),
        Spell(None, 1, 25_000, 35_000, ids(7)),  # the foul stops play
        Spell(A, 1, 35_000, 36_000, ids(8)),
        Spell(None, 1, 36_000, 60_000, ()),  # the save has no time on the ball
        Spell(A, 1, 60_000, 62_500, ids(10, 11)),
        Spell(None, 1, 62_500, 70_000, ids(12, 13)),
    ]


def test_example_possession():
    s = spells(EXAMPLE)
    # H 9 000 ms, A 11 500 ms: 43.9 % and 56.1 %
    assert possession(s, (H, A)) == Possession(
        (H, A), (9_000, 11_500), (44, 56), ids(0, 1, 2, 3, 4, 5, 6, 8, 10, 11)
    )
    assert possession(s, (H, A), 1, 3_000, 21_000) == Possession(
        (H, A), (6_000, 4_000), (60, 40), ids(0, 1, 2, 3, 4, 5, 6)
    )
    assert possession(s, (H, A), 2) == Possession((H, A), (0, 0), (50, 50), ())
    # the loose ball between H's spell and A's: both only touch the window, so neither counts
    assert possession(s, (H, A), 1, 4_000, 5_000) == Possession((H, A), (0, 0), (50, 50), ())


def test_example_live():
    # up to the save nothing says the ball went out for the corner: the save is the last word
    assert spells(EXAMPLE[:10])[-2:] == [
        Spell(None, 1, 25_000, 35_000, ids(7)),
        Spell(A, 1, 35_000, 36_000, ids(8)),
    ]
    assert spells(EXAMPLE[:1]) == []  # the kick-off at 0: no time has passed
    assert spells([]) == []


def test_possession_rejects_bad_arguments():
    s = spells(EXAMPLE)
    with pytest.raises(ValueError, match="needs a period"):
        possession(s, (H, A), start_ms=0)
    with pytest.raises(ValueError, match="distinct"):
        possession(s, (H, H))
    with pytest.raises(ValueError, match="not one of"):
        possession(s, (H, CLUBS[2]))
    with pytest.raises(ValueError, match="period = 3"):
        possession(s, (H, A), 3)
    with pytest.raises(ValueError, match="ends before it starts"):
        possession(s, (H, A), 1, 5_000, 4_000)


def assert_tiles(period_spells: list[Spell], end: int) -> None:
    """Gapless from 0 to `end`, nothing empty, consecutive spells of different teams."""
    bounds = [0] + [s.end_ms for s in period_spells]
    assert [s.start_ms for s in period_spells] == bounds[:-1]
    assert bounds[-1] == end
    assert all(s.end_ms > s.start_ms for s in period_spells)
    assert all(a.team != b.team for a, b in pairwise(period_spells))


def period_end(events: list[Event], period: int) -> int:
    return next(e.clock_ms for e in events if e.period == period and e.type is E.PERIOD_END)


@given(event_streams())
def test_spells_tile_each_period(stream):
    _, events = stream
    got = spells(events)
    assert [s.period for s in got] == sorted(s.period for s in got)
    for period in PERIODS:
        assert_tiles([s for s in got if s.period == period], period_end(events, period))


@given(event_streams())
def test_spell_events_are_in_order_inside_the_spell(stream):
    _, events = stream
    by_id = {e.event_id: e for e in events}
    got = spells(events)
    listed = [i for s in got for i in s.event_ids]
    assert listed == [e.event_id for e in events if e.event_id in set(listed)]  # once, in order
    for s in got:
        for i in s.event_ids:
            e = by_id[i]
            assert e.period == s.period and s.start_ms <= e.clock_ms <= s.end_ms
            if gains_ball(e):
                assert e.team == s.team
        if s.team is not None:  # a team's spell starts with the event that gave it the ball
            first = by_id[s.event_ids[0]]
            assert gains_ball(first) and first.team == s.team and first.clock_ms == s.start_ms


def clip(full: list[Spell], events: list[Event], k: int) -> list[Spell]:
    """The spells of the whole match as far as the first `k` events know them."""
    if k == 0:
        return []
    last = events[k - 1]
    known = {e.event_id for e in events[:k]}
    horizon = MAX_PERIOD_MS if last.type is E.PERIOD_END else last.clock_ms
    return [
        dataclasses.replace(
            s,
            end_ms=min(s.end_ms, horizon) if s.period == last.period else s.end_ms,
            event_ids=tuple(i for i in s.event_ids if i in known),
        )
        for s in full
        if s.period < last.period or (s.period == last.period and s.start_ms < horizon)
    ]


@given(event_streams(), st.data())
def test_a_prefix_gives_the_live_spells(stream, data):
    _, events = stream
    k = data.draw(st.integers(0, len(events)))
    assert spells(events[:k]) == clip(spells(events), events, k)


def relabel(e: Event, swap: dict[str, str]) -> Event:
    def player(p):
        return p and f"{swap[e.team]}-{p.split('-')[1]}"

    if e.team is None:
        return e
    return dataclasses.replace(
        e, team=swap[e.team], player=player(e.player), recipient=player(e.recipient)
    )


@given(event_streams())
def test_swapping_the_teams_mirrors_the_result(stream):
    (home, away), events = stream
    swap = {home: away, away: home}
    got = spells(events)
    mirrored = spells([relabel(e, swap) for e in events])
    assert mirrored == [dataclasses.replace(s, team=swap.get(s.team)) for s in got]
    for period in (None, *PERIODS):
        before = possession(got, (home, away), period)
        after = possession(mirrored, (home, away), period)
        assert after.ms == before.ms[::-1]
        assert after.event_ids == before.event_ids
        total = sum(before.ms)
        if total and Fraction(100 * before.ms[0], total).denominator == 2:
            # x.5 against y.5: the leftover point goes to the team listed first, either way
            assert after.percent == (before.percent[1] + 1, before.percent[0] - 1)
        else:
            assert after.percent == before.percent[::-1]


cuts = st.integers(-10_000, MAX_PERIOD_MS + 10_000)


@given(event_streams(), st.sampled_from(PERIODS), st.data())
def test_windows_periods_and_match_add_up(stream, period, data):
    teams, events = stream
    s = spells(events)
    # cuts on and next to spell edges as well, where a window just touches a spell
    edges = sorted({b + d for x in s for b in (x.start_ms, x.end_ms) for d in (-1, 0, 1)})
    cut = st.sampled_from(edges) | cuts if edges else cuts
    lo, mid, hi = sorted(data.draw(st.lists(cut, min_size=3, max_size=3)))
    whole = possession(s, teams, period, lo, hi)
    halves = possession(s, teams, period, lo, mid), possession(s, teams, period, mid, hi)
    assert whole.ms == tuple(a + b for a, b in zip(*(h.ms for h in halves), strict=True))
    assert sum(whole.ms) <= hi - lo
    counted = [
        x
        for x in s
        if x.team is not None and x.period == period and min(x.end_ms, hi) > max(x.start_ms, lo)
    ]
    assert whole.event_ids == tuple(i for x in counted for i in x.event_ids)
    assert sum(whole.percent) == 100
    assert whole.percent == tuple(percent_shares(whole.ms))
    match = possession(s, teams)
    first, second = (possession(s, teams, p) for p in PERIODS)
    assert match.ms == tuple(a + b for a, b in zip(first.ms, second.ms, strict=True))
    assert match.event_ids == first.event_ids + second.event_ids
    assert possession(s, teams, period, 0, MAX_PERIOD_MS) == (first, second)[period - 1]
    on_the_ball = sum(x.end_ms - x.start_ms for x in s if x.team is not None)
    assert sum(match.ms) == on_the_ball


# --- real matches --------------------------------------------------------------------------------

REAL_SEEDS = (3, 7)


@functools.cache
def real(seed: int) -> tuple[tuple[str, str], list[Event], list[Spell]]:
    m = generate_match(seed)
    events = list(m.events)
    return (m.meta.home, m.meta.away), events, spells(events)


@pytest.mark.parametrize("seed", REAL_SEEDS)
def test_real_match_spells(seed):
    teams, events, got = real(seed)
    for period in PERIODS:
        assert_tiles([s for s in got if s.period == period], period_end(events, period))
    assert {s.team for s in got} == {*teams, None}
    # every event is in a spell except a save parried out for a corner (no time on the ball)
    listed = {i for s in got for i in s.event_ids}
    missing = [(e, events[n + 1]) for n, e in enumerate(events) if e.event_id not in listed]
    assert all(e.type is E.SAVE and nxt.restart is Restart.CORNER for e, nxt in missing)


@settings(deadline=None)  # the first example generates the match
@given(st.sampled_from(REAL_SEEDS), st.data())
def test_real_match_prefix_gives_the_live_spells(seed, data):
    _, events, full = real(seed)
    k = data.draw(st.integers(0, len(events)))
    assert spells(events[:k]) == clip(full, events, k)
