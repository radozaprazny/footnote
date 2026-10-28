import itertools
import math

import pytest
from hypothesis import given
from hypothesis import strategies as st
from lineups import CLUBS, PLAYERS, two_teams

from matchlens.events import PITCH_LENGTH, PITCH_WIDTH
from matchlens.formations import Slot, to_pitch
from matchlens.movement import EDGE_BAND, Body, Limits, pace_to_arrive, step
from matchlens.targets import (
    CAP_IN,
    CAP_OUT,
    COMFORT_BRAKING,
    DRIFT_M,
    DRIFT_PERIOD_S,
    FAR,
    FAR_FULL,
    FAR_PACE,
    GAP_IN,
    GAP_OUT,
    HALFWAY,
    JOG_CAP,
    KEEPER_DEPTH,
    LINE_DEEPEST,
    MARK_CLOSE,
    MARK_GAP,
    MARK_RADIUS,
    MARK_SWITCH,
    MARK_WEIGHT,
    MIDDLE,
    OFFSIDE_MARGIN,
    PACE_BASE,
    PACE_PER_M,
    PRESS_PACE,
    PRESS_TRIGGER,
    PRESSERS_APART,
    PULL,
    RUN_EVERY_S,
    RUN_FOR_S,
    WALK,
    WALK_WITHIN,
    WIDTH_FACTOR,
    Aim,
    Moment,
    Team,
    back_line,
    cover_point,
    drifted,
    goal_side,
    keeper_point,
    marking,
    nearest,
    offside_line,
    pace_to,
    pressing,
    run_point,
    shape_point,
    targets,
)

# --- the back line ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("attacking", "gaps", "caps"), [(False, GAP_OUT, CAP_OUT), (True, GAP_IN, CAP_IN)]
)
@pytest.mark.parametrize("height", [0.0, 1.0])
def test_the_back_line_follows_the_ball_between_its_floor_and_its_cap(
    attacking, gaps, caps, height
):
    gap, cap = gaps[int(height)], caps[int(height)]
    floor_ball = LINE_DEEPEST + gap  # the ball at which the line leaves its floor
    assert back_line(floor_ball, attacking, height) == pytest.approx(LINE_DEEPEST)
    assert back_line(floor_ball - 1, attacking, height) == pytest.approx(LINE_DEEPEST)
    assert back_line(floor_ball + 1, attacking, height) == pytest.approx(LINE_DEEPEST + 1)
    cap_ball = cap + gap
    assert back_line(cap_ball, attacking, height) == pytest.approx(cap)
    assert back_line(cap_ball - 1, attacking, height) == pytest.approx(cap - 1)
    assert back_line(cap_ball + 1, attacking, height) == pytest.approx(cap)


def test_a_high_line_stands_higher_than_a_deep_block():
    for ball_x in (20.0, 50.0, 80.0):
        assert back_line(ball_x, False, 1.0) >= back_line(ball_x, False, 0.0)


# --- the shape ----------------------------------------------------------------------------------


@pytest.mark.parametrize("phase", ["attack", "defend"])
@pytest.mark.parametrize("width", [0.0, 0.5, 1.0])
def test_a_slot_is_spread_by_the_width_and_leans_to_the_ball(phase, width):
    slot = Slot("FB", "L", (13.0, 13.0), (1.5, 17.5))
    dx, y = getattr(slot, phase)
    spread = WIDTH_FACTOR[0] + (WIDTH_FACTOR[1] - WIDTH_FACTOR[0]) * width
    x0, y0 = shape_point(slot, phase, 30.0, (50.0, MIDDLE), width)
    assert (x0, y0) == pytest.approx((30.0 + dx, MIDDLE + (y - MIDDLE) * spread))
    _, y1 = shape_point(slot, phase, 30.0, (50.0, MIDDLE + 10.0), width)
    assert y1 - y0 == pytest.approx(PULL[phase] * 10.0)


# --- the keeper ---------------------------------------------------------------------------------


