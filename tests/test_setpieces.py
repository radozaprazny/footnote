import itertools
import math
from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st
from lineups import CLUBS, PLAYERS, two_teams

from matchlens.events import PITCH_LENGTH, PITCH_WIDTH, Restart
from matchlens.formations import to_pitch
from matchlens.match import (
    GOAL_AREA_HALF_WIDTH,
    GOAL_AREA_LENGTH,
    PENALTY_AREA_HALF_WIDTH,
    PENALTY_AREA_LENGTH,
    PENALTY_SPOT,
)
from matchlens.movement import EDGE_BAND
from matchlens.setpieces import (
    CIRCLE,
    CORNER_ARC,
    MARGIN,
    PLAYER_GAP,
    PRESS_LINE,
    SHOOTING_RANGE,
    TEAMMATE_GAP,
    THROW_DISTANCE,
    WALL_DISTANCE,
    WALL_OF_FOUR,
    WALL_OF_THREE,
    breaches,
    layout,
)
from matchlens.targets import COMFORT_BRAKING, HALFWAY, MIDDLE, WALK, pace_to

# every ordered pair of clubs, the side taking the restart first, attacking either way
PAIRS = [(h, a, right) for h, a in itertools.permutations(CLUBS, 2) for right in (True, False)]
PENALTY_MARK = (PITCH_LENGTH - PENALTY_SPOT, MIDDLE)  # in the shooting side's frame
EPS = 1e-9


def everyone(team):
    return (*team.slots, team.keeper)


def grid(teams):
    """Where everyone is before the restart: anywhere, here a spread over the pitch."""
    pids = [p for t in teams for p in everyone(t)]
    return {p: (5.0 + 4.5 * i, 3.0 + (2.9 * i) % 62.0) for i, p in enumerate(pids)}


def case(pair, kind, spot, taker=None, at=None):
    """A restart of `kind` at `spot`, given in the taking side's frame, by `taker` (by default
    its last outfield player by id); every aim's point in its own side's frame."""
    home, away, right = pair
    taking, other = two_teams(home, away, right)
    taker = taker(taking) if callable(taker) else taker or sorted(taking.slots)[-1]
    aims = layout(
        kind, to_pitch(*spot, right), taker, taking, other, at or grid((taking, other)), PLAYERS
    )
    frame = {pid: t.attacks_right for t in (taking, other) for pid in everyone(t)}
    mine = {pid: to_pitch(*aim.point, frame[pid]) for pid, aim in aims.items()}
    return taking, other, taker, mine, aims


def theirs(spot):
    """A point of the taking side's frame in the other side's frame."""
    return (PITCH_LENGTH - spot[0], PITCH_WIDTH - spot[1])


def in_area_ahead(p):  # the penalty area a side attacks, in its own frame; its lines included
    return (
        p[0] >= PITCH_LENGTH - PENALTY_AREA_LENGTH and abs(p[1] - MIDDLE) <= PENALTY_AREA_HALF_WIDTH
    )


def in_own_area(p):
    return p[0] <= PENALTY_AREA_LENGTH and abs(p[1] - MIDDLE) <= PENALTY_AREA_HALF_WIDTH


def clear_of_area_ahead(p):  # outside it by the margin
    return (
        p[0] <= PITCH_LENGTH - PENALTY_AREA_LENGTH - MARGIN
        or abs(p[1] - MIDDLE) >= PENALTY_AREA_HALF_WIDTH + MARGIN
    )


def assert_apart(aims):
    # no two players share a point: PLAYER_GAP between any two (a wall stands 0.6 m apart)
    for (a, p), (b, q) in itertools.combinations(sorted(aims.items()), 2):
        assert math.dist(p.point, q.point) >= PLAYER_GAP - EPS, (a, b, p.point, q.point)


def assert_room_for_the_taker(taking, taker, mine, spot):
    for pid in everyone(taking):
        if pid != taker:
            assert math.dist(mine[pid], spot) >= TEAMMATE_GAP + MARGIN - EPS, (pid, mine[pid])


def aims_at(aims):
    return {p: a.point for p, a in aims.items()}


def any_taker(data):
    return lambda team: data.draw(st.sampled_from(sorted(everyone(team))))


SPOTS = {
    Restart.KICK_OFF: (HALFWAY, MIDDLE),
    Restart.GOAL_KICK: (5.5, 30.0),
    Restart.CORNER: (105.0, 0.0),
    Restart.FREE_KICK: (85.0, 30.0),
    Restart.THROW_IN: (60.0, 0.0),
    Restart.PENALTY: PENALTY_MARK,
}


# --- every restart -------------------------------------------------------------------------------


