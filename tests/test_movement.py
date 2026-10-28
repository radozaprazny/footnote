import math
import random
from unittest.mock import patch

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

import matchlens.movement as movement
from matchlens.events import PITCH_LENGTH, PITCH_WIDTH
from matchlens.movement import (
    DT,
    EDGE_BAND,
    FAR_ENOUGH_M,
    FATIGUE_DROP,
    FATIGUE_FROM_S,
    FATIGUE_FULL_S,
    REACH_WITHIN_S,
    Body,
    Limits,
    _for_the_edge,
    braking_bound,
    braking_distance,
    pace_to_arrive,
    step,
    stopping_speed,
    time_to_reach,
)

# the limits league.py validates (M9 item 2), ends included
top_speeds = st.floats(min_value=6.5, max_value=9.8)
accelerations = st.floats(min_value=4.0, max_value=6.5)
limits = st.builds(Limits, top_speeds, accelerations)
xs = st.floats(min_value=0.0, max_value=PITCH_LENGTH)
ys = st.floats(min_value=0.0, max_value=PITCH_WIDTH)
targets = st.tuples(xs, ys)
# at rest: a named tuple's defaults are drawn by `builds` too, so they are given
inside = st.builds(
    Body,
    st.floats(min_value=EDGE_BAND, max_value=PITCH_LENGTH - EDGE_BAND),
    st.floats(min_value=EDGE_BAND, max_value=PITCH_WIDTH - EDGE_BAND),
    st.just(0.0),
    st.just(0.0),
)
# a leg: a target, the pace asked for and how many steps it lasts before the next target
# a target's own velocity, still or moving in any direction up to 12 m/s
velocities = st.one_of(
    st.just((0.0, 0.0)),
    st.tuples(
        st.floats(min_value=-12.0, max_value=12.0), st.floats(min_value=-12.0, max_value=12.0)
    ),
)
# a leg: a target, the pace asked for, how many steps it lasts and the target's velocity
legs = st.lists(
    st.tuples(targets, st.floats(min_value=0.0, max_value=12.0), st.integers(1, 40), velocities),
    min_size=1,
    max_size=8,
)
EPS = 1e-9


shares = st.floats(min_value=0.25, max_value=1.0)  # an arrival's braking share, MIN_BRAKING up


@given(limits, inside, legs, shares)
def test_a_player_keeps_his_limits_and_the_pitch(limit, start, plan, share):
    body = start
    for target, pace, n, moving in plan:
        for _ in range(n):
            nxt = step(body, target, pace, limit, moving, braking=share)
            assert nxt.speed <= limit.top_speed + EPS
            change = math.hypot(nxt.vx - body.vx, nxt.vy - body.vy)
            assert change <= limit.acceleration * DT + EPS
            assert EDGE_BAND - EPS <= nxt.x <= PITCH_LENGTH - EDGE_BAND + EPS
            assert EDGE_BAND - EPS <= nxt.y <= PITCH_WIDTH - EDGE_BAND + EPS
            # the velocity is the step itself, so the tracking measures what he ran
            assert nxt.x == pytest.approx(body.x + nxt.vx * DT, abs=1e-9)
            assert nxt.y == pytest.approx(body.y + nxt.vy * DT, abs=1e-9)
            body = nxt


@given(limits, inside, targets, shares)
def test_from_rest_he_reaches_the_target_and_stops_on_it(limit, start, target, share):
    goal = (
        min(PITCH_LENGTH - EDGE_BAND, max(EDGE_BAND, target[0])),
        min(PITCH_WIDTH - EDGE_BAND, max(EDGE_BAND, target[1])),
    )
    body, left = start, math.dist((start.x, start.y), goal)
    # 30 s: the diagonal at 6.5 m/s, and a gentle stop from it at a quarter of 4 m/s²
    for _ in range(300):
        body = step(body, target, limit.top_speed, limit, braking=share)
        now = math.dist((body.x, body.y), goal)
        assert now <= left + EPS  # never past the target and back
        left = now
        if left == 0.0 and body.speed == 0.0:
            return
    pytest.fail(f"still {left:.3f} m away, at {body.speed:.3f} m/s")


