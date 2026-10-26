import dataclasses
import itertools
from fractions import Fraction

import pytest
import real
from hypothesis import assume, given
from hypothesis import strategies as st
from strategies import CLUBS, event_streams, lineup

from matchlens.events import (
    MAX_SEQ,
    PERIODS,
    PITCH_LENGTH,
    PITCH_WIDTH,
    Event,
    EventType,
    MatchMeta,
    Outcome,
    Point,
    Restart,
    make_event_id,
    parse_event_id,
)
from matchlens.stats.flow import (
    MS_PER_MINUTE,
    NEUTRAL,
    PRESSING,
    SHOT_WEIGHT,
    TYPICAL_CHANGES_PER_MINUTE,
    TYPICAL_POSSESSION_MS,
    Control,
    attacking_weight,
    chaos_index,
    control,
    momentum,
    pressing,
)
from matchlens.stats.possession import spells

E = EventType
H, A = CLUBS[:2]
META = MatchMeta("m1", H, A, lineup(H), lineup(A), 1)  # home attacks x = 105 in period 1


def on_ball(seq, clock, kind, team, at, period=1, **fields):
    return Event(make_event_id("m1", seq), period, clock, kind, team, f"{team}-p09", at, **fields)


def flight(seq, clock, kind, team, at, to, outcome, ms=1000, period=1, **fields):
    recipient = f"{team}-p10" if outcome is Outcome.COMPLETE else None
    return on_ball(
        seq, clock, kind, team, at, period, end=to, duration_ms=ms, outcome=outcome,
        recipient=recipient, **fields,
    )  # fmt: skip


def ids(*seqs):
    return tuple(make_event_id("m1", s) for s in seqs)


P = Point
EXAMPLE = [
    flight(0, 0, E.PASS, H, P(52.5, 34), P(40, 30), Outcome.COMPLETE, restart=Restart.KICK_OFF),
    on_ball(1, 5_000, E.PRESSURE, A, P(40, 30), outcome=Outcome.RESISTED),  # A's 65 m: presses
    flight(2, 8_000, E.PASS, H, P(40, 30), P(75, 20), Outcome.COMPLETE),  # into the final third
    on_ball(3, 10_000, E.TACKLE, A, P(75, 20), outcome=Outcome.WON),  # A's 30 m: own half
    flight(4, 15_000, E.PASS, A, P(75, 20), P(30, 34), Outcome.COMPLETE),  # A's final third
    on_ball(5, 18_000, E.PRESSURE, H, P(30, 34), outcome=Outcome.REGAIN),  # H's own half
    flight(6, 20_000, E.SHOT, H, P(88, 34), P(105, 34), Outcome.OFF_TARGET),  # dead at 21 000
    flight(7, 30_000, E.PASS, A, P(99, 34), P(80, 34), Outcome.COMPLETE, restart=Restart.GOAL_KICK),
    on_ball(8, 40_000, E.PRESSURE, H, P(60, 34), outcome=Outcome.REGAIN),  # high: both count
    Event("m1-e00009", 1, 50_000, E.PERIOD_END),
]


# --- examples, worked by hand -------------------------------------------------------------------


def test_example_pressing():
    home, away = pressing(META, EXAMPLE)
    assert (home.team, home.actions, home.event_ids, home.window_ms) == (H, 1, ids(8), 50_000)
    assert (away.team, away.actions, away.event_ids) == (A, 1, ids(1))
    assert home.per_minute == away.per_minute == 1.2


def test_example_momentum():
    m = momentum(META, EXAMPLE)
    # H: the pass into the final third 1, the shot 3, the high regain 1; A: its pass 1
    assert (m.teams, m.weights, m.event_ids) == ((H, A), (5, 1), ids(2, 4, 6, 8))
    assert m.percent == (83, 17)  # 83.3 and 16.7


def test_example_control():
    c = control(EXAMPLE)
    # H 0–10 s, A 10–18 s, H 18–21 s, (dead ball), A 30–40 s, H 40–50 s
    assert (c.window_ms, c.ball_ms, c.possessions, c.changes) == (50_000, 41_000, 5, 4)
    assert c.change_ids == ids(3, 5, 7, 8)
    assert c.changes_per_minute == 4.8 and c.average_possession_ms == 8_200
    # 50 * (4.8 / 7.8 + 16.4 / 24.6) = 64.1
    assert c.chaos == 64
    assert c.spells == tuple(s for s in spells(EXAMPLE) if s.team)