def test_the_keeper_stands_between_the_ball_and_the_goal_centre():
    near, far = KEEPER_DEPTH
    # a ball straight ahead: the depth alone
    assert keeper_point((5.0, MIDDLE)) == pytest.approx((near, MIDDLE))
    assert keeper_point((10.0, MIDDLE)) == pytest.approx((near, MIDDLE))
    assert keeper_point((20.0, MIDDLE)) == pytest.approx((near + 3.0, MIDDLE))
    cap_ball = 10.0 + (far - near) / 0.30
    assert keeper_point((cap_ball, MIDDLE)) == pytest.approx((far, MIDDLE))
    assert keeper_point((cap_ball + 20.0, MIDDLE)) == pytest.approx((far, MIDDLE))
    # a wide ball: on the line to it, so outside the posts when deep enough
    x, y = keeper_point((60.0, 4.0))
    assert y < MIDDLE - 3.66
    assert math.hypot(x, y - MIDDLE) == pytest.approx(min(far, near + 0.30 * 50.0))
    # a ball nearer than his depth: he goes to it
    assert keeper_point((1.0, MIDDLE + 1.0)) == (1.0, MIDDLE + 1.0)


# --- offside, pressing, marking, pace -----------------------------------------------------------


def test_the_offside_line_is_the_second_last_opponent_the_ball_or_halfway():
    opponents = [(100.0, 34.0), (80.0, 30.0), (70.0, 20.0)]
    assert offside_line((60.0, 34.0), opponents) == 80.0
    assert offside_line((85.0, 34.0), opponents) == 85.0
    deep = [(100.0, 34.0), (40.0, 30.0)]
    assert offside_line((30.0, 34.0), deep) == PITCH_LENGTH / 2


def test_pressing_sends_two_from_a_press_of_one_half_and_only_within_the_trigger():
    ids = list(two_teams()[0].slots)
    carrier = (50.0, 34.0)
    at = {pid: (50.0 + 2.0 * (i + 1), 34.0) for i, pid in enumerate(ids)}
    assert pressing(carrier, at, 0.5) == ids[:2]
    assert pressing(carrier, at, 0.49) == ids[:1]
    trigger = PRESS_TRIGGER[0] + (PRESS_TRIGGER[1] - PRESS_TRIGGER[0]) * 0.2
    edge = {ids[0]: (50.0 + trigger, 34.0), ids[1]: (50.0 + trigger + 0.01, 34.0)}
    assert pressing(carrier, edge, 0.2) == [ids[0]]
    assert pressing(carrier, {ids[1]: edge[ids[1]]}, 0.2) == []


def test_goal_side_steps_towards_the_own_goal_centre():
    assert goal_side((20.0, MIDDLE), 2.0) == pytest.approx((18.0, MIDDLE))
    x, y = goal_side((30.0, MIDDLE + 40.0), 5.0)
    assert math.hypot(30.0 - x, MIDDLE + 40.0 - y) == pytest.approx(5.0)
    assert goal_side((1.0, MIDDLE), 2.0) == (0.0, MIDDLE)


@pytest.mark.parametrize("work", [0.0, 1.0])
def test_the_pace_grows_with_the_distance_to_a_cap(work):
    here = (50.0, 34.0)
    cap = JOG_CAP[int(work)]

    def at(d):
        return pace_to(here, (50.0 + d, 34.0), work)

    assert at(WALK_WITHIN - 0.01) == WALK
    assert at(WALK_WITHIN) == pytest.approx(PACE_BASE + PACE_PER_M * WALK_WITHIN)
    assert at(5.0) == pytest.approx(min(cap, PACE_BASE + PACE_PER_M * 5.0))
    assert at(FAR) == pytest.approx(cap)
    far = FAR_PACE[int(work)]
    # from FAR a ramp, continuous, to a hard run at FAR_FULL
    assert at(FAR + 0.01) == pytest.approx(cap, abs=0.01)
    assert at((FAR + FAR_FULL) / 2) == pytest.approx((cap + far) / 2)
    assert at(FAR_FULL) == pytest.approx(far)
    assert at(FAR_FULL + 10.0) == pytest.approx(far)