@pytest.mark.parametrize("pair", PAIRS)
@pytest.mark.parametrize("kind", list(Restart))
def test_every_player_gets_an_aim_inside_the_band_at_a_pace_he_can_run(pair, kind):
    taking, other, taker, _, aims = case(pair, kind, SPOTS[kind])
    assert set(aims) == set(everyone(taking)) | set(everyone(other))
    for pid, aim in aims.items():
        assert EDGE_BAND <= aim.point[0] <= PITCH_LENGTH - EDGE_BAND, pid
        assert EDGE_BAND <= aim.point[1] <= PITCH_WIDTH - EDGE_BAND, pid
        assert 0.0 < aim.pace <= PLAYERS[pid].top_speed, pid
        assert aim.velocity == (0.0, 0.0) and aim.braking == COMFORT_BRAKING
    assert_apart(aims)
    # everyone on his point keeps the Laws: the restart can be played once they are there
    spot = to_pitch(*SPOTS[kind], pair[2])
    assert breaches(kind, spot, taker, taking, other, {p: a.point for p, a in aims.items()}) == []


@pytest.mark.parametrize(
    ("kind", "spot", "near"),
    [
        (Restart.KICK_OFF, (HALFWAY, MIDDLE), (HALFWAY, MIDDLE)),
        (Restart.CORNER, (105.0, 0.0), (105.0 - EDGE_BAND, EDGE_BAND)),
        (Restart.CORNER, (105.0, 68.0), (105.0 - EDGE_BAND, 68.0 - EDGE_BAND)),
        (Restart.THROW_IN, (60.0, 0.0), (60.0, EDGE_BAND)),
        (Restart.THROW_IN, (0.0, 68.0), (EDGE_BAND, 68.0 - EDGE_BAND)),
        (Restart.GOAL_KICK, (5.5, 30.0), (5.5, 30.0)),
        (Restart.PENALTY, PENALTY_MARK, PENALTY_MARK),
    ],
)
@pytest.mark.parametrize("right", [True, False])
def test_the_taker_goes_to_the_spot_as_near_as_the_band_allows(kind, spot, near, right):
    taking, _, taker, mine, _ = case(("cor", "qrd", right), kind, spot)
    assert mine[taker] == pytest.approx(near, abs=EPS)


def test_the_pace_is_a_walk_on_the_point_and_a_run_from_far():
    pair = ("cor", "qrd", True)
    taking, other, taker, _, first = case(pair, Restart.THROW_IN, (60.0, 0.0))
    # everyone where he is going: a walk; everyone 50 m off it: his pace for 50 m, a run
    on_it = {pid: aim.point for pid, aim in first.items()}
    _, _, _, _, aims = case(pair, Restart.THROW_IN, (60.0, 0.0), taker, on_it)
    assert {aim.pace for aim in aims.values()} == {WALK}
    far = {pid: (p[0] + 50.0 if p[0] < HALFWAY else p[0] - 50.0, p[1]) for pid, p in on_it.items()}
    _, _, _, _, aims = case(pair, Restart.THROW_IN, (60.0, 0.0), taker, far)
    for pid, aim in aims.items():
        assert aim.pace == pace_to(far[pid], aim.point, PLAYERS[pid].work_rate) > WALK


def test_the_constants_are_the_laws():
    # Law 1's pitch markings and the distances of Laws 8, 13, 15 and 17, written out
    assert (CIRCLE, CORNER_ARC, THROW_DISTANCE, MARGIN) == (9.15, 1.0, 2.0, 0.5)
    assert (TEAMMATE_GAP, PLAYER_GAP, WALL_DISTANCE) == (3.0, 0.5, 1.0)
    assert (PENALTY_AREA_LENGTH, PENALTY_AREA_HALF_WIDTH, PENALTY_SPOT) == (16.5, 20.16, 11.0)
    assert (GOAL_AREA_LENGTH, GOAL_AREA_HALF_WIDTH) == (5.5, 9.16)


def test_no_pace_is_above_the_players_top_speed():
    # a far walk back would be a run of up to 6.5 m/s; a player slower than that runs his best
    slow = {pid: replace(p, top_speed=1.5) for pid, p in PLAYERS.items()}
    taking, other = two_teams("cor", "qrd")
    far = {pid: (0.0, 0.0) for t in (taking, other) for pid in everyone(t)}
    aims = layout(
        Restart.KICK_OFF, (HALFWAY, MIDDLE), sorted(taking.slots)[0], taking, other, far, slow
    )
    assert max(aim.pace for aim in aims.values()) == 1.5