@given(limits, inside, targets)
def test_a_pace_of_zero_brings_him_to_a_stop(limit, start, target):
    body = Body(start.x, start.y, limit.top_speed * 0.6, 0.0)
    for _ in range(40):
        body = step(body, target, 0.0, limit)
    assert body.speed == 0.0


# step brakes with the acceleration, with it over sqrt 2 for an edge, and with tired values
brakings = st.floats(min_value=2.5, max_value=6.5)


@given(st.floats(min_value=0.0, max_value=200.0), brakings)
def test_stopping_speed_stops_exactly_on_the_point(distance, acceleration):
    s, dv = stopping_speed(distance, acceleration), acceleration * DT
    braked = sum(max(0.0, s - k * dv) for k in range(int(s / dv) + 2)) * DT
    assert braked == pytest.approx(distance, abs=1e-9)


@given(st.floats(min_value=0.0, max_value=200.0), brakings)
def test_braking_distance_is_the_inverse_of_stopping_speed(distance, acceleration):
    s = stopping_speed(distance, acceleration)
    assert braking_distance(s, acceleration) == pytest.approx(distance, abs=1e-9)


@given(st.floats(min_value=0.0, max_value=12.0), brakings)
def test_stopping_speed_is_the_inverse_of_braking_distance(speed, acceleration):
    d = braking_distance(speed, acceleration)
    assert stopping_speed(d, acceleration) == pytest.approx(speed, abs=1e-9)


def test_stopping_speed_at_its_steps():
    # a = 5 m/s²: dv = 0.5 m/s a step; one step's worth of distance at dv is 0.05 m
    assert stopping_speed(0.0, 5.0) == 0.0
    assert stopping_speed(-1.0, 5.0) == 0.0
    assert stopping_speed(0.05, 5.0) == pytest.approx(0.5)  # one step at dv, then 0
    assert stopping_speed(0.15, 5.0) == pytest.approx(1.0)  # 1.0 then 0.5
    assert stopping_speed(0.30, 5.0) == pytest.approx(1.5)  # 1.5, 1.0, 0.5
    # one unit either side of each piece's end: continuous and never falling through it
    for end, s in ((0.05, 0.5), (0.15, 1.0), (0.30, 1.5)):
        below = stopping_speed(math.nextafter(end, 0.0), 5.0)
        above = stopping_speed(math.nextafter(end, 1.0), 5.0)
        assert below <= stopping_speed(end, 5.0) <= above
        assert below == pytest.approx(s) and above == pytest.approx(s)


@pytest.mark.parametrize("stamina", [0.0, 0.5, 1.0])
def test_fatigue_starts_at_the_30th_minute_and_is_full_at_the_45th(stamina):
    fresh = Limits(9.0, 5.0)
    drop = FATIGUE_DROP * (1.0 - stamina)
    assert fresh.tired(stamina, 0.0) == fresh
    assert fresh.tired(stamina, FATIGUE_FROM_S) == fresh
    one_step_later = fresh.tired(stamina, FATIGUE_FROM_S + DT)
    assert one_step_later.top_speed == pytest.approx(
        9.0 * (1 - drop * DT / (FATIGUE_FULL_S - FATIGUE_FROM_S))
    )
    full = fresh.tired(stamina, FATIGUE_FULL_S)
    assert full.top_speed == pytest.approx(9.0 * (1 - drop))
    assert full.acceleration == pytest.approx(5.0 * (1 - drop))
    assert fresh.tired(stamina, FATIGUE_FULL_S - DT).top_speed > full.top_speed or drop == 0
    assert fresh.tired(stamina, FATIGUE_FULL_S + 600.0) == full  # stoppage time tires no more


@given(limits, st.floats(min_value=0.0, max_value=1.0), st.floats(min_value=0.0, max_value=4000))
def test_a_tired_player_keeps_at_least_nine_tenths_of_his_limits(limit, stamina, half_s):
    tired = limit.tired(stamina, half_s)
    assert 0.9 * limit.top_speed - EPS <= tired.top_speed <= limit.top_speed
    assert 0.9 * limit.acceleration - EPS <= tired.acceleration <= limit.acceleration