def test_the_drift_is_bounded_smooth_and_the_seeds_own():
    low = DRIFT_PERIOD_S[0]
    a = [drifted((50.0, 34.0), "cor-p05", s / 10, 7) for s in range(0, 3000)]
    assert all(abs(x - 50.0) <= DRIFT_M + 1e-9 and abs(y - 34.0) <= DRIFT_M + 1e-9 for x, y in a)
    most = 2 * math.pi * DRIFT_M / low * 0.1 + 1e-9  # the steepest change of a sine in 0.1 s
    assert all(math.dist(p, q) <= most * math.sqrt(2) for p, q in itertools.pairwise(a))
    assert drifted((50.0, 34.0), "cor-p05", 12.3, 7) == a[123]
    assert drifted((50.0, 34.0), "cor-p05", 12.3, 8) != a[123]


# --- the whole moment ---------------------------------------------------------------------------

points = st.tuples(
    st.floats(min_value=0.0, max_value=PITCH_LENGTH),
    st.floats(min_value=0.0, max_value=PITCH_WIDTH),
)


def mirror(p):
    return (PITCH_LENGTH - p[0], PITCH_WIDTH - p[1])


@st.composite
def moments(draw):
    teams = two_teams(*draw(st.sampled_from([("cor", "qrd"), ("vel", "slt"), ("slt", "cor")])))
    everyone = [pid for t in teams for pid in (*t.slots, t.keeper)]
    at = {pid: draw(points) for pid in everyone}
    velocity = {pid: (draw(st.floats(-8, 8)), draw(st.floats(-8, 8))) for pid in everyone}
    side = draw(st.sampled_from([None, 0, 1]))
    possession = None if side is None else teams[side].club.id
    carrier = receiver = None
    if side is not None:
        role = draw(st.sampled_from(["carrier", "receiver", None]))
        mate = draw(st.sampled_from(sorted((*teams[side].slots, teams[side].keeper))))
        carrier, receiver = (mate, None) if role == "carrier" else (None, mate if role else None)
    # whom each marked at the previous call: anyone, a teammate or a keeper too (they are ignored)
    marks = draw(st.dictionaries(st.sampled_from(everyone), st.sampled_from(everyone), max_size=8))
    moment = Moment(
        ball=at[carrier] if carrier else draw(points),
        possession=possession,
        half_s=draw(st.floats(0, 3000)),
        carrier=carrier,
        carry_to=draw(points) if carrier else None,
        carry_pace=draw(st.floats(0, 7)),
        receiver=receiver,
        landing=draw(points) if receiver else None,
        lands_in_s=draw(st.floats(0.1, 3.0)),
        period=draw(st.sampled_from([1, 2])),
    )
    return moment, teams, at, velocity, draw(st.integers(0, 2**31)), marks


@given(moments())
def test_every_target_lies_inside_the_band_at_a_pace_he_can_run(case):
    moment, teams, at, velocity, seed, marks = case
    out = targets(moment, teams, at, velocity, PLAYERS, seed, marks)
    assert set(out) == set(at)
    opponents = {pid: set(o.slots) for t, o in (teams, teams[::-1]) for pid in (*t.slots, t.keeper)}
    for pid, aim in out.items():
        assert aim.mark is None or aim.mark in opponents[pid]  # an outfield opponent, or nobody
        x, y = aim.point
        assert EDGE_BAND <= x <= PITCH_LENGTH - EDGE_BAND
        assert EDGE_BAND <= y <= PITCH_WIDTH - EDGE_BAND
        assert 0.0 <= aim.pace <= PLAYERS[pid].top_speed
        assert all(math.isfinite(v) for v in aim.velocity)
        assert aim.braking in (COMFORT_BRAKING, 1.0)
    if moment.receiver is not None:  # his pace gets him there in time, from where and how he runs
        p = PLAYERS[moment.receiver]
        body = Body(*at[moment.receiver], *velocity[moment.receiver])
        want = pace_to_arrive(
            body, moment.landing, moment.lands_in_s, Limits(p.top_speed, p.acceleration)
        )
        assert out[moment.receiver].pace == want