def test_a_team_that_gets_its_own_ball_back_keeps_its_possession():
    stream = [
        flight(0, 0, E.PASS, H, P(52.5, 34), P(40, 30), Outcome.COMPLETE, restart=Restart.KICK_OFF),
        flight(1, 4_000, E.PASS, H, P(40, 30), P(60, 30), Outcome.INCOMPLETE),  # loose at 5 000
        on_ball(2, 6_000, E.RECOVERY, H, P(60, 30)),
        on_ball(3, 10_000, E.INTERCEPTION, A, P(70, 30)),
        Event("m1-e00004", 1, 20_000, E.PERIOD_END),
    ]
    c = control(stream)
    assert [s.team for s in spells(stream)] == [H, None, H, A]
    assert (c.possessions, c.changes, c.change_ids, c.ball_ms) == (2, 1, ids(3), 19_000)
    assert c.average_possession_ms == 9_500


@pytest.mark.parametrize("team", [A, H])
def test_possession_changes_do_not_cross_half_time(team):
    second = [
        flight(10, 0, E.PASS, team, P(52.5, 34), P(60, 30), Outcome.COMPLETE, period=2,
               restart=Restart.KICK_OFF),
        Event("m1-e00011", 2, 10_000, E.PERIOD_END),
    ]  # fmt: skip
    c = control(EXAMPLE + second)
    # H ends period 1 with the ball; whoever kicks off period 2 starts a new possession, and
    # the ball changing teams over half-time is no change of possession
    assert (c.possessions, c.changes, c.window_ms) == (6, 4, 60_000)
    assert c.change_ids == ids(3, 5, 7, 8)
    after = control(EXAMPLE + second, 2)
    assert (after.possessions, after.changes, after.ball_ms) == (1, 0, 10_000)


# --- boundaries, pinned from both sides ---------------------------------------------------------


@pytest.mark.parametrize(
    ("period", "team", "x", "counts"),
    [
        (1, H, 52.50, True),  # on the halfway line: the opponent's half, as in passing
        (1, H, 52.49, False),
        (1, A, 52.50, True),
        (1, A, 52.51, False),  # 52.49 m from A's goal line
        (2, H, 52.50, True),
        (2, H, 52.51, False),
        (2, A, 52.49, False),
        (2, A, 52.50, True),
    ],
)
def test_the_halfway_line_is_the_opponent_s_half(period, team, x, counts):
    stream = [on_ball(0, 1_000, E.PRESSURE, team, P(x, 10), period, outcome=Outcome.REGAIN)]
    home, away = pressing(META, stream)
    assert (home if team == H else away).actions == counts
    assert momentum(META, stream).weights == ((counts, 0) if team == H else (0, counts))


@pytest.mark.parametrize(
    ("period", "team", "x", "weight"),
    [
        (1, H, 70.00, 1),  # the final third starts at 70 m from the own goal line
        (1, H, 69.99, 0),
        (2, H, 35.00, 1),
        (2, H, 35.01, 0),
        (1, A, 35.00, 1),
        (1, A, 35.01, 0),
        (1, H, 105.0, 1),  # the penalty area is in the final third
    ],
)
def test_a_pass_counts_from_the_final_third_on(period, team, x, weight):
    for outcome, expected in ((Outcome.COMPLETE, weight), (Outcome.INCOMPLETE, 0)):
        e = flight(0, 1_000, E.PASS, team, P(52.5, 34), P(x, 34), outcome, 2_000, period)
        assert attacking_weight(META, e) == expected


@pytest.mark.parametrize(
    ("start_ms", "end_ms", "counted"),
    [
        (40_000, 45_000, True),  # an event on the window's start
        (40_001, 45_000, False),
        (35_000, 40_000, True),  # on its end
        (35_000, 39_999, False),
    ],
)
def test_a_window_holds_the_events_on_its_edges(start_ms, end_ms, counted):
    home, _ = pressing(META, EXAMPLE, 1, start_ms, end_ms)
    assert home.event_ids == (ids(8) if counted else ())
    assert momentum(META, EXAMPLE, 1, start_ms, end_ms).event_ids == home.event_ids