def test_a_wrong_taker_a_spot_off_its_place_or_a_free_kick_in_the_defending_area_is_refused():
    taking, other = two_teams("cor", "qrd")
    at = grid((taking, other))
    with pytest.raises(ValueError, match="does not play"):
        layout(Restart.CORNER, (105.0, 0.0), other.keeper, taking, other, at, PLAYERS)
    taker = sorted(taking.slots)[0]
    # the area's line belongs to the area: on it a foul is a penalty, a hundredth short of it not
    area_x = PITCH_LENGTH - PENALTY_AREA_LENGTH
    for spot in [(area_x, MIDDLE), (100.0, MIDDLE + PENALTY_AREA_HALF_WIDTH)]:
        with pytest.raises(ValueError, match="penalty area"):
            layout(Restart.FREE_KICK, spot, taker, taking, other, at, PLAYERS)
    for spot in [(area_x - 0.01, MIDDLE), (100.0, MIDDLE + PENALTY_AREA_HALF_WIDTH + 0.01)]:
        layout(Restart.FREE_KICK, spot, taker, taking, other, at, PLAYERS)
    # the same test as v1's in_penalty_area to the last bit: for a side attacking left a foul at
    # x = 16.500000000000004 is outside the area (turned into the side's frame it would be on it)
    left, right = two_teams("cor", "qrd", home_right=False)
    layout(Restart.FREE_KICK, (16.500000000000004, MIDDLE), taker, left, right, at, PLAYERS)
    with pytest.raises(ValueError, match="penalty area"):
        layout(Restart.FREE_KICK, (16.5, MIDDLE), taker, left, right, at, PLAYERS)
    # a kick-off off the centre, a penalty off the mark, both sides attacking one way
    layout(Restart.KICK_OFF, (HALFWAY, MIDDLE + 1e-7), taker, taking, other, at, PLAYERS)
    with pytest.raises(ValueError, match="centre"):
        layout(Restart.KICK_OFF, (HALFWAY, MIDDLE + 1e-5), taker, taking, other, at, PLAYERS)
    mark = (PITCH_LENGTH - PENALTY_SPOT, MIDDLE)
    layout(Restart.PENALTY, (mark[0] + 1e-7, MIDDLE), taker, taking, other, at, PLAYERS)
    with pytest.raises(ValueError, match="mark"):
        layout(Restart.PENALTY, (mark[0] + 1e-5, MIDDLE), taker, taking, other, at, PLAYERS)
    with pytest.raises(ValueError, match="mark"):
        layout(Restart.PENALTY, (PENALTY_SPOT, MIDDLE), taker, taking, other, at, PLAYERS)
    same = replace(other, attacks_right=True)
    with pytest.raises(ValueError, match="same way"):
        layout(Restart.THROW_IN, (60.0, 0.0), taker, taking, same, at, PLAYERS)
    # a corner on a flag of the defending side's goal line, a throw-in on a touchline, a goal
    # kick in the taker's goal area: within a micrometre, not ten
    for kind, on, off in [
        (Restart.CORNER, (105.0, 68.0 - 1e-7), (105.0, 68.0 - 1e-5)),
        (Restart.CORNER, (105.0 - 1e-7, 0.0), (0.0, 0.0)),
        (Restart.THROW_IN, (60.0, 1e-7), (60.0, 1e-5)),
        (Restart.GOAL_KICK, (GOAL_AREA_LENGTH + 1e-7, 30.0), (GOAL_AREA_LENGTH + 1e-5, 30.0)),
        (Restart.GOAL_KICK, (2.0, MIDDLE - GOAL_AREA_HALF_WIDTH), (100.0, MIDDLE)),
    ]:
        layout(kind, on, taker, taking, other, at, PLAYERS)
        with pytest.raises(ValueError, match="not"):
            layout(kind, off, taker, taking, other, at, PLAYERS)


# --- the kick-off --------------------------------------------------------------------------------


@pytest.mark.parametrize("pair", PAIRS)
def test_at_a_kick_off_everyone_is_in_his_own_half_and_the_opponents_outside_the_circle(pair):
    taking, other, taker, mine, _ = case(pair, Restart.KICK_OFF, (HALFWAY, MIDDLE))
    for pid, p in mine.items():
        assert p[0] <= (HALFWAY if pid == taker else HALFWAY - MARGIN) + EPS, pid
    for pid in everyone(other):
        assert math.dist(mine[pid], (HALFWAY, MIDDLE)) >= CIRCLE + MARGIN - EPS, pid
    # the circle binds: some opponent stands on its margin
    nearest = min(math.dist(mine[p], (HALFWAY, MIDDLE)) for p in everyone(other))
    assert nearest == pytest.approx(CIRCLE + MARGIN, abs=1e-6)
    assert mine[taking.keeper] == mine[other.keeper] == (6.0, MIDDLE)


# --- the goal kick -------------------------------------------------------------------------------


