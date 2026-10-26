import functools
import itertools
import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from strategies import CLUBS, events, lineup, periods, two_clubs

from matchlens.events import (
    FRAME_MS,
    MAX_BALL_SPEED,
    PITCH_LENGTH,
    PITCH_WIDTH,
    Event,
    EventType,
    Outcome,
    PlayerPosition,
    Point,
    TrackingFrame,
    make_event_id,
    make_frame_id,
)
from matchlens.generator import generate_match
from matchlens.match import PLAYER_SPEED_LIMIT
from matchlens.stats.passing import pass_ratings
from matchlens.stats.speed import (
    HARD_SHOT_MS,
    SPRINT_MS,
    BallSpeed,
    Movement,
    Tag,
    ball_speeds,
    hard_shot_tags,
    movement,
    sprint_tags,
    upward_crossings,
)

H, A = CLUBS[:2]
PLAYERS = lineup(H) + lineup(A)
RUNNER = PLAYERS[0]


def frame(clock: int, at: tuple[float, float], period: int = 1) -> TrackingFrame:
    """Everyone stands still at the centre spot except RUNNER, who is `at`."""
    positions = [PlayerPosition(p, 52.5, 34.0) for p in PLAYERS]
    positions[0] = PlayerPosition(RUNNER, *at)
    return TrackingFrame(make_frame_id("m1", period, clock), period, clock, positions, Point(0, 0))


def shot(seq: int, metres: float, ms: int = 1_000) -> Event:
    return Event(
        make_event_id("m1", seq), 1, 10_000 * seq, EventType.SHOT, H, f"{H}-p09",
        Point(50, 34), end=Point(50 + metres, 34), duration_ms=ms, outcome=Outcome.OFF_TARGET,
    )  # fmt: skip


# --- examples ----------------------------------------------------------------------------------


def test_a_run_of_two_steps():
    frames = [frame(0, (0, 0)), frame(100, (3, 4)), frame(200, (3, 4))]
    ids = tuple(f.frame_id for f in frames)
    assert movement(frames)[RUNNER] == Movement(RUNNER, 5.0, 50.0, ids[:2], (ids[0], ids[2]))
    assert movement(frames)[PLAYERS[1]] == Movement(PLAYERS[1], 0.0, 0.0, (), (ids[0], ids[2]))


def test_one_frame_has_no_movement():
    m = movement([frame(0, (10, 10))])[RUNNER]
    assert (m.distance_m, m.top_speed_ms, m.top_speed_frames) == (0.0, 0.0, ())


def test_the_two_periods_are_not_joined():
    # period 2 clocked later than period 1 ends, so only the period tells the stretches apart
    frames = [frame(0, (0, 0)), frame(100, (1, 0)), frame(200, (90, 0), 2), frame(300, (91, 0), 2)]
    assert movement(frames)[RUNNER].distance_m == 2.0


def test_sprint_tags_fire_on_reaching_the_threshold():
    # speeds 2.5, 7.5, 7.5, 2.5, 7.5 m/s: 0.75 m in 100 ms is 7.5 m/s
    xs = (0, 0.25, 1.0, 1.75, 2.0, 2.75)
    frames = [frame(100 * i, (x, 0)) for i, x in enumerate(xs)]
    tags = sprint_tags(frames, threshold=7.5)
    assert [t.clock_ms for t in tags] == [200, 500]
    assert all(t.kind == "sprint" and t.player == RUNNER for t in tags)
    assert tags[0].source_ids == (frames[1].frame_id, frames[2].frame_id)
    assert sprint_tags(frames, threshold=7.51) == []
    # by default at the 7 m/s line; a tag carries the speed reached, not the threshold
    assert [(t.clock_ms, t.speed_ms) for t in sprint_tags(frames)] == [(200, 7.5), (500, 7.5)]


def test_the_thresholds_decided():
    assert (SPRINT_MS, HARD_SHOT_MS) == (7.0, 28.0)  # owner 20 Oct; p80 of shots, seeds 0-49


def test_a_slow_walk_counts_in_full():
    frames = [frame(100 * i, (0.0625 * i, 0)) for i in range(9)]  # 0.625 m/s for 0.8 s
    assert movement(frames)[RUNNER].distance_m == 0.5


def test_hard_shots_at_the_threshold_and_below():
    shots = [shot(0, HARD_SHOT_MS), shot(1, HARD_SHOT_MS - 0.01), shot(2, 30.0)]
    assert [t.source_ids for t in hard_shot_tags(shots)] == [("m1-e00000",), ("m1-e00002",)]
    assert hard_shot_tags(shots)[0] == Tag("hard_shot", f"{H}-p09", 1, 0, 28.0, ("m1-e00000",))


def test_ball_speed_is_the_events_own():
    e = shot(0, 30.0, ms=1_200)
    assert ball_speeds([e]) == [
        BallSpeed("m1-e00000", 1, 0, 1_200, EventType.SHOT, H, f"{H}-p09", 25.0)
    ]