@pytest.mark.parametrize(
    ("start_ms", "end_ms", "changes", "possessions"),
    [
        (10_000, 15_000, ids(3), 1),  # A wins the ball on the window's start: a change
        (10_001, 15_000, (), 1),
        (5_000, 10_000, (), 1),  # on its end A has had no time on the ball yet
        (5_000, 10_001, ids(3), 2),
        (25_000, 35_000, ids(7), 1),  # H's ball went dead before the window, A's goal kick in it
        (21_000, 29_999, (), 0),  # dead ball all through
    ],
)
def test_a_change_of_possession_counts_where_the_new_possession_starts(
    start_ms, end_ms, changes, possessions
):
    c = control(EXAMPLE, 1, start_ms, end_ms)
    assert (c.change_ids, c.changes, c.possessions) == (changes, len(changes), possessions)


def test_the_length_of_a_window():
    live = EXAMPLE[:-1]  # period 1 has not ended: it lasts to its latest event, 40 000
    assert pressing(META, EXAMPLE)[0].window_ms == 50_000
    assert pressing(META, live)[0].window_ms == 40_000
    assert pressing(META, live, 1, 30_000, 60_000)[0].window_ms == 30_000  # the clock runs on
    assert pressing(META, EXAMPLE, 1, 30_000, 60_000)[0].window_ms == 20_000  # cut at the end
    assert pressing(META, EXAMPLE, 1, 30_000, 50_000)[0].window_ms == 20_000
    assert pressing(META, EXAMPLE, 1, -5_000, 10_000)[0].window_ms == 10_000
    assert pressing(META, EXAMPLE, 1, 60_000, 70_000)[0].window_ms == 0
    assert pressing(META, EXAMPLE, 2)[0].window_ms == 0  # not started
    assert control(EXAMPLE, 1, 30_000, 60_000).window_ms == 20_000


def test_no_time_passed_is_no_rate():
    home, _ = pressing(META, EXAMPLE, 1, 40_000, 40_000)
    assert (home.actions, home.window_ms, home.per_minute) == (1, 0, 0.0)
    c = control(EXAMPLE, 1, 40_000, 40_000)
    assert (c.possessions, c.chaos, c.average_possession_ms, c.spells) == (0, NEUTRAL, None, ())


def test_windows_are_checked():
    for bad in ((None, 0, 10), (3, None, None), (1, 10, 5)):
        with pytest.raises(ValueError):
            pressing(META, EXAMPLE, *bad)
        with pytest.raises(ValueError):
            momentum(META, EXAMPLE, *bad)
        with pytest.raises(ValueError):
            control(EXAMPLE, *bad)


def test_a_team_that_is_not_playing_is_refused():
    stranger = CLUBS[2]
    shot = flight(0, 1_000, E.SHOT, stranger, P(90, 34), P(105, 34), Outcome.OFF_TARGET)
    tackle = on_ball(0, 1_000, E.TACKLE, stranger, P(90, 34), outcome=Outcome.LOST)
    with pytest.raises(ValueError):
        momentum(META, [shot])
    with pytest.raises(ValueError):
        pressing(META, [tackle])


# --- the chaos index ----------------------------------------------------------------------------

rates = st.fractions(min_value=0, max_value=1_000, max_denominator=10**6)
lengths = st.fractions(min_value=Fraction(1, 10**6), max_value=10**7, max_denominator=10**6)


def test_a_typical_match_scores_the_middle():
    assert chaos_index(TYPICAL_CHANGES_PER_MINUTE, Fraction(TYPICAL_POSSESSION_MS)) == 50


def test_the_chaos_index_rounds_half_up_exactly():
    # often = 1/2 at the typical rate; short = 51/100 needs a possession of 16 400 * 49/51 ms,
    # so the index is exactly 50.5
    rate, on_it = TYPICAL_CHANGES_PER_MINUTE, Fraction(TYPICAL_POSSESSION_MS * 49, 51)
    assert chaos_index(rate, on_it) == 51
    assert chaos_index(rate, on_it + Fraction(1, 10**9)) == 50


def test_the_ends_of_the_chaos_index():
    assert chaos_index(Fraction(0), Fraction(10**12)) == 0
    assert chaos_index(Fraction(10**12), Fraction(1, 10**12)) == 100


@given(rates, lengths)
def test_the_chaos_index_is_bounded(rate, length):
    assert 0 <= chaos_index(rate, length) <= 100