@given(
    st.sampled_from(PAIRS),
    st.floats(min_value=0.0, max_value=GOAL_AREA_LENGTH),
    st.floats(min_value=MIDDLE - GOAL_AREA_HALF_WIDTH, max_value=MIDDLE + GOAL_AREA_HALF_WIDTH),
    st.data(),
)
def test_at_a_goal_kick_the_opponents_are_outside_the_takers_area(pair, x, y, data):
    taking, other, taker, mine, aims = case(pair, Restart.GOAL_KICK, (x, y), any_taker(data))
    for pid in everyone(other):
        assert clear_of_area_ahead(mine[pid]), (pid, mine[pid])
    assert_apart(aims)


def test_a_pressing_side_waits_on_the_edge_of_the_area_at_a_goal_kick():
    # Corrowmere (press 0.85) stand their back line at 30 + 35 x 0.85 m, so their striker would
    # be in the area (89.75 m) and waits the margin short of its line; Quarrendale (0.2) stand deep
    assert PRESS_LINE == (30.0, 65.0)
    _, other, _, mine, _ = case(("qrd", "cor", True), Restart.GOAL_KICK, (5.5, 30.0))
    edge = PITCH_LENGTH - PENALTY_AREA_LENGTH - MARGIN
    on_edge = [p for p in other.slots if mine[p][0] == edge]
    assert [other.slots[p].role for p in on_edge] == ["ST"]
    _, other, _, mine, _ = case(("cor", "qrd", True), Restart.GOAL_KICK, (5.5, 30.0))
    assert max(mine[p][0] for p in other.slots) < edge - 10.0


@pytest.mark.parametrize(("raw", "x"), [(87.75, 87.75), (88.25, 88.0), (88.75, 88.0)])
def test_the_area_is_kept_clear_by_the_margin_from_both_sides(raw, x):
    # Corrowmere's striker stands 30 m ahead of their press line at a goal kick: with the press
    # set to put him short of the margin, inside it and inside the area, he stays, then waits on
    # the margin's edge (88 m) both times
    cor = CLUBS["cor"]
    press = (raw - 30.0 - PRESS_LINE[0]) / (PRESS_LINE[1] - PRESS_LINE[0])
    taking, other = two_teams("qrd", "cor")
    other = replace(other, club=replace(cor, tactics=replace(cor.tactics, press=press)))
    at = grid((taking, other))
    aims = layout(Restart.GOAL_KICK, (5.5, 30.0), taking.keeper, taking, other, at, PLAYERS)
    (striker,) = [p for p, s in other.slots.items() if s.role == "ST"]
    assert to_pitch(*aims[striker].point, other.attacks_right)[0] == pytest.approx(x, abs=1e-9)


# --- the corner ----------------------------------------------------------------------------------


@pytest.mark.parametrize("pair", PAIRS)
@pytest.mark.parametrize("corner", [(105.0, 0.0), (105.0, 68.0)])
def test_a_corner_loads_the_area_as_real_teams_do(pair, corner):
    # PROGRESS, M9 item 1: a match's median 3-6 attackers and 9-11 defenders in the area, and
    # Law 17: the opponents 9.15 m off the corner arc (1 m round the flag)
    for taker in sorted(two_teams(*pair)[0].slots):
        taking, other, _, mine, aims = case(pair, Restart.CORNER, corner, taker)
        assert_apart(aims)  # the attackers' spare man and the defenders' outlet once shared one
        attackers = sum(in_area_ahead(mine[p]) for p in everyone(taking))
        defenders = sum(in_own_area(mine[p]) for p in everyone(other))
        assert 3 <= attackers <= 6, taker
        assert 9 <= defenders <= 11, taker
        for pid in everyone(other):
            assert math.dist(mine[pid], theirs(corner)) >= CIRCLE + CORNER_ARC + MARGIN - EPS
    # the defender nearest the goal line (the near post's zone) is on the corner's side
    near = min(other.slots, key=lambda p: mine[p][0])
    assert (mine[near][1] - MIDDLE) * (theirs(corner)[1] - MIDDLE) > 0
    # the defending keeper on his line, the attacking one up at 30 m
    assert mine[other.keeper] == (EDGE_BAND, MIDDLE) and mine[taking.keeper] == (30.0, MIDDLE)


# --- the free kick -------------------------------------------------------------------------------


def outside_the_defending_area(spot):
    return not in_area_ahead(spot)