def test_a_speed_above_tired_limits_falls_to_them():
    fresh, tired = Limits(9.0, 5.0), Limits(8.1, 4.5)
    body = Body(50.0, 34.0, 9.0, 0.0)
    after = step(body, (100.0, 34.0), 9.0, tired)
    assert after.speed == pytest.approx(8.1)
    assert fresh.top_speed > after.speed


# per edge: a target beyond it, on the band's edge and one unit inside, and where he ends
EDGES = [
    ((PITCH_LENGTH, 34.0), (PITCH_LENGTH - EDGE_BAND, 34.0), (-1.0, 0.0)),
    ((0.0, 34.0), (EDGE_BAND, 34.0), (1.0, 0.0)),
    ((52.5, PITCH_WIDTH), (52.5, PITCH_WIDTH - EDGE_BAND), (0.0, -1.0)),
    ((52.5, 0.0), (52.5, EDGE_BAND), (0.0, 1.0)),
]


@pytest.mark.parametrize(("beyond", "edge", "inwards"), EDGES)
def test_a_target_is_taken_no_nearer_the_line_than_the_band(beyond, edge, inwards):
    limit = Limits(8.0, 5.0)
    one_inside = tuple(math.nextafter(c, c + i) for c, i in zip(edge, inwards, strict=True))
    for target, end in ((beyond, edge), (edge, edge), (one_inside, one_inside)):
        body = Body(*(c + 3.0 * i for c, i in zip(edge, inwards, strict=True)))
        for _ in range(40):
            body = step(body, target, 5.0, limit)
        assert (body.x, body.y) == pytest.approx(end, abs=1e-12)
        assert body.speed == 0.0


CORNER_BRAKING = 4.0 / math.sqrt(2.0)  # what is left of 4 m/s² on one axis in a corner
STOPS = 1.5404401145198807  # m/s: from this speed he stops 0.5 m ahead, at that braking


@pytest.mark.parametrize(
    ("v", "asked", "forced"),
    [
        (2.0, 2.0 - STOPS, True),  # the edge turns the asked change round, as large
        (2.0, math.nextafter(2.0 - STOPS, math.inf), True),  # turned round, a unit smaller
        (2.0, math.nextafter(2.0 - STOPS, 0.0), True),  # turned round and larger
        (STOPS, 0.5, False),  # held where he is: no change, not one the other way
        (0.5, 2.0, False),  # merely shorter, the same way
    ],
)
def test_an_edge_that_turns_the_asked_change_round_forces_it(v, asked, forced):
    # 0.5 m short of the band's edge at 67.5 m, moving at it and asked to speed up
    assert stopping_speed(0.5, CORNER_BRAKING) == STOPS
    assert STOPS - 2.0 == -(2.0 - STOPS)  # the change made is exactly the asked one, reversed
    assert _for_the_edge(v, asked, 67.0, PITCH_WIDTH, CORNER_BRAKING) == (STOPS, forced)


@settings(deadline=None)  # up to 3 200 steps an example
@given(limits, st.floats(min_value=0.0, max_value=1.0), inside, legs)
# into the corner at (105, 0) behind a target running at it: the edge of y turned the asked
# change round and was taken for merely shortening it, so x's braking cut y's (fixed 27 Oct)
@example(
    limit=Limits(9.0, 4.0),
    stamina=0.0,
    start=Body(1.0, 41.0),
    plan=[
        ((0.0, 0.0), 0.0, 1, (0.0, 0.0)),
        ((0.0, 0.0), 0.0, 1, (0.0, 0.0)),
        ((0.0, 59.0), 4.0, 4, (0.0, 0.0)),
        ((0.0, 0.0), 0.0, 15, (9.5625, -5.78125)),
    ],
)
def test_a_tiring_player_keeps_his_tired_limits(limit, stamina, start, plan):
    # through the fatigue window, every step with the limits of its own moment; a speed reached
    # before may exceed the newly tired top speed only by what the limit fell in that step
    body, half_s = start, FATIGUE_FROM_S - 10.0
    previous = limit.tired(stamina, half_s)
    for target, pace, n, moving in plan:
        for _ in range(n * 10):
            half_s += DT
            now = limit.tired(stamina, half_s)
            nxt = step(body, target, pace, now, moving)
            assert nxt.speed <= now.top_speed + EPS
            change = math.hypot(nxt.vx - body.vx, nxt.vy - body.vy)
            fell = previous.top_speed - now.top_speed
            # braking for an edge may cost up to 0.1 % more: the edge's bounds move as he tires
            assert change <= now.acceleration * DT * 1.001 + fell + EPS
            assert 0.0 < nxt.x < PITCH_LENGTH and 0.0 < nxt.y < PITCH_WIDTH
            body, previous = nxt, now