@given(rates, rates, lengths)
def test_more_changes_never_calm_the_game(r1, r2, length):
    low, high = sorted((r1, r2))
    assert chaos_index(low, length) <= chaos_index(high, length)


@given(rates, lengths, lengths)
def test_longer_possessions_never_add_chaos(rate, l1, l2):
    short, long_ = sorted((l1, l2))
    assert chaos_index(rate, short) >= chaos_index(rate, long_)


@pytest.mark.parametrize(("rate", "length"), [(-1, 1_000), (1, 0), (1, -5)])
def test_the_chaos_index_refuses_what_cannot_be(rate, length):
    with pytest.raises(ValueError):
        chaos_index(Fraction(rate), Fraction(length))


# --- properties over random event streams -------------------------------------------------------


def meta_of(teams: tuple[str, str], events: list[Event]) -> MatchMeta:
    home, away = teams
    match_id = parse_event_id(events[0].event_id)[0]
    return MatchMeta(match_id, home, away, lineup(home), lineup(away), 0)


cuts = st.integers(-10_000, 420_000)  # a period of `event_streams` lasts at most 405 s


@st.composite
def windows(draw):
    period = draw(st.none() | st.sampled_from(PERIODS))
    if period is None:
        return None, None, None
    start, end = draw(st.none() | cuts), draw(st.none() | cuts)
    if start is not None and end is not None and start > end:
        start, end = end, start
    return period, start, end


def holds(window, e: Event) -> bool:
    period, start, end = window
    return (
        period in (None, e.period)
        and (start is None or start <= e.clock_ms)
        and (end is None or e.clock_ms <= end)
    )


def rightwards(meta: MatchMeta, team: str, period: int) -> bool:
    return (team == meta.home) == (period == 1)


def cm_from_own_goal(meta: MatchMeta, e: Event, spot: Point) -> int:
    x = round(spot.x * 100)
    return x if rightwards(meta, e.team, e.period) else 10_500 - x


def oracle_weight(meta: MatchMeta, e: Event) -> int:
    if e.type is E.SHOT:
        return 3
    if e.type in (E.PASS, E.CLEARANCE):
        return int(e.outcome is Outcome.COMPLETE and cm_from_own_goal(meta, e, e.end) >= 7_000)
    if e.type in (E.INTERCEPTION, E.RECOVERY) or e.outcome in (Outcome.WON, Outcome.REGAIN):
        return int(cm_from_own_goal(meta, e, e.start) >= 5_250)
    return 0


def oracle_control(events: list[Event], window) -> tuple[int, int, tuple[str, ...]]:
    """(time on the ball, possessions, change ids), counted spell by spell."""
    period, start, end = window
    lo = -(10**9) if start is None else start
    hi = 10**9 if end is None else end
    team_spells = [s for s in spells(events) if s.team]
    counted = [
        (s, min(s.end_ms, hi) - max(s.start_ms, lo))
        for s in team_spells
        if period in (None, s.period)
    ]
    counted = [(s, t) for s, t in counted if t > 0]
    runs = itertools.groupby(counted, key=lambda c: (c[0].period, c[0].team))
    changes = tuple(
        b.event_ids[0]
        for a, b in itertools.pairwise(team_spells)
        if a.period == b.period and period in (None, b.period)
        if a.team != b.team and lo <= b.start_ms < hi
    )
    return sum(t for _, t in counted), sum(1 for _ in runs), changes


def oracle_window_ms(events: list[Event], window) -> int:
    """The clock time of a window: a period lasts to its latest event, an ended one no longer."""
    period, start, end = window

    def length(p: int) -> int:
        return max((e.clock_ms for e in events if e.period == p), default=0)

    if period is None:
        return sum(length(p) for p in PERIODS)
    ended = any(e.period == period and e.type is E.PERIOD_END for e in events)
    stop = length(period) if end is None else min(end, length(period)) if ended else end
    return max(0, stop - max(0, start or 0))