@given(
    st.sampled_from(PAIRS),
    st.tuples(
        st.floats(min_value=0.0, max_value=PITCH_LENGTH),
        st.floats(min_value=0.0, max_value=PITCH_WIDTH),
    ).filter(outside_the_defending_area),
    st.data(),
)
def test_at_a_free_kick_the_opponents_are_9_15_m_off_the_ball(pair, spot, data):
    # anywhere a v1 foul gives one, near the corner flags too: the band must not pull anyone back
    taking, other, taker, mine, aims = case(pair, Restart.FREE_KICK, spot, any_taker(data))
    for pid in everyone(other):
        assert math.dist(mine[pid], theirs(spot)) >= CIRCLE + MARGIN - EPS, (pid, mine[pid])
        if in_own_area(spot):  # the taker's own area: the opponents are outside it too
            assert clear_of_area_ahead(mine[pid]), (pid, mine[pid])
    assert_room_for_the_taker(taking, taker, mine, spot)
    assert_apart(aims)
    pitch_spot = to_pitch(*spot, pair[2])
    assert breaches(Restart.FREE_KICK, pitch_spot, taker, taking, other, aims_at(aims)) == []
    wall = wall_of(other, mine, spot)
    if len(wall) >= 3:  # Law 13: the taker's teammates a metre off a wall of three or more
        for p, w in itertools.product(everyone(taking), wall):
            assert math.dist(aims[p].point, aims[w].point) >= WALL_DISTANCE + MARGIN - EPS


def test_the_taker_s_teammates_keep_a_metre_off_a_wall_of_three():
    # with the highest line of the validated range Corrowmere's striker would stand 0.75 m from
    # a wall of three for a free kick 24.9 m out; he keeps the metre and the margin instead
    cor = CLUBS["cor"]
    taking, other = two_teams("cor", "qrd")
    taking = replace(taking, club=replace(cor, tactics=replace(cor.tactics, line_height=1.0)))
    spot = (80.1, MIDDLE)
    aims = layout(
        Restart.FREE_KICK,
        spot,
        sorted(taking.slots)[0],
        taking,
        other,
        grid((taking, other)),
        PLAYERS,
    )
    mine = {p: to_pitch(*a.point, p not in everyone(other)) for p, a in aims.items()}
    wall = wall_of(other, mine, spot)
    assert len(wall) == 3
    nearest = min(
        math.dist(aims[p].point, aims[w].point)
        for p in everyone(taking)
        if p != sorted(taking.slots)[0]
        for w in wall
    )
    assert nearest == pytest.approx(WALL_DISTANCE + MARGIN, abs=1e-6)


def test_a_teammate_leaves_the_taker_the_ball():
    # Corrowmere's striker stands at (86.75, 34) for any free kick from 77.65 m on: with one
    # there, taken by a winger, he steps 3.5 m off it instead of onto the ball
    taking, _, _, mine, _ = case(("cor", "qrd", True), Restart.FREE_KICK, (80.0, 34.0))
    (striker,) = [p for p, s in taking.slots.items() if s.role == "ST"]
    assert mine[striker] == pytest.approx((86.75, 34.0), abs=1e-9)
    taker = next(p for p, s in sorted(taking.slots.items()) if s.role == "W")
    _, _, _, mine, _ = case(("cor", "qrd", True), Restart.FREE_KICK, (86.75, 34.0), taker)
    assert math.dist(mine[striker], (86.75, 34.0)) == pytest.approx(TEAMMATE_GAP + MARGIN)


def test_the_keeper_of_the_side_taking_a_free_kick_in_its_half_stays_behind_his_back_line():
    # at (20, 34) the back line stands on its floor of 6 m and the keeper 1.5 m behind it
    taking, _, _, mine, _ = case(("cor", "qrd", True), Restart.FREE_KICK, (20.0, MIDDLE))
    assert mine[taking.keeper][0] <= 6.0 - 1.5 + EPS


# every 2 m within 8 m of a touchline or a goal line, outside the defending side's area
EDGE_SPOTS = [
    (float(x), float(y))
    for x in range(0, 106, 2)
    for y in range(0, 69, 2)
    if (min(y, 68 - y) <= 8 or min(x, 105 - x) <= 8) and not in_area_ahead((x, y))
]


@pytest.mark.parametrize("pair", PAIRS)
def test_a_free_kick_near_an_edge_keeps_the_distance_inside_the_band(pair):
    # pushed straight off the ball, or round it, a player could leave the pitch; the band would
    # pull him back within the distance (a free kick at (86, 8): one at 7.5 m), so he goes on
    # round the circle to a point inside the band
    for spot in [*EDGE_SPOTS, (105.0, 55.0), (105.0, 13.0)]:  # a wall the band would squeeze
        _, other, _, mine, aims = case(pair, Restart.FREE_KICK, spot)
        assert_apart(aims)
        for pid in everyone(other):
            assert math.dist(mine[pid], theirs(spot)) >= CIRCLE + MARGIN - EPS, (spot, pid)
            assert EDGE_BAND - EPS <= mine[pid][0] <= PITCH_LENGTH - EDGE_BAND + EPS
            assert EDGE_BAND - EPS <= mine[pid][1] <= PITCH_WIDTH - EDGE_BAND + EPS