def test_the_constants_are_the_plans():
    # PROGRESS, M9 item 3: tiring from the 30th minute of a half to the 45th, by at most 10 %;
    # targets and braking 0.5 m inside the pitch
    assert (FATIGUE_FROM_S, FATIGUE_FULL_S, FATIGUE_DROP) == (1800, 2700, 0.10)
    assert EDGE_BAND == 0.5
    assert DT == 0.1
    assert REACH_WITHIN_S == 30.0


def _run(body, legs, limit):
    """Steps through (target, pace, until) legs, `until` a test on the body that ends a leg;
    asserts the limits and the band at every step and returns the bodies."""
    path = [body]
    for target, pace, until in legs:
        for _ in range(400):
            nxt = step(body, target, pace, limit)
            assert nxt.speed <= limit.top_speed + EPS
            assert math.hypot(nxt.vx - body.vx, nxt.vy - body.vy) <= limit.acceleration * DT + EPS
            assert EDGE_BAND - EPS <= nxt.x <= PITCH_LENGTH - EDGE_BAND + EPS
            assert EDGE_BAND - EPS <= nxt.y <= PITCH_WIDTH - EDGE_BAND + EPS
            body = nxt
            path.append(body)
            if until(body):
                break
    return path


EXTREMES = [Limits(9.8, 6.5), Limits(9.8, 4.0), Limits(6.5, 4.0), Limits(8.0, 5.0)]
# (start, legs): flat out at an edge or a corner, then a target that turns him along it or away;
# without the braking for the edge, its priority over the turn or its sqrt 2 for a corner, his
# momentum carried him onto the line or past his acceleration
TURNS = {
    "along the touchline": (
        (50.0, 34.0),
        [
            ((50.0, PITCH_WIDTH), lambda b: b.y >= PITCH_WIDTH - EDGE_BAND - 7.0),
            ((100.0, PITCH_WIDTH), lambda b: b.x >= 99.0),
        ],
    ),
    "along the other touchline": (
        (50.0, 34.0),
        [((50.0, 0.0), lambda b: b.y <= EDGE_BAND + 3.0), ((5.0, 0.0), lambda b: b.x <= 6.0)],
    ),
    "out of a corner along the goal line": (
        (70.0, 34.0),
        [
            ((PITCH_LENGTH, PITCH_WIDTH), lambda b: b.x >= PITCH_LENGTH - 6.0),
            ((PITCH_LENGTH, 0.0), lambda b: b.y <= 20.0),
        ],
    ),
    "out of a corner along the touchline": (
        (35.0, 34.0),
        [((0.0, 0.0), lambda b: b.x <= 4.0), ((60.0, 0.0), lambda b: b.x >= 50.0)],
    ),
    "a zigzag on the goal line": (
        (90.0, 34.0),
        [
            ((PITCH_LENGTH, 60.0), lambda b: b.x >= PITCH_LENGTH - 2.0),
            ((PITCH_LENGTH, 10.0), lambda b: b.y <= 40.0),
            ((PITCH_LENGTH, 60.0), lambda b: b.y >= 50.0),
        ],
    ),
}


@pytest.mark.parametrize("limit", EXTREMES)
@pytest.mark.parametrize("turn", sorted(TURNS))
def test_a_turn_at_an_edge_keeps_his_limits_and_the_band(turn, limit):
    start, legs = TURNS[turn]
    path = _run(Body(*start), [(target, 12.0, until) for target, until in legs], limit)
    assert len(path) > 10