@given(moments())
def test_a_moment_turned_half_round_turns_every_target(case):
    moment, teams, at, velocity, seed, marks = case
    turned_teams = tuple(Team(t.club, t.slots, t.keeper, not t.attacks_right) for t in teams)
    turned = Moment(
        mirror(moment.ball),
        moment.possession,
        moment.half_s,
        moment.carrier,
        mirror(moment.carry_to) if moment.carry_to else None,
        moment.carry_pace,
        moment.receiver,
        mirror(moment.landing) if moment.landing else None,
        moment.lands_in_s,
        moment.period,
    )
    a = targets(moment, teams, at, velocity, PLAYERS, seed, marks)
    b = targets(
        turned,
        turned_teams,
        {p: mirror(q) for p, q in at.items()},
        {p: (-v[0], -v[1]) for p, v in velocity.items()},
        PLAYERS,
        seed,
        marks,
    )
    for pid, aim in a.items():
        assert b[pid].mark == aim.mark
        assert b[pid].point == pytest.approx(mirror(aim.point), abs=1e-9)
        # a receiver's pace comes from stepping (a bisection), equal to its last round, 9/4096
        assert b[pid].pace == pytest.approx(aim.pace, abs=0.003)
        assert b[pid].velocity == pytest.approx((-aim.velocity[0], -aim.velocity[1]), abs=1e-9)
        assert b[pid].braking == aim.braking


def test_the_carrier_and_the_receiver_go_where_the_play_sends_them():
    teams = two_teams()
    home, away = teams
    everyone = [pid for t in teams for pid in (*t.slots, t.keeper)]
    at = {pid: (52.5, 34.0) for pid in everyone}
    carrier, receiver = list(home.slots)[5], list(home.slots)[8]
    at[receiver] = (60.0, 20.0)
    out = targets(
        Moment((52.5, 34.0), home.club.id, carrier=carrier, carry_to=(58.0, 30.0), carry_pace=4.0),
        teams,
        at,
        {},
        PLAYERS,
        1,
    )
    assert out[carrier] == Aim((58.0, 30.0), 4.0, (0.0, 0.0), 1.0)
    out = targets(
        Moment((52.5, 34.0), home.club.id, receiver=receiver, landing=(70.0, 20.0), lands_in_s=2.0),
        teams,
        at,
        {},
        PLAYERS,
        1,
    )
    assert out[receiver].point == (70.0, 20.0)
    # the pace that gets him there by the landing, run-up and braking included
    p = PLAYERS[receiver]
    body = Body(60.0, 20.0)
    for _ in range(20):
        body = step(body, (70.0, 20.0), out[receiver].pace, Limits(p.top_speed, p.acceleration))
    assert math.dist((body.x, body.y), (70.0, 20.0)) < 0.01 or out[receiver].pace == p.top_speed
    assert out[receiver].braking == 1.0


def _band(point):
    return (
        min(PITCH_LENGTH - EDGE_BAND, max(EDGE_BAND, point[0])),
        min(PITCH_WIDTH - EDGE_BAND, max(EDGE_BAND, point[1])),
    )


@given(moments())
def test_attackers_off_the_ball_aim_onside(case):
    # in possession, everyone but the carrier and the receiver aims no further than the offside
    # line (second-last opponent, the ball, halfway) less the margin, runs and drift included
    moment, teams, at, velocity, seed, marks = case
    out = targets(moment, teams, at, velocity, PLAYERS, seed, marks)
    for team, other in (teams, teams[::-1]):
        if moment.possession != team.club.id:
            continue
        frame = team.attacks_right
        ball = to_pitch(*moment.ball, frame)
        line = offside_line(ball, [to_pitch(*at[o], frame) for o in (*other.slots, other.keeper)])
        for pid in team.slots:
            if pid in (moment.carrier, moment.receiver):
                continue
            x = to_pitch(*out[pid].point, frame)[0]
            assert x <= line - OFFSIDE_MARGIN + 1e-9, (pid, x, line)


@given(moments())
def test_the_keeper_aims_on_the_line_from_his_goal_to_the_ball(case):
    moment, teams, at, velocity, seed, marks = case
    out = targets(moment, teams, at, velocity, PLAYERS, seed, marks)
    for team in teams:
        if team.keeper in (moment.carrier, moment.receiver):
            continue
        frame = team.attacks_right
        ball = to_pitch(*moment.ball, frame)
        attacking = moment.possession == team.club.id
        line = back_line(ball[0], attacking, team.club.tactics.line_height)
        spot = keeper_point(ball, line if ball[0] < HALFWAY else None)
        assert out[team.keeper].point == pytest.approx(to_pitch(*_band(spot), frame), abs=1e-9)