def test_a_free_kick_in_the_takers_area_clears_it_of_a_pressing_side():
    # Corrowmere press at a free kick in Quarrendale's area as at a goal kick: their striker,
    # out of the area, goes round the ball to 9.15 m plus the margin; on the area's line the
    # rule applies, a hundredth beyond it not
    spot = (PENALTY_AREA_LENGTH, 40.0)
    _, other, _, mine, _ = case(("qrd", "cor", True), Restart.FREE_KICK, spot)
    edge = PITCH_LENGTH - PENALTY_AREA_LENGTH - MARGIN
    (striker,) = [p for p in other.slots if mine[p][0] > edge - 2.0]
    assert clear_of_area_ahead(mine[striker])
    assert math.dist(mine[striker], theirs(spot)) == pytest.approx(CIRCLE + MARGIN, abs=1e-6)
    _, other, _, mine, _ = case(("qrd", "cor", True), Restart.FREE_KICK, (16.51, 40.0))
    assert max(mine[p][0] for p in other.slots) < edge - 10.0


def wall_of(other, mine, spot):
    """The opponents in the wall: square to the line from the ball to the goal's centre, 9.15 m
    plus the margin along it off the ball and within a metre of it (a player only kept off the
    ball stands on the circle of that radius, nearer the ball along the line)."""
    ball = theirs(spot)
    d = math.dist(ball, (0.0, MIDDLE))
    u = (-ball[0] / d, (MIDDLE - ball[1]) / d)
    wall = []
    for p in other.slots:
        dx, dy = mine[p][0] - ball[0], mine[p][1] - ball[1]
        along, across = dx * u[0] + dy * u[1], dx * u[1] - dy * u[0]
        if abs(along - (CIRCLE + MARGIN)) < 1e-6 and abs(across) <= 1.0:
            wall.append(p)
    return wall


@pytest.mark.parametrize("pair", PAIRS)
@pytest.mark.parametrize(
    ("out", "size"),
    [
        (WALL_OF_FOUR - 0.01, 4),
        (WALL_OF_FOUR, 3),
        (WALL_OF_THREE - 0.01, 3),
        (WALL_OF_THREE, 2),
        (SHOOTING_RANGE, 2),
        (SHOOTING_RANGE + 0.01, 0),
    ],
)
def test_a_free_kick_in_shooting_range_gets_a_wall_by_its_distance(pair, out, size):
    assert (WALL_OF_FOUR, WALL_OF_THREE, SHOOTING_RANGE) == (20.0, 25.0, 30.0)
    spot = (PITCH_LENGTH - out, MIDDLE)  # straight on, `out` metres from the goal's centre
    taking, other, _, mine, _ = case(pair, Restart.FREE_KICK, spot)
    wall = wall_of(other, mine, spot)
    if size:  # the wall, and the keeper on his line behind it
        assert len(wall) == size
        assert mine[other.keeper][0] == EDGE_BAND
    else:  # no wall: at most one player kept off the ball straight in its way, the keeper off
        assert len(wall) <= 1  # his line, behind his back line as in open play
        assert mine[other.keeper][0] > EDGE_BAND + 1.0


@pytest.mark.parametrize(
    ("spot", "size"), [((85.0, 15.0), 2), ((88.0, 50.0), 3), ((92.0, 8.0), 2)]
)  # 27.6, 23.3 and 29.1 m from the goal's centre
def test_a_wall_from_an_angle_stands_between_the_ball_and_the_goal(spot, size):
    taking, other, _, mine, _ = case(("vel", "slt", False), Restart.FREE_KICK, spot)
    assert len(wall_of(other, mine, spot)) == size


# --- the throw-in --------------------------------------------------------------------------------


@given(
    st.sampled_from(PAIRS),
    st.floats(min_value=0.0, max_value=PITCH_LENGTH),
    st.sampled_from([0.0, PITCH_WIDTH]),
    st.data(),
)
def test_at_a_throw_in_the_opponents_are_2_m_off_the_thrower(pair, x, y, data):
    taking, other, taker, mine, aims = case(pair, Restart.THROW_IN, (x, y), any_taker(data))
    for pid in everyone(other):
        assert math.dist(mine[pid], theirs((x, y))) >= THROW_DISTANCE + MARGIN - EPS, pid
    assert_room_for_the_taker(taking, taker, mine, (x, y))
    assert_apart(aims)