def test_stopping_speed_far_beyond_any_run():
    assert stopping_speed(FAR_ENOUGH_M, 4.0) < math.inf
    assert stopping_speed(math.nextafter(FAR_ENOUGH_M, math.inf), 4.0) == math.inf
    assert stopping_speed(1e300, 4.0) == math.inf


@pytest.mark.parametrize(
    ("heading", "target"),
    [((7.0, 0.0), (20.0, 34.0)), ((5.0, -5.0), (25.0, 60.0)), ((0.0, 6.5), (40.0, 8.0))],
)
def test_a_pursuer_runs_with_a_moving_target(heading, target):
    # the target is where it is now and moves at `heading` during the step, so after a step a
    # pursuer told its velocity stands where the target is at the step's end: on it, not behind
    # or ahead; 8 s keep every target on the pitch
    limit = Limits(9.5, 5.0)
    body = Body(target[0] - 10.0, target[1] - 4.0)
    for _ in range(80):
        body = step(body, target, 4.0, limit, heading)
        target = (target[0] + heading[0] * DT, target[1] + heading[1] * DT)
    assert (body.x, body.y) == pytest.approx(target, abs=1e-6)
    assert (body.vx, body.vy) == pytest.approx(heading, abs=1e-6)


def test_a_pursuer_on_the_target_moves_with_it():
    body = Body(50.0, 34.0, 3.0, 0.0)
    after = step(body, (50.0, 34.0), 0.0, Limits(9.0, 5.0), (3.0, 0.0))
    assert (after.x, after.y, after.vx, after.vy) == pytest.approx((50.3, 34.0, 3.0, 0.0))


def test_untold_he_trails_a_moving_target_by_his_braking_distance():
    # each point taken as a place to stop: he settles where his stopping speed is the target's
    limit = Limits(9.5, 5.0)
    target, body = (10.0, 34.0), Body(2.0, 34.0)
    for _ in range(120):  # the target ends at x = 94
        body = step(body, target, limit.top_speed, limit)
        target = (target[0] + 7.0 * DT, target[1])
    assert target[0] - body.x == pytest.approx(braking_distance(7.0, 5.0), abs=0.05)


# per edge: a start off its axis, a target beyond the edge and the same target on the band; the
# beyond one is taken on the band, so both paths are the same step by step
CLAMPED = [
    ((90.0, 20.0), (110.0, 50.0), (PITCH_LENGTH - EDGE_BAND, 50.0)),
    ((15.0, 20.0), (-5.0, 50.0), (EDGE_BAND, 50.0)),
    ((40.0, 50.0), (70.0, 75.0), (70.0, PITCH_WIDTH - EDGE_BAND)),
    ((40.0, 20.0), (70.0, -7.0), (70.0, EDGE_BAND)),
]


@pytest.mark.parametrize(("start", "beyond", "on_band"), CLAMPED)
def test_a_target_beyond_an_edge_is_the_point_on_the_band(start, beyond, on_band):
    limit = Limits(8.5, 5.5)
    a = b = Body(*start)
    for _ in range(120):
        a, b = step(a, beyond, 7.0, limit), step(b, on_band, 7.0, limit)
        assert (a.x, a.y, a.vx, a.vy) == (b.x, b.y, b.vx, b.vy)
    assert (a.x, a.y) == pytest.approx(on_band)