def test_the_constants_are_the_plans():
    # PROGRESS, M9 item 3 part 2, after its review
    assert JOG_CAP == (2.6, 3.8)
    assert (FAR, FAR_FULL, FAR_PACE) == (25.0, 40.0, (5.0, 6.5))
    assert PRESS_PACE == (4.0, 7.0)
    assert (MARK_RADIUS, MARK_CLOSE, MARK_GAP, MARK_WEIGHT) == (12.0, 6.0, 2.0, 0.6)
    assert MARK_SWITCH == 3.0
    assert (RUN_EVERY_S, RUN_FOR_S) == (8.0, 4.0)
    assert COMFORT_BRAKING == 0.6
    assert (OFFSIDE_MARGIN, PRESSERS_APART) == (0.5, 2.0)


def _far_away(team, frame_right):
    """Everyone of `team` near his own goal, out of every rule's reach."""
    return {pid: to_pitch(3.0, 10.0 + 4.0 * i, frame_right) for i, pid in enumerate(team.slots)}


@pytest.mark.parametrize(
    ("distance", "marked"), [(MARK_RADIUS - 0.01, True), (MARK_RADIUS + 0.01, False)]
)
def test_a_defender_marks_an_opponent_within_the_radius_of_his_slot(distance, marked):
    # the ball loose on halfway, so the back line stands where it rests and every share agrees
    home, away = two_teams()
    defender, slot = next(iter(sorted(home.slots.items())))
    width = home.club.tactics.width
    ball = (HALFWAY, MIDDLE)
    rest = back_line(HALFWAY, False, home.club.tactics.line_height)
    spot = shape_point(slot, "defend", rest, ball, width)
    opponent = sorted(away.slots)[0]
    at = {pid: (52.0, 34.0) for pid in (*home.slots, home.keeper)}
    at |= {pid: to_pitch(*q, True) for pid, q in _far_away(away, False).items()}
    at[away.keeper] = (100.0, 34.0)
    at[opponent] = (spot[0] + distance, spot[1])  # home attacks right: its frame is the pitch's
    aim = targets(Moment(ball, None, half_s=10.0), (home, away), at, {}, PLAYERS, 3)[defender]
    if marked:
        guard = goal_side(at[opponent], MARK_GAP)
        mixed = tuple(
            MARK_WEIGHT * g + (1 - MARK_WEIGHT) * s for g, s in zip(guard, spot, strict=True)
        )
        want = drifted(mixed, defender, 10.0, 3)
    else:
        want = drifted(spot, defender, 10.0, 3)
    assert aim.point == pytest.approx(_band(want), abs=1e-9)


@pytest.mark.parametrize(("gap", "runs_with_him"), [(MARK_CLOSE, True), (MARK_CLOSE + 0.01, False)])
def test_a_marker_runs_with_his_man_only_when_close(gap, runs_with_him):
    home, away = two_teams()
    defender, slot = next(iter(sorted(home.slots.items())))
    ball = (HALFWAY, MIDDLE)
    rest = back_line(HALFWAY, False, home.club.tactics.line_height)
    spot = shape_point(slot, "defend", rest, ball, home.club.tactics.width)
    opponent = sorted(away.slots)[0]
    at = {pid: (52.0, 34.0) for pid in (*home.slots, home.keeper)}
    at |= {pid: to_pitch(*q, True) for pid, q in _far_away(away, False).items()}
    at[away.keeper] = (100.0, 34.0)
    at[opponent] = (spot[0] + 5.0, spot[1])
    at[defender] = (spot[0] + 5.0 - gap, spot[1])
    velocity = {opponent: (3.0, -2.0)}
    aim = targets(Moment(ball, None), (home, away), at, velocity, PLAYERS, 3)[defender]
    want = (MARK_WEIGHT * 3.0, MARK_WEIGHT * -2.0) if runs_with_him else (0.0, 0.0)
    assert aim.velocity == pytest.approx(want)