def test_the_throw_in_distance_binds():
    # with the throw at 40 m, some opponent of some pair would stand nearer: he is on the margin
    nearest = []
    for pair in PAIRS:
        _, other, _, mine, _ = case(pair, Restart.THROW_IN, (40.0, 0.0))
        nearest.append(min(math.dist(mine[p], theirs((40.0, 0.0))) for p in everyone(other)))
    assert min(nearest) == pytest.approx(THROW_DISTANCE + MARGIN, abs=1e-6)


# --- the penalty ---------------------------------------------------------------------------------


@pytest.mark.parametrize("pair", PAIRS)
def test_at_a_penalty_all_but_taker_and_keeper_are_out_of_the_area_the_arc_and_behind(pair):
    for taker in (lambda t: sorted(t.slots)[-1], lambda t: t.keeper):
        taking, other, taker, mine, _ = case(pair, Restart.PENALTY, PENALTY_MARK, taker)
        for pid in everyone(taking):
            if pid == taker:
                continue
            p = mine[pid]
            assert clear_of_area_ahead(p), pid
            assert math.dist(p, PENALTY_MARK) >= CIRCLE + MARGIN - EPS, pid
            assert p[0] <= PENALTY_MARK[0] - MARGIN, pid
        mark = theirs(PENALTY_MARK)
        for pid in other.slots:
            p = mine[pid]
            assert p[0] >= PENALTY_AREA_LENGTH + MARGIN or abs(p[1] - MIDDLE) >= (
                PENALTY_AREA_HALF_WIDTH + MARGIN
            ), pid
            assert math.dist(p, mark) >= CIRCLE + MARGIN - EPS, pid
            assert p[0] >= mark[0] + MARGIN, pid
        assert mine[other.keeper] == (EDGE_BAND, MIDDLE)  # on his line, as near as the band allows
        # both sides' outfield players wait round the area's edge for a rebound
        for team in (taking, other):
            mark_here = PENALTY_MARK if team is taking else mark
            assert max(math.dist(mine[p], mark_here) for p in team.slots) < 30.0


# --- the Laws where everyone stands (M9 item 5: the ball is played only once nobody breaks them) --

# cor takes it and attacks to the right, so the pitch is its frame; qrd attacks to the left
BREACH_TEAMS = two_teams("cor", "qrd", True)


def lawful_at():
    """Everyone far from any restart's spot, in his own half, behind any penalty mark."""
    taking, other = BREACH_TEAMS
    at = {p: (30.0, 4.0 + 6.0 * i) for i, p in enumerate(sorted(everyone(taking)))}
    at |= {p: (75.0, 4.0 + 6.0 * i) for i, p in enumerate(sorted(everyone(other)))}
    return at


# points whose float distance from the centre and from the penalty mark is exactly 9.15 (found by
# a search; the test asserts it), so `<` and `<=` differ there
ON_THE_CIRCLE = (52.5022875, 43.149999714062496)
ON_THE_ARC = (88.28125, 41.14271646066817)