def _seeded_run(seed):
    """Random legs with moving targets, drawn from `seed`; asserts the limits and the band at
    every step. Seeds 128 and 1398 broke an edge braking 0.1 % too weak and an axis counted as
    forced whenever its edge bound cut it."""
    rng = random.Random(seed)
    limit = Limits(
        rng.choice([6.5, 9.8, rng.uniform(6.5, 9.8)]), rng.choice([4.0, 6.5, rng.uniform(4, 6.5)])
    )
    body = Body(
        rng.uniform(EDGE_BAND, PITCH_LENGTH - EDGE_BAND),
        rng.uniform(EDGE_BAND, PITCH_WIDTH - EDGE_BAND),
    )
    plan = []
    for _ in range(6):
        target = (
            rng.choice([0.0, PITCH_LENGTH, rng.uniform(0, PITCH_LENGTH)]),
            rng.choice([0.0, PITCH_WIDTH, rng.uniform(0, PITCH_WIDTH)]),
        )
        moving = (rng.uniform(-12, 12), rng.uniform(-12, 12))
        plan.append((target, rng.uniform(0, 12), rng.randint(1, 40), moving))
    for target, pace, n, moving in plan:
        for _ in range(n):
            nxt = step(body, target, pace, limit, moving)
            assert nxt.speed <= limit.top_speed + EPS
            assert math.hypot(nxt.vx - body.vx, nxt.vy - body.vy) <= limit.acceleration * DT + EPS
            assert EDGE_BAND - EPS <= nxt.x <= PITCH_LENGTH - EDGE_BAND + EPS
            assert EDGE_BAND - EPS <= nxt.y <= PITCH_WIDTH - EDGE_BAND + EPS
            body = nxt


@pytest.mark.parametrize("seed", [128, 1398, 0, 1, 2, 3])
def test_seeded_runs_after_moving_targets_keep_the_limits_and_the_band(seed):
    _seeded_run(seed)


@pytest.mark.parametrize(
    ("target", "pace", "velocity"),
    [
        ((math.nan, 34.0), 5.0, (0.0, 0.0)),
        ((50.0, math.inf), 5.0, (0.0, 0.0)),
        ((50.0, 34.0), math.nan, (0.0, 0.0)),
        ((50.0, 34.0), math.inf, (0.0, 0.0)),
        ((50.0, 34.0), -0.01, (0.0, 0.0)),
        ((50.0, 34.0), math.nextafter(0.0, -1.0), (0.0, 0.0)),
        ((50.0, 34.0), 5.0, (math.nan, 0.0)),
        ((50.0, 34.0), 5.0, (0.0, math.nan)),
        ((50.0, 34.0), 5.0, (math.inf, 0.0)),
        ((50.0, 34.0), 5.0, (0.0, -math.inf)),
    ],
)
def test_a_target_or_pace_that_is_no_number_is_refused(target, pace, velocity):
    with pytest.raises(ValueError, match="pace"):
        step(Body(50.0, 30.0), target, pace, Limits(8.0, 5.0), velocity)


@pytest.mark.parametrize("pace", [0.0, -0.0, 0])
def test_a_pace_of_zero_is_accepted(pace):
    assert step(Body(50.0, 30.0), (50.0, 34.0), pace, Limits(8.0, 5.0)).speed == 0.0


@pytest.mark.parametrize("share", [0.6, 1.0])
def test_an_arrival_brakes_with_the_share_it_is_given(share):
    # straight from rest to a still target 20 m off: he speeds up at his full acceleration, but
    # slows down on the way in by no more than the share of it, and stops on the target
    limit = Limits(9.0, 5.0)
    body, slowest = Body(30.0, 34.0), 0.0
    for _ in range(200):
        nxt = step(body, (50.0, 34.0), 9.0, limit, braking=share)
        slowest = max(slowest, body.speed - nxt.speed)
        body = nxt
    assert (body.x, body.y, body.speed) == pytest.approx((50.0, 34.0, 0.0))
    assert slowest <= share * limit.acceleration * DT + EPS
    assert slowest == pytest.approx(share * limit.acceleration * DT, rel=0.01)


@pytest.mark.parametrize(
    "share", [0.0, math.nextafter(0.25, 0.0), math.nextafter(1.0, 2.0), math.nan]
)
def test_a_braking_share_outside_its_range_is_refused(share):
    with pytest.raises(ValueError, match="braking share"):
        step(Body(50.0, 30.0), (50.0, 34.0), 5.0, Limits(8.0, 5.0), braking=share)


@pytest.mark.parametrize("share", [0.25, 1.0])  # MIN_BRAKING and all of it
def test_a_braking_share_on_its_ends_is_accepted(share):
    step(Body(50.0, 30.0), (50.0, 34.0), 5.0, Limits(8.0, 5.0), braking=share)