@given(event_streams(), windows())
def test_each_index_is_what_it_counts_and_stays_in_range(stream, window):
    teams, events = stream
    meta = meta_of(teams, events)
    inside = [e for e in events if holds(window, e)]

    for p in pressing(meta, events, *window):
        mine = [e for e in inside if e.team == p.team and e.type in PRESSING]
        high = [e.event_id for e in mine if cm_from_own_goal(meta, e, e.start) >= 5_250]
        assert p.event_ids == tuple(high) and p.actions == len(high) <= len(mine)
        assert p.window_ms >= 0 and p.per_minute >= 0
        if p.window_ms:
            assert p.per_minute == p.actions * MS_PER_MINUTE / p.window_ms
        else:
            assert p.per_minute == 0.0

    m = momentum(meta, events, *window)
    weighted = [e for e in inside if oracle_weight(meta, e)]
    assert m.event_ids == tuple(e.event_id for e in weighted)
    assert m.weights == tuple(
        sum(oracle_weight(meta, e) for e in weighted if e.team == t) for t in teams
    )
    assert sum(m.percent) == 100 and all(0 <= s <= 100 for s in m.percent)
    if not weighted:
        assert m.percent == (NEUTRAL, NEUTRAL)

    c = control(events, *window)
    assert (c.ball_ms, c.possessions, c.change_ids) == oracle_control(events, window)
    assert c.changes == len(c.change_ids)
    assert 0 <= c.ball_ms <= c.window_ms and 0 <= c.chaos <= 100
    ms = oracle_window_ms(events, window)
    assert c.window_ms == ms and [p.window_ms for p in pressing(meta, events, *window)] == [ms] * 2
    if c.possessions:
        assert c.average_possession_ms == c.ball_ms / c.possessions
        rate = Fraction(c.changes * MS_PER_MINUTE, c.window_ms)
        assert c.changes_per_minute == float(rate)
        assert c.chaos == chaos_index(rate, Fraction(c.ball_ms, c.possessions))
    else:
        assert c == Control(c.window_ms, 0, 0, 0, 0.0, None, NEUTRAL, (), ())


@given(event_streams(), st.sampled_from(PERIODS), cuts)
def test_adjacent_windows_add_up_to_the_period(stream, period, cut):
    _, events = stream
    before, after = control(events, period, None, cut), control(events, period, cut, None)
    whole = control(events, period)
    assert before.change_ids + after.change_ids == whole.change_ids
    assert before.ball_ms + after.ball_ms == whole.ball_ms


@st.composite
def empty_windows(draw, events: list[Event]):
    """A clock range of one period that holds no event with a team: before the first, between
    two, or after the last."""
    period = draw(st.sampled_from(PERIODS))
    clocks = sorted({e.clock_ms for e in events if e.period == period and e.team})
    edges = [-10_001, *clocks, 420_001]
    gaps = [(a + 1, b - 1) for a, b in itertools.pairwise(edges) if b - a >= 2]
    low, high = draw(st.sampled_from(gaps))
    start = draw(st.integers(low, high))
    return period, start, draw(st.integers(start, high))


@given(event_streams(), st.data())
def test_an_empty_window_gives_the_neutral_values(stream, data):
    teams, events = stream
    window = data.draw(empty_windows(events))
    assert not any(holds(window, e) and e.team for e in events)
    meta = meta_of(teams, events)
    assert [p.actions for p in pressing(meta, events, *window)] == [0, 0]
    assert all(p.per_minute == 0.0 for p in pressing(meta, events, *window))
    m = momentum(meta, events, *window)
    assert (m.weights, m.percent, m.event_ids) == ((0, 0), (NEUTRAL, NEUTRAL), ())
    c = control(events, *window)
    if not c.ball_ms:  # nobody had the ball in it either
        assert (c.chaos, c.changes, c.possessions) == (NEUTRAL, 0, 0)


def test_a_match_without_a_team_on_the_ball_is_neutral():
    stream = [Event("m1-e00000", 1, 60_000, E.PERIOD_END), Event("m1-e00001", 2, 0, E.PERIOD_END)]
    assert [p.per_minute for p in pressing(META, stream)] == [0.0, 0.0]
    assert momentum(META, stream).percent == (NEUTRAL, NEUTRAL)
    assert control(stream) == Control(60_000, 0, 0, 0, 0.0, None, NEUTRAL, (), ())


def on_grid(e: Event) -> Event:
    """The event with its spots on the centimetre grid, as the generator writes them."""

    def snap(p: Point | None) -> Point | None:
        return p and Point(round(p.x, 2), round(p.y, 2))

    return dataclasses.replace(e, start=snap(e.start), end=snap(e.end))