@pytest.mark.parametrize(
    ("values", "crossings"),
    [
        ([], []),
        ([5], [0]),  # nothing before the first value
        ([4.9, 5, 5, 4, 6], [1, 4]),
        ([6, 7, 4.99], [0]),
    ],
)
def test_upward_crossings_examples(values, crossings):
    assert upward_crossings(values, 5) == crossings


# --- properties --------------------------------------------------------------------------------

cm = st.integers(0, round(PITCH_LENGTH * 100)).map(lambda v: v / 100)
cm_y = st.integers(0, round(PITCH_WIDTH * 100)).map(lambda v: v / 100)


@st.composite
def frame_streams(draw, period=None, clubs=None) -> list[TrackingFrame]:
    """Consecutive 10 Hz frames of one period, everyone anywhere in each."""
    home, away = draw(two_clubs) if clubs is None else clubs
    players = lineup(home) + lineup(away)
    period = draw(periods) if period is None else period
    start = draw(st.integers(0, 1_000)) * FRAME_MS
    stream = []
    for i in range(draw(st.integers(1, 8))):
        clock = start + i * FRAME_MS
        stream.append(
            TrackingFrame(
                make_frame_id("m1", period, clock),
                period,
                clock,
                tuple(PlayerPosition(p, draw(cm), draw(cm_y)) for p in players),
                Point(draw(cm), draw(cm_y)),
            )
        )
    return stream


def position(f: TrackingFrame, player: str) -> tuple[float, float]:
    p = next(p for p in f.players if p.player == player)
    return p.x, p.y


@given(frame_streams(), st.data())
def test_distance_adds_up_over_adjacent_stretches(frames, data):
    cut = data.draw(st.integers(0, len(frames) - 1))
    whole, early, late = movement(frames), movement(frames[: cut + 1]), movement(frames[cut:])
    for player, m in whole.items():
        both = early[player].distance_m + late[player].distance_m
        assert math.isclose(m.distance_m, both, rel_tol=1e-9, abs_tol=1e-9)
        assert m.top_speed_ms == max(early[player].top_speed_ms, late[player].top_speed_ms)


@given(frame_streams())
def test_distance_at_least_the_straight_line_and_top_speed_at_least_the_average(frames):
    seconds = (frames[-1].clock_ms - frames[0].clock_ms) / 1000
    for player, m in movement(frames).items():
        (x0, y0), (x1, y1) = position(frames[0], player), position(frames[-1], player)
        assert m.distance_m >= math.hypot(x1 - x0, y1 - y0) - 1e-9
        assert m.frame_ids == (frames[0].frame_id, frames[-1].frame_id)
        if seconds:
            assert m.top_speed_ms >= m.distance_m / seconds - 1e-9
        # the top speed and the first pair of frames that reached it
        path = [position(f, player) for f in frames]
        speeds = [
            math.hypot(b[0] - a[0], b[1] - a[1]) * 1000 / FRAME_MS
            for a, b in itertools.pairwise(path)
        ]
        top = max(speeds, default=0.0)
        pair = () if top == 0 else (frames[speeds.index(top)], frames[speeds.index(top) + 1])
        assert m.top_speed_ms == top
        assert m.top_speed_frames == tuple(f.frame_id for f in pair)


@given(two_clubs, st.data())
def test_periods_are_counted_apart(clubs, data):
    first = data.draw(frame_streams(period=1, clubs=clubs))
    second = data.draw(frame_streams(period=2, clubs=clubs))
    whole, apart = movement(first + second), (movement(first), movement(second))
    for player, m in whole.items():
        both = apart[0][player].distance_m + apart[1][player].distance_m
        assert math.isclose(m.distance_m, both, rel_tol=1e-9, abs_tol=1e-9)


@given(st.lists(st.floats(0, 20, allow_nan=False)), st.floats(0, 20, allow_nan=False))
def test_upward_crossings_fire_exactly_where_the_threshold_is_reached(values, threshold):
    got = upward_crossings(values, threshold)
    for i, v in enumerate(values):
        reached = v >= threshold and (i == 0 or values[i - 1] < threshold)
        assert (i in got) == reached
    assert got == sorted(set(got))


@given(frame_streams(), st.floats(0, 2_000, allow_nan=False), st.data())
def test_sprint_tags_are_the_crossings_of_each_players_speeds(frames, threshold, data):
    tags = sprint_tags(frames, threshold)
    for player in {p.player for p in frames[0].players}:
        path = [position(f, player) for f in frames]
        speeds = [
            math.hypot(b[0] - a[0], b[1] - a[1]) * 1000 / FRAME_MS
            for a, b in itertools.pairwise(path)
        ]
        mine = [t for t in tags if t.player == player]
        assert mine == [
            Tag(
                "sprint",
                player,
                frames[i + 1].period,
                frames[i + 1].clock_ms,
                speeds[i],
                (frames[i].frame_id, frames[i + 1].frame_id),
            )
            for i in upward_crossings(speeds, threshold)
        ]
    assert [t.clock_ms for t in tags] == sorted(t.clock_ms for t in tags)
    k = data.draw(st.integers(1, len(frames)))  # live: a prefix gives the tags so far
    now = (frames[k - 1].period, frames[k - 1].clock_ms)
    assert sprint_tags(frames[:k], threshold) == [t for t in tags if (t.period, t.clock_ms) <= now]