def _arrives(body, target, pace, limit, within_s):
    tx = min(PITCH_LENGTH - EDGE_BAND, max(EDGE_BAND, target[0]))
    ty = min(PITCH_WIDTH - EDGE_BAND, max(EDGE_BAND, target[1]))
    for _ in range(int(within_s / DT + 1e-9)):
        body = step(body, target, pace, limit)
        if math.hypot(tx - body.x, ty - body.y) < 0.01:
            return True
    return False


@given(
    limits,
    st.floats(min_value=10.0, max_value=95.0),
    st.floats(min_value=10.0, max_value=58.0),
    st.tuples(st.floats(-5.0, 5.0), st.floats(-5.0, 5.0)),
    targets,
    st.floats(min_value=0.3, max_value=4.0),
)
def test_pace_to_arrive_is_the_lowest_pace_that_gets_him_there_in_time(
    limit, x, y, moving, target, within_s
):
    body = Body(x, y, *moving)
    pace = pace_to_arrive(body, target, within_s, limit)
    assert 0.0 <= pace <= limit.top_speed
    if _arrives(body, target, pace, limit, within_s):
        # the lowest: a hundredth of a metre per second less (four bisection steps) is late
        if pace >= 0.01:
            assert not _arrives(body, target, pace - 0.01, limit, within_s)
    else:
        assert pace == limit.top_speed  # even flat out he is late: he runs flat out
        assert not _arrives(body, target, limit.top_speed, limit, within_s)


def test_a_receiver_running_the_wrong_way_still_gets_there():
    # at 5 m/s away from the landing 6 m behind him: he stops (0.9 s, 2.3 m further), turns and
    # comes back; in 3 s even flat out he is late, in 4 s a slower pace does it
    limit = Limits(9.0, 5.5)
    body = Body(50.0, 34.0, 5.0, 0.0)
    assert pace_to_arrive(body, (44.0, 34.0), 3.0, limit) == limit.top_speed
    assert not _arrives(body, (44.0, 34.0), limit.top_speed, limit, 3.0)
    pace = pace_to_arrive(body, (44.0, 34.0), 4.0, limit)
    assert pace < limit.top_speed
    assert _arrives(body, (44.0, 34.0), pace, limit, 4.0)


def test_a_receiver_near_his_top_speed_gets_the_pace_he_needs():
    # 15 m from rest in 3.2 s takes 8.25 of his 9.0 m/s: the search reaches up to his top speed
    # (one capped at 0.8 of it, 7.2 m/s, would leave him late)
    limit = Limits(9.0, 5.5)
    body = Body(50.0, 34.0)
    pace = pace_to_arrive(body, (65.0, 34.0), 3.2, limit)
    assert pace == pytest.approx(8.2507, abs=1e-4)
    assert _arrives(body, (65.0, 34.0), pace, limit, 3.2)
    assert not _arrives(body, (65.0, 34.0), pace - 0.01, limit, 3.2)
    assert _arrives(body, (65.0, 34.0), 8.26, limit, 3.2)
    assert not _arrives(body, (65.0, 34.0), 7.2, limit, 3.2)


# --- time_to_reach: the counterpart of pace_to_arrive (M9 item 5) ------------------------------


@given(
    limits,
    st.floats(min_value=10.0, max_value=95.0),
    st.floats(min_value=10.0, max_value=58.0),
    st.tuples(st.floats(-5.0, 5.0), st.floats(-5.0, 5.0)),
    targets,
)
def test_time_to_reach_is_the_least_time_in_which_some_pace_gets_him_there(
    limit, x, y, moving, target
):
    body = Body(x, y, *moving)
    t = time_to_reach(body, target, limit)
    assert math.isfinite(t)  # no run on the pitch takes 30 s
    assert round(t / DT, 9) == int(round(t / DT, 9))  # on the 100 ms grid
    if t == 0.0:
        return
    assert _arrives(body, target, limit.top_speed, limit, t)
    assert _arrives(body, target, pace_to_arrive(body, target, t, limit), limit, t)
    # 100 ms less and no pace gets him there: flat out is the quickest
    assert not _arrives(body, target, limit.top_speed, limit, t - DT)
    assert pace_to_arrive(body, target, t - DT, limit) == limit.top_speed