def test_two_pressers_take_two_points_the_second_covering():
    # Corrowmere presses with two (0.85); a qrd carrier on the ball close to two of them
    home, away = two_teams("cor", "qrd")
    carrier = sorted(away.slots)[0]
    at = {pid: (20.0, 10.0 + 3.0 * i) for i, pid in enumerate((*home.slots, home.keeper))}
    at |= {pid: (80.0, 10.0 + 4.0 * i) for i, pid in enumerate((*away.slots, away.keeper))}
    first, second = sorted(home.slots)[:2]
    at[carrier], at[first], at[second] = (40.0, 30.0), (44.0, 30.0), (45.0, 33.0)
    cv = (-2.0, 1.0)
    moment = Moment(
        at[carrier], away.club.id, carrier=carrier, carry_to=(35.0, 32.0), carry_pace=4.0
    )
    out = targets(moment, (home, away), at, {carrier: cv}, PLAYERS, 3)
    lead = (40.0 - 2.0 * 0.3, 30.0 + 1.0 * 0.3)
    pace = PRESS_PACE[0] + (PRESS_PACE[1] - PRESS_PACE[0]) * home.club.tactics.press
    assert out[first] == Aim(
        pytest.approx(goal_side(lead, MARK_GAP / 2)), pytest.approx(pace), cv, 1.0
    )
    assert out[second].point == pytest.approx(cover_point(lead))
    assert math.dist(out[first].point, out[second].point) > 3.0
    assert out[second].velocity == cv and out[second].braking == 1.0


def test_a_keeper_can_carry_receive_and_be_pressed():
    home, away = two_teams("cor", "qrd")
    at = {pid: (30.0, 10.0 + 3.0 * i) for i, pid in enumerate((*home.slots, home.keeper))}
    at |= {pid: (80.0, 10.0 + 4.0 * i) for i, pid in enumerate((*away.slots, away.keeper))}
    at[away.keeper] = (95.0, 34.0)
    near = sorted(home.slots)[0]
    at[near] = (90.0, 34.0)  # within Corrowmere's trigger of the keeper
    moment = Moment(at[away.keeper], away.club.id, carrier=away.keeper, carry_to=(96.0, 30.0))
    out = targets(moment, (home, away), at, {}, PLAYERS, 3)
    assert out[away.keeper].point == (96.0, 30.0)
    assert out[near].braking == 1.0  # pressing him
    moment = Moment(
        (80.0, 34.0), away.club.id, receiver=away.keeper, landing=(97.0, 36.0), lands_in_s=2.0
    )
    assert targets(moment, (home, away), at, {}, PLAYERS, 3)[away.keeper].point == (97.0, 36.0)


@pytest.mark.parametrize("club", ["cor", "vel", "qrd", "slt"])
def test_with_the_ball_in_his_half_the_keeper_stays_behind_his_back_line(club):
    line_height = CLUBS[club].tactics.line_height
    for ball_x in (15.0, 25.0, 31.4, 40.0, 52.0):
        for ball_y in (10.0, 34.0, 60.0):
            line = back_line(ball_x, False, line_height)
            x, _ = keeper_point((ball_x, ball_y), line)
            assert x <= line - 1.5 + 1e-9


def _a_running_moment(role):
    """A seed, player and time at which a player of `role` makes a run (searched, deterministic)."""
    home, _ = two_teams("slt" if role == "ST" else "cor", "qrd")
    for pid, slot in sorted(home.slots.items()):
        if slot.role != role:
            continue
        for tenth in range(0, 2000):
            half_s = tenth / 10
            if run_point(pid, slot, (60.0, 20.0), (70.0, 15.0), 80.0, 1.0, half_s, 3) is not None:
                return pid, slot, half_s
    raise AssertionError(f"no run for {role}")


def test_runs_start_only_past_halfway_last_their_window_share_and_stay_onside():
    pid, slot, half_s = _a_running_moment("FB")
    point, offside = (60.0, 20.0), 80.0

    def run(ball, at_s=half_s):
        return run_point(pid, slot, point, ball, offside, 1.0, at_s, 3)

    assert run((HALFWAY, 15.0)) is not None
    assert run((math.nextafter(HALFWAY, 0.0), 15.0)) is None  # in his own half: no run
    assert run((70.0, 50.0)) is None  # the ball on the other side: a full-back stays
    x, y = run((70.0, 15.0))
    assert x == min(70.0 + 8.0, offside - OFFSIDE_MARGIN) and y == 20.0 - 4.0
    # a run lasts the first RUN_FOR_S of his window and no longer
    assert (
        sum(run((70.0, 15.0), half_s + k / 10) is not None for k in range(-80, 80))
        <= RUN_FOR_S * 10 + 1
    )