@given(st.lists(events(match_id="m1"), max_size=20), st.floats(0, 60, allow_nan=False))
def test_hard_shot_tags_are_the_shots_at_or_above_the_threshold(stream, threshold):
    assert hard_shot_tags(stream, threshold) == [
        Tag("hard_shot", e.player, e.period, e.clock_ms, e.ball_speed(), (e.event_id,))
        for e in stream
        if e.type is EventType.SHOT and e.ball_speed() >= threshold
    ]


@given(two_clubs, st.floats(0, 2_000, allow_nan=False), st.data())
def test_sprints_restart_with_each_period(clubs, threshold, data):
    first = data.draw(frame_streams(period=1, clubs=clubs))
    second = data.draw(frame_streams(period=2, clubs=clubs))
    whole = sprint_tags(first + second, threshold)
    assert whole == sprint_tags(first, threshold) + sprint_tags(second, threshold)
    # live across half-time: (period, clock) orders the tags, the clock alone does not
    frames = first + second
    k = data.draw(st.integers(1, len(frames)))
    now = (frames[k - 1].period, frames[k - 1].clock_ms)
    assert sprint_tags(frames[:k], threshold) == [t for t in whole if (t.period, t.clock_ms) <= now]


@given(st.lists(events(match_id="m1"), max_size=20))
def test_ball_speeds_wrap_the_event_formula(stream):
    flights = [e for e in stream if e.type in (EventType.PASS, EventType.SHOT, EventType.CLEARANCE)]
    got = ball_speeds(stream)
    assert [s.event_id for s in got] == [e.event_id for e in flights]
    for s, e in zip(got, flights, strict=True):
        assert s.speed_ms == e.ball_speed() <= MAX_BALL_SPEED
        assert (s.period, s.clock_ms) == (e.period, e.clock_ms)
        assert s.arrival_ms == e.clock_ms + e.duration_ms
        assert (s.type, s.team, s.player) == (e.type, e.team, e.player)


# --- a real match ------------------------------------------------------------------------------


@functools.cache
def match7():
    return generate_match(7)


def test_real_match_movement_within_the_caps():
    """One pass over the 57 000 frames of match 7 (about 4 s)."""
    m = match7()
    moved = movement(m.frames())
    assert set(moved) == set(m.meta.home_lineup + m.meta.away_lineup)
    for mv in moved.values():
        assert 4_000 < mv.distance_m < 15_000  # seeds 0-49: keepers 4.2-5.0 km, others 10.4-14.6
        # frames are rounded to the centimetre, so 100 ms steps carry up to 0.2 m/s of noise
        assert 0 < mv.top_speed_ms <= PLAYER_SPEED_LIMIT + 0.2
    for s in ball_speeds(m.events):
        assert 0 < s.speed_ms <= MAX_BALL_SPEED
    # one formula: a pass's speed over its flight time is the length the pass rating measured
    durations = {e.event_id: e.duration_ms for e in m.events}
    lengths = {r.event_id: r.length_m for r in pass_ratings(m.meta, m.events, m.snapshots)}
    for s in ball_speeds(m.events):
        if s.type is EventType.PASS:
            assert math.isclose(s.speed_ms * durations[s.event_id] / 1000, lengths[s.event_id],
                                rel_tol=1e-9, abs_tol=1e-9)  # fmt: skip
    assert hard_shot_tags(m.events) == [
        t for t in hard_shot_tags(m.events, 0.0) if t.speed_ms >= HARD_SHOT_MS
    ]


@settings(deadline=None, max_examples=20)
@given(st.integers(2, 3_000), st.data())
def test_real_match_stretches_add_up_and_sprints_are_live(n, data):
    frames = list(itertools.islice(match7().frames(), n))
    cut = data.draw(st.integers(0, n - 1))
    whole, early, late = movement(frames), movement(frames[: cut + 1]), movement(frames[cut:])
    for player, m in whole.items():
        both = early[player].distance_m + late[player].distance_m
        assert math.isclose(m.distance_m, both, rel_tol=1e-9, abs_tol=1e-9)
        # within the schema's cap; frames are rounded to the centimetre: up to 0.2 m/s of noise
        assert m.top_speed_ms <= PLAYER_SPEED_LIMIT + 0.2
    tags = sprint_tags(frames, 6.0)
    assert sprint_tags(frames[: cut + 1], 6.0) == [
        t for t in tags if (t.period, t.clock_ms) <= (frames[cut].period, frames[cut].clock_ms)
    ]