def test_time_to_reach_looks_no_further_than_it_is_asked():
    # 15 m from rest at 9.0 m/s and 5.5 m/s²: 3.2 s, run-up and braking included (the receiver of
    # test_a_receiver_near_his_top_speed_gets_the_pace_he_needs needs 8.25 m/s in 3.2 s)
    limit = Limits(9.0, 5.5)
    body = Body(50.0, 34.0)
    assert time_to_reach(body, (65.0, 34.0), limit) == 3.2
    assert time_to_reach(body, (65.0, 34.0), limit, within_s=3.2) == 3.2
    assert time_to_reach(body, (65.0, 34.0), limit, within_s=3.1) == math.inf
    # from the far corner to the far corner is within the default 30 s, from rest
    assert time_to_reach(Body(0.5, 0.5), (104.5, 67.5), limit) < REACH_WITHIN_S


@pytest.mark.parametrize(("gap", "want"), [(0.0, 0.0), (0.0099, 0.0), (0.0101, 0.1)])
def test_a_player_on_his_target_needs_no_time(gap, want):
    # nearer than ARRIVED_M (0.01 m) he is there; just beyond it, one step brings him on it
    assert time_to_reach(Body(50.0, 34.0), (50.0 + gap, 34.0), Limits(9.0, 5.5)) == want


def test_a_target_beyond_an_edge_is_reached_on_the_band():
    limit = Limits(9.0, 5.5)
    beyond = time_to_reach(Body(100.0, 34.0), (105.0, 34.0), limit)
    assert beyond == time_to_reach(Body(100.0, 34.0), (104.5, 34.0), limit)


# --- the shortcut past stopping_speed (M9 item 6) -----------------------------------------------


@given(st.floats(0.0, 12.0), st.floats(0.5, 7.0), st.floats(0.0, 2000.0))
def test_beyond_the_braking_bound_he_always_stops_in_time(speed, acceleration, beyond):
    bound = braking_bound(speed, acceleration)
    assert braking_distance(speed, acceleration) < bound
    assert stopping_speed(bound + beyond, acceleration) >= speed


def test_the_braking_bound_meets_the_grid_where_it_is_tight():
    # at 1 m/s braking by 4 m/s² he covers 0.1 + 0.06 + 0.02 m: the bound's 0.125 + 0.05 +
    # 0.005 m meet it exactly (1 / 0.4 is 2.5, a half step), plus its micrometre
    assert braking_distance(1.0, 4.0) == pytest.approx(0.18, abs=1e-12)
    assert braking_bound(1.0, 4.0) == pytest.approx(0.180001, abs=1e-12)
    # a target 1 mm short of it is too near for 1 m/s: the step slows him
    slower = stopping_speed(0.179, 4.0)
    assert slower < 1.0
    nxt = step(Body(50.0, 34.0, 1.0, 0.0), (50.179, 34.0), 1.0, Limits(8.0, 4.0))
    assert nxt.vx == pytest.approx(slower, abs=1e-9)


moving_bodies = st.builds(
    Body,
    st.floats(min_value=0.0, max_value=PITCH_LENGTH),
    st.floats(min_value=0.0, max_value=PITCH_WIDTH),
    st.floats(min_value=-10.0, max_value=10.0),
    st.floats(min_value=-10.0, max_value=10.0),
)


@given(
    moving_bodies,
    targets,
    st.floats(min_value=0.0, max_value=12.0),
    limits,
    velocities,
    st.floats(min_value=0.25, max_value=1.0),
)
def test_the_braking_bound_never_changes_a_step(body, target, pace, limit, moving, share):
    fast = step(body, target, pace, limit, moving, share)
    with patch.object(movement, "braking_bound", lambda speed, acceleration: math.inf):
        always = step(body, target, pace, limit, moving, share)
    assert fast == always