@pytest.mark.parametrize("role", ["W", "ST"])
def test_a_winger_comes_inside_and_a_striker_waits_on_the_line(role):
    pid, slot, half_s = _a_running_moment(role)
    x, y = run_point(pid, slot, (60.0, 20.0), (70.0, 15.0), 80.0, 1.0, half_s, 3)
    if role == "W":
        assert (x, y) == (64.0, MIDDLE + (20.0 - MIDDLE) * 0.5)
    else:
        assert (x, y) == (80.0 - OFFSIDE_MARGIN, 20.0)


@pytest.mark.parametrize(
    ("role", "slot_x", "ball_x", "x"),
    [
        # a full-back overlaps 8 m beyond the ball, a winger cuts in 4 m beyond his slot: short
        # of, on and past the point where the offside line (80) less the margin takes over
        ("FB", 60.0, 71.4, 79.4),
        ("FB", 60.0, 71.5, 79.5),
        ("FB", 60.0, 71.6, 79.5),
        ("W", 75.4, 70.0, 79.4),
        ("W", 75.5, 70.0, 79.5),
        ("W", 75.6, 70.0, 79.5),
    ],
)
def test_a_run_stops_half_a_metre_short_of_the_offside_line(role, slot_x, ball_x, x):
    pid, slot, half_s = _a_running_moment(role)
    run = run_point(pid, slot, (slot_x, 20.0), (ball_x, 15.0), 80.0, 1.0, half_s, 3)
    assert run[0] == pytest.approx(x, abs=1e-9)


def test_a_slot_past_the_offside_line_is_held_half_a_metre_short_of_it():
    # Corrowmere attacking right with the ball on 50 m (no runs in their own half) and every
    # opponent behind halfway, so the line is halfway: the front three's slots lie past it,
    # drift or not, and they aim exactly the margin short of it; the rest stand short anyway
    home, away = two_teams("cor", "qrd")
    carrier = sorted(p for p, s in home.slots.items() if s.role == "CB")[0]
    at = {pid: (40.0 + i, 4.0 + 5.0 * i) for i, pid in enumerate((*home.slots, home.keeper))}
    at |= {pid: (40.0, 4.0 + 5.0 * i) for i, pid in enumerate((*away.slots, away.keeper))}
    for seed, half_s in itertools.product(range(4), (0.0, 600.0, 1800.0, 2700.0)):
        moment = Moment((50.0, 34.0), home.club.id, half_s, carrier, carry_to=(50.0, 34.0))
        out = targets(moment, (home, away), at, {}, PLAYERS, seed)
        front = [p for p, s in home.slots.items() if s.role in ("W", "ST")]
        assert len(front) == 3
        assert {out[p].point[0] for p in front} == {HALFWAY - OFFSIDE_MARGIN}, (seed, half_s)
        rest = [p for p in home.slots if p not in front and p != carrier]
        assert max(out[p].point[0] for p in rest) < HALFWAY - OFFSIDE_MARGIN, (seed, half_s)


def test_two_pressers_never_take_one_point_anywhere_on_the_pitch():
    # every place of a qrd carrier, the goal mouth of Corrowmere (two pressers) included: two
    # cor players 2 m off him press; their points stay at least PRESSERS_APART apart
    home, away = two_teams("cor", "qrd")
    carrier = sorted(away.slots)[0]
    first, second = sorted(home.slots)[:2]
    base = {pid: (100.0, 4.0 + 3.0 * i) for i, pid in enumerate((*home.slots, home.keeper))}
    base |= {pid: (60.0, 4.0 + 3.0 * i) for i, pid in enumerate((*away.slots, away.keeper))}
    for x in [0.0, 0.5, 1.0, 3.0, *range(5, 106, 10)]:
        for y in [0.0, 20.0, 33.0, 34.0, 35.0, 50.0, 68.0]:
            at = base | {carrier: (x, y), first: (x + 2.0, y), second: (x, min(68.0, y + 2.0))}
            moment = Moment((x, y), away.club.id, carrier=carrier, carry_to=(x, y), carry_pace=0.0)
            out = targets(moment, (home, away), at, {}, PLAYERS, 3)
            pressers = [p for p in (first, second) if out[p].braking == 1.0]
            assert len(pressers) == 2, (x, y)
            assert math.dist(out[first].point, out[second].point) >= PRESSERS_APART - 1e-9, (x, y)