TAKER = sorted(BREACH_TEAMS[0].slots)[-1]
MATE = sorted(BREACH_TEAMS[0].slots)[0]
RIVAL = sorted(BREACH_TEAMS[1].slots)[0]
# (kind, spot, who moves, where to, breaks the Laws): each boundary from both sides, in literals
BREACHES = [
    # a kick-off: everyone in his own half (the halfway line is part of both), the opponents
    # 9.15 m off the centre
    (Restart.KICK_OFF, (52.5, 34.0), MATE, (52.5, 10.0), False),
    (Restart.KICK_OFF, (52.5, 34.0), MATE, (52.51, 10.0), True),
    (Restart.KICK_OFF, (52.5, 34.0), RIVAL, (52.5, 10.0), False),
    (Restart.KICK_OFF, (52.5, 34.0), RIVAL, (52.49, 10.0), True),
    (Restart.KICK_OFF, (52.5, 34.0), RIVAL, ON_THE_CIRCLE, False),
    (Restart.KICK_OFF, (52.5, 34.0), RIVAL, (52.5, 34.0 + 9.14), True),
    (Restart.KICK_OFF, (52.5, 34.0), MATE, (52.5, 34.0 + 5.0), False),  # his side may be near
    # a goal kick: the opponents outside the taker's area, its lines included
    (Restart.GOAL_KICK, (5.5, 30.0), RIVAL, (16.51, 34.0), False),
    (Restart.GOAL_KICK, (5.5, 30.0), RIVAL, (16.5, 34.0), True),
    (Restart.GOAL_KICK, (5.5, 30.0), MATE, (10.0, 34.0), False),
    # a corner: the opponents 9.15 m off the corner arc of 1 m
    (Restart.CORNER, (105.0, 0.0), RIVAL, (105.0, 10.15), False),
    (Restart.CORNER, (105.0, 0.0), RIVAL, (105.0, 10.14), True),
    (Restart.CORNER, (105.0, 0.0), MATE, (104.0, 2.0), False),
    # a free kick: the opponents 9.15 m off the ball; in the taker's own area, out of it too
    (Restart.FREE_KICK, (60.0, 0.0), RIVAL, (60.0, 9.15), False),
    (Restart.FREE_KICK, (60.0, 0.0), RIVAL, (60.0, 9.14), True),
    (Restart.FREE_KICK, (60.0, 0.0), MATE, (60.0, 3.0), False),
    (Restart.FREE_KICK, (10.0, 34.0), RIVAL, (16.51, 50.0), False),
    (Restart.FREE_KICK, (10.0, 34.0), RIVAL, (16.5, 50.0), True),
    (Restart.FREE_KICK, (30.0, 34.0), RIVAL, (16.5, 50.0), False),  # not his area: 9.15 m only
    # a throw-in: the opponents 2 m off the thrower
    (Restart.THROW_IN, (60.0, 0.0), RIVAL, (60.0, 2.0), False),
    (Restart.THROW_IN, (60.0, 0.0), RIVAL, (60.0, 1.99), True),
    # a penalty: all but the taker and the keeper behind the mark, outside the area and the arc
    (Restart.PENALTY, (94.0, 34.0), MATE, (94.0, 10.0), False),
    (Restart.PENALTY, (94.0, 34.0), MATE, (94.01, 10.0), True),
    (Restart.PENALTY, (94.0, 34.0), RIVAL, (88.49, 34.0 + 20.0), False),
    (Restart.PENALTY, (94.0, 34.0), RIVAL, (88.5, 34.0 + 20.0), True),
    (Restart.PENALTY, (94.0, 34.0), MATE, ON_THE_ARC, False),
    (Restart.PENALTY, (94.0, 34.0), MATE, (94.0 - 9.15, 34.0), False),
    (Restart.PENALTY, (94.0, 34.0), MATE, (94.0 - 9.14, 34.0), True),
    (Restart.PENALTY, (94.0, 34.0), BREACH_TEAMS[1].keeper, (105.0, 34.0), False),
    (Restart.PENALTY, (94.0, 34.0), BREACH_TEAMS[0].keeper, (90.0, 34.0), True),
    (Restart.PENALTY, (94.0, 34.0), TAKER, (94.0, 34.0), False),
]


@pytest.mark.parametrize(("kind", "spot", "who", "where", "broken"), BREACHES)
def test_the_laws_are_kept_exactly_on_their_lines_and_broken_a_centimetre_inside(
    kind, spot, who, where, broken
):
    taking, other = BREACH_TEAMS
    at = lawful_at()
    assert breaches(kind, spot, TAKER, taking, other, at) == []
    at[who] = where
    assert breaches(kind, spot, TAKER, taking, other, at) == ([who] if broken else [])


def test_the_exact_points_lie_exactly_on_the_circle_and_the_arc():
    assert math.dist(ON_THE_CIRCLE, (52.5, 34.0)) == 9.15
    assert math.dist(ON_THE_ARC, (94.0, 34.0)) == 9.15
    assert abs(ON_THE_ARC[1] - 34.0) > 20.16 or ON_THE_ARC[0] < 88.5  # outside the area


def test_a_player_breaking_two_laws_is_named_once():
    # in the kicking side's half and inside the circle at a kick-off
    taking, other = BREACH_TEAMS
    at = lawful_at()
    at[RIVAL] = (50.0, 34.0)
    assert breaches(Restart.KICK_OFF, (52.5, 34.0), TAKER, taking, other, at) == [RIVAL]


def test_those_who_break_the_laws_are_named_in_order():
    # six opponents inside the circle, put there in reverse order: the result is sorted by id
    taking, other = BREACH_TEAMS
    at = lawful_at()
    six = sorted(other.slots)[:6]
    for i, pid in enumerate(reversed(six)):
        at[pid] = (52.5 + 1.0 + i, 34.0)
    assert breaches(Restart.KICK_OFF, (52.5, 34.0), TAKER, taking, other, at) == six


def test_a_side_attacking_left_breaks_the_laws_in_its_own_frame():
    # turned half round, the same breach: qrd takes a throw-in, attacking to the left
    other, taking = BREACH_TEAMS
    at = {p: (105.0 - x, 68.0 - y) for p, (x, y) in lawful_at().items()}
    at[MATE] = (45.0, 68.0 - 1.99)
    taker = sorted(taking.slots)[-1]
    assert breaches(Restart.THROW_IN, (45.0, 68.0), taker, taking, other, at) == [MATE]