def turned_round(e: Event) -> Event:
    def turn(p: Point | None) -> Point | None:
        return p and Point(round(PITCH_LENGTH - p.x, 2), round(PITCH_WIDTH - p.y, 2))

    return dataclasses.replace(e, start=turn(e.start), end=turn(e.end))


def renamed(e: Event, swap: dict[str, str]) -> Event:
    def player(p):
        return p and f"{swap[e.team]}-{p.split('-')[1]}"

    if e.team is None:
        return e
    return dataclasses.replace(
        e, team=swap[e.team], player=player(e.player), recipient=player(e.recipient)
    )


def swapped_ends(meta: MatchMeta) -> MatchMeta:
    return MatchMeta(meta.match_id, meta.away, meta.home, meta.away_lineup, meta.home_lineup, 0)


@given(event_streams(), windows())
def test_turning_the_pitch_round_and_swapping_ends_changes_nothing(stream, window):
    teams, events = stream
    events = [on_grid(e) for e in events]
    meta = meta_of(teams, events)
    turned, other = [turned_round(e) for e in events], swapped_ends(meta)
    home, away = pressing(meta, events, *window)
    assert pressing(other, turned, *window) == (away, home)  # each team presses as before
    before, after = momentum(meta, events, *window), momentum(other, turned, *window)
    assert (after.weights, after.event_ids) == (before.weights[::-1], before.event_ids)
    total = sum(before.weights)
    if total and Fraction(100 * before.weights[0], total).denominator == 2:
        # x.5 against y.5: the leftover point goes to the home team, either way
        assert after.percent == (before.percent[1] + 1, before.percent[0] - 1)
    else:
        assert after.percent == before.percent[::-1]
    assert control(turned, *window) == control(events, *window)


@given(event_streams(), windows())
def test_swapping_the_teams_names_only_swaps_the_names(stream, window):
    (home, away), events = stream
    swap = {home: away, away: home}
    meta = meta_of((home, away), events)
    named = [renamed(e, swap) for e in events]
    other = swapped_ends(meta)  # the renamed home team still plays where home played
    got = pressing(other, named, *window)
    assert got == tuple(
        dataclasses.replace(p, team=swap[p.team]) for p in pressing(meta, events, *window)
    )
    before, after = momentum(meta, events, *window), momentum(other, named, *window)
    assert after == dataclasses.replace(before, teams=(away, home))
    c, renamed_c = control(events, *window), control(named, *window)
    assert renamed_c == dataclasses.replace(
        c, spells=tuple(dataclasses.replace(s, team=swap[s.team]) for s in c.spells)
    )


def inserted(events: list[Event], e: Event) -> list[Event]:
    """`e` after every event up to its period and clock."""
    at = next(
        (i for i, x in enumerate(events) if (x.period, x.clock_ms) > (e.period, e.clock_ms)),
        len(events),
    )
    return events[:at] + [e] + events[at:]


@st.composite
def moments_in(draw, events: list[Event], window) -> tuple[int, int]:
    """A period and clock inside the window and before that period's end."""
    period, start, end = window
    period = draw(st.sampled_from(PERIODS)) if period is None else period
    last = max(e.clock_ms for e in events if e.period == period)
    low, high = max(start or 0, 0), last if end is None else min(last, end)
    assume(low <= high)
    return period, draw(st.integers(low, high))


@given(event_streams(), windows(), st.data())
def test_one_more_press_high_up_adds_one_and_one_deep_adds_none(stream, window, data):
    teams, events = stream
    meta = meta_of(teams, events)
    period, clock = data.draw(moments_in(events, window))
    team = data.draw(st.sampled_from(teams))
    high = data.draw(st.booleans())
    depth = data.draw(st.integers(5_250, 10_500) if high else st.integers(0, 5_249))
    x = depth if rightwards(meta, team, period) else 10_500 - depth
    kind = data.draw(st.sampled_from(sorted(PRESSING)))
    outcomes = (
        [Outcome.REGAIN, Outcome.RESISTED] if kind is E.PRESSURE else [Outcome.WON, Outcome.LOST]
    )
    outcome = data.draw(st.sampled_from(outcomes))
    extra = Event(make_event_id(meta.match_id, MAX_SEQ), period, clock, kind, team,
                  f"{team}-p05", Point(x / 100, 34.0), outcome=outcome)  # fmt: skip
    before = {p.team: p.actions for p in pressing(meta, events, *window)}
    after = {p.team: p.actions for p in pressing(meta, inserted(events, extra), *window)}
    assert after == before | {team: before[team] + high}