# --- a marker keeps his man (M9 item 5) ---------------------------------------------------------


@pytest.mark.parametrize(("other_x", "kept"), [(2.0, False), (2.01, True)])
def test_a_marker_keeps_his_man_until_another_is_3_m_nearer(other_x, kept):
    # his man 5 m from the slot: one 3 m nearer (at 2 m) takes over, 2.99 m nearer does not
    others = {"a": (5.0, 0.0), "b": (other_x, 0.0)}
    assert marking((0.0, 0.0), others, "a") == ("a" if kept else "b")


@pytest.mark.parametrize(("man_x", "kept"), [(12.0, True), (12.01, False)])
def test_a_marker_lets_his_man_go_beyond_the_radius(man_x, kept):
    # the other is only 0.5 m nearer: the man is kept while within MARK_RADIUS, else dropped
    others = {"a": (man_x, 0.0), "b": (0.0, 11.5)}
    assert marking((0.0, 0.0), others, "a") == ("a" if kept else "b")


@pytest.mark.parametrize("kept", [None, "gone"])
def test_without_a_man_he_marks_the_nearest_within_the_radius(kept):
    # no man before, or one who is no longer an opponent near (`gone`): the nearest, if any
    assert marking((0.0, 0.0), {"a": (5.0, 0.0), "b": (4.0, 0.0)}, kept) == "b"
    assert marking((0.0, 0.0), {"c": (12.01, 0.0)}, kept) is None


@pytest.mark.parametrize(("other_gap", "kept"), [(2.5, True), (3.1, False)])
def test_targets_pass_the_marks_on_and_keep_a_man(other_gap, kept):
    # two opponents near a defender's slot: his man 5 m off it, the other nearer by 2.5 m (kept)
    # or by 3.1 m (switched); without marks he takes the nearer at once
    home, away = two_teams()
    defender, slot = next(iter(sorted(home.slots.items())))
    ball = (HALFWAY, MIDDLE)
    rest = back_line(HALFWAY, False, home.club.tactics.line_height)
    spot = shape_point(slot, "defend", rest, ball, home.club.tactics.width)
    man, other = sorted(away.slots)[:2]
    at = {pid: (52.0, 34.0) for pid in (*home.slots, home.keeper)}
    at |= {pid: to_pitch(*q, True) for pid, q in _far_away(away, False).items()}
    at[away.keeper] = (100.0, 34.0)
    at[man] = (spot[0] + 5.0, spot[1])
    at[other] = (spot[0], spot[1] + 5.0 - other_gap)
    moment = Moment(ball, None, half_s=10.0)
    fresh = targets(moment, (home, away), at, {}, PLAYERS, 3)[defender]
    assert fresh.mark == other
    held = targets(moment, (home, away), at, {}, PLAYERS, 3, {defender: man})[defender]
    assert held.mark == (man if kept else other)


@given(
    points,
    st.dictionaries(st.sampled_from("abcde"), points, max_size=5),
    st.sampled_from([None, "a", "b", "c", "d", "e", "z"]),
)
def test_a_marker_keeps_his_man_or_takes_the_nearest_within_the_radius(point, others, kept):
    got = marking(point, others, kept)
    best = nearest(point, others, MARK_RADIUS)
    d = {o: math.dist(q, point) for o, q in others.items()}
    if got is None:
        assert best is None  # nobody within the radius
        return
    assert d[got] <= MARK_RADIUS
    if got != best:  # he keeps his man: no other is MARK_SWITCH nearer
        assert got == kept and d[best] > d[kept] - MARK_SWITCH
    elif kept in d and d[kept] <= MARK_RADIUS and got != kept:  # he switched: one is that nearer
        assert d[got] <= d[kept] - MARK_SWITCH