@given(event_streams(), windows(), st.data())
def test_one_more_shot_never_takes_momentum_away(stream, window, data):
    teams, events = stream
    meta = meta_of(teams, events)
    period, clock = data.draw(moments_in(events, window))
    team = data.draw(st.sampled_from(teams))
    shot = Event(make_event_id(meta.match_id, MAX_SEQ), period, clock, E.SHOT, team,
                 f"{team}-p09", Point(90.0, 34.0), Point(100.0, 34.0), Outcome.OFF_TARGET,
                 duration_ms=1_000)  # fmt: skip
    before = momentum(meta, events, *window)
    after = momentum(meta, inserted(events, shot), *window)
    i = teams.index(team)
    assert after.weights[i] == before.weights[i] + SHOT_WEIGHT
    assert after.weights[1 - i] == before.weights[1 - i]
    assert after.percent[i] >= before.percent[i] and after.percent[1 - i] <= before.percent[1 - i]


@given(event_streams(), st.data())
def test_a_prefix_gives_the_live_values(stream, data):
    teams, events = stream
    meta = meta_of(teams, events)
    k = data.draw(st.integers(0, len(events) - 1))
    now = events[k]
    prefix = [e for e in events if (e.period, e.clock_ms) <= (now.period, now.clock_ms)]
    start = data.draw(st.none() | st.integers(-10_000, now.clock_ms))
    window = (now.period, start, now.clock_ms)
    assert pressing(meta, prefix, *window)[0].window_ms == oracle_window_ms(prefix, window)
    assert pressing(meta, prefix, *window) == pressing(meta, events, *window)
    assert momentum(meta, prefix, *window) == momentum(meta, events, *window)

    def numbers(c: Control):
        return c.window_ms, c.ball_ms, c.possessions, c.change_ids, c.chaos

    assert numbers(control(prefix, *window)) == numbers(control(events, *window))

    # the match so far: the full stream's earlier periods, and the current one up to now
    so_far = [(p, None) for p in PERIODS if p < now.period] + [(now.period, now.clock_ms)]

    def press(*args):
        home, away = pressing(meta, *args)
        return home.actions, home.window_ms, away.actions, away.window_ms

    def weights(*args):
        return momentum(meta, *args).weights

    def ball(*args):
        c = control(*args)
        return c.ball_ms, c.possessions, c.changes, c.window_ms

    for index in (press, weights, ball):
        parts = [index(events, p, None, end) for p, end in so_far]
        assert index(prefix) == tuple(map(sum, zip(*parts, strict=True)))


# --- real matches -------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [3, 7])
def test_real_match_periods_add_up_to_the_match(seed):
    m = real.match(seed)
    meta, events = m.meta, m.events
    whole, halves = pressing(meta, events), [pressing(meta, events, p) for p in PERIODS]
    for i in (0, 1):
        assert whole[i].actions == sum(h[i].actions for h in halves) > 0
        assert whole[i].window_ms == sum(h[i].window_ms for h in halves)
    mo, mo_halves = momentum(meta, events), [momentum(meta, events, p) for p in PERIODS]
    assert mo.weights == tuple(map(sum, zip(*(h.weights for h in mo_halves), strict=True)))
    c, c_halves = control(events), [control(events, p) for p in PERIODS]
    assert c.changes == sum(h.changes for h in c_halves) > 200
    assert c.possessions == c.changes + 2
    assert c.ball_ms == sum(h.ball_ms for h in c_halves)
    assert 40 <= c.chaos <= 60  # a whole match is close to typical (seeds 0–49: 47–52)


@pytest.mark.parametrize("seed", [3, 7])
def test_real_match_rolling_windows(seed):
    m = real.match(seed)
    for period in PERIODS:
        last = max(e.clock_ms for e in m.events if e.period == period)
        for end in range(300_000, last + 1, 60_000):
            window = (period, end - 300_000, end)
            c = control(m.events, *window)
            assert c.window_ms == 300_000 and 0 < c.ball_ms <= 300_000
            assert c.possessions >= 1 and 0 <= c.chaos <= 100
            assert sum(momentum(m.meta, m.events, *window).percent) == 100
