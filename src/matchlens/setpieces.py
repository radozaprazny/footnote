"""Where everyone stands at a restart of generator v2, within the Laws of the Game.

`layout` gives every player an `Aim` for a dead ball: the taker goes to the spot, the others to
the layout of the restart, worked out in each team's frame (x from its own goal line, L below
y = 34) and turned onto the pitch. The Laws it keeps: at a kick-off everyone is in his own half
and the opponents outside the centre circle; at a goal kick the opponents are outside the taker's
penalty area; at a free kick the opponents are 9.15 m from the ball (a wall in shooting range),
and outside the taker's penalty area when he takes it there; at a throw-in the opponents are 2 m
from the thrower; at a corner they are 9.15 m from the corner arc; at a penalty everyone but the
taker and the defending keeper is outside the penalty area and the penalty arc and behind the
mark. A corner loads the area as real teams do (PROGRESS, M9 item 1: 3–6 attackers and 9–11
defenders in it). No two players share a point (PLAYER_GAP), and at a free kick or a throw-in the
taker's teammates leave him room (TEAMMATE_GAP). Every point lies inside the band along the edges
(`movement.EDGE_BAND`), the taker's too: the decision layer puts the ball, a thrower and a keeper
on his line on the line itself.
"""

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace

from matchlens.events import PITCH_LENGTH, PITCH_WIDTH, Restart
from matchlens.formations import to_pitch
from matchlens.league import Player
from matchlens.match import (
    GOAL_AREA_HALF_WIDTH,
    GOAL_AREA_LENGTH,
    PENALTY_AREA_HALF_WIDTH,
    PENALTY_AREA_LENGTH,
    PENALTY_SPOT,
)
from matchlens.movement import EDGE_BAND
from matchlens.targets import (
    COMFORT_BRAKING,
    HALFWAY,
    MIDDLE,
    Aim,
    Team,
    back_line,
    band,
    keeper_point,
    pace_to,
    shape_point,
)

CIRCLE = 9.15  # m, the centre circle's radius and the distance at a free kick and a corner
CORNER_ARC = 1.0  # m, the corner arc's radius: a corner's distance is measured from it
MARGIN = 0.5  # m kept beyond every line and distance of the Laws
THROW_DISTANCE = 2.0
TEAMMATE_GAP = 3.0  # m a teammate keeps off the ball at a free kick or a throw-in
PLAYER_GAP = 0.5  # m, the least room between two players' points
RING = 0.25  # m between the rings searched round a point for a free one
SHOOTING_RANGE = 30.0  # m from the goal's centre: a free kick there gets a wall
WALL_OF_FOUR, WALL_OF_THREE = 20.0, 25.0  # nearer than these a wall of four, of three; else two
WALL_GAP = 0.6  # m between the players of a wall
WALL_DISTANCE = 1.0  # m the taker's teammates keep off a wall of three or more (Law 13)
ON_SPOT = 1e-6  # m a restart's spot may lie off its line or point
KICK_OFF_LINES = (25.0, 22.0)  # the back line's x of the side kicking off and of the other
KICK_OFF_KEEPER = (6.0, MIDDLE)
GOAL_KICK_LINE = 12.0  # of the side taking a goal kick
# the other side's back line at a goal kick (and a free kick in the taker's area) from a press of
# 0 to 1: from about 0.8 its striker would stand in the area and waits on its edge instead
PRESS_LINE = (30.0, 65.0)
AREA_X = PITCH_LENGTH - PENALTY_AREA_LENGTH  # the penalty area's line ahead, in a side's frame
# the corner: the attackers' spots in the area and beside it and the defenders' zones, each in
# its own side's frame for a corner from the low-y side (mirrored for the other), so the near
# post is the low-y one
CORNER_BOX = ((99.0, 29.0), (99.5, 39.0), (94.0, 34.0), (97.0, 34.0), (92.0, 40.0))
CORNER_EDGE = (86.0, 34.0)
CORNER_SHORT = (100.0, MIDDLE - 24.0)
CORNER_BACK = ((58.0, 24.0), (58.0, 44.0))
CORNER_SPARE = (66.0, MIDDLE)  # goal-side of the defenders' outlet, which stands at 70 m
CORNER_ZONES = (
    (5.5, 28.0),
    (5.5, 34.0),
    (5.5, 40.0),
    (11.0, 30.0),
    (11.0, 38.0),
    (1.0, 30.5),
    (8.0, 24.0),
    (8.0, 44.0),
    (14.0, 34.0),
)
CORNER_OUTLET = (35.0, MIDDLE)
SET_KEEPER = (30.0, MIDDLE)  # the keeper of the side taking a corner or a penalty
# a penalty: the rows outside the area, the arc and the mark, in the shooting side's frame; the
# shooting side stands in the front row, the other a row behind and a metre aside
PENALTY_ROWS = (87.0, 84.0, 81.0)
PENALTY_YS = (26.0, 42.0, 22.0, 46.0, 18.0, 50.0, 14.0, 54.0)


def _anywhere(p) -> bool:
    return True


@dataclass(frozen=True)
class _Side:
    """A side's points at a restart in its own frame, and where its players may stand: at least
    `distance` plus the margin off `centre` (when there is one) and where `allowed` says; the
    players in `first` are placed before the others (a wall), those in `free` only kept inside
    the band and off the others (a keeper on his line at a penalty)."""

    points: dict[str, tuple[float, float]]
    centre: tuple[float, float] | None = None
    distance: float = 0.0
    allowed: Callable[[tuple[float, float]], bool] = _anywhere
    first: tuple[str, ...] = ()
    free: tuple[str, ...] = ()


def layout(
    kind: Restart,
    spot: tuple[float, float],
    taker: str,
    taking: Team,
    other: Team,
    at: Mapping[str, tuple[float, float]],
    players: Mapping[str, Player],
) -> dict[str, Aim]:
    """Every player's aim for a restart of `kind` at `spot` (on the pitch), taken by `taker` of
    `taking`; `at` is where everyone is now (on the pitch), for the pace to his point: a walk or
    a jog, a run from far (`targets.pace_to`). Refused: a taker of the other side, two sides
    attacking the same way, a spot off its place (the centre, the mark, a flag of the defending
    side's goal line, a touchline, the taker's goal area), and a free kick inside the defending
    side's penalty area (a foul there gives a penalty)."""
    _check(kind, spot, taker, taking, other)
    own_area = kind is Restart.FREE_KICK and in_penalty_area(spot, not taking.attacks_right)

    def aim(pid, there):
        pace = min(pace_to(at[pid], there, players[pid].work_rate), players[pid].top_speed)
        return Aim(there, pace, (0.0, 0.0), COMFORT_BRAKING)

    out = {taker: aim(taker, band(spot))}
    placed = [band(spot)]  # on the pitch
    wall: list[tuple[float, float]] = []  # the other side's, on the pitch, once placed
    # the other side first, its wall first of all: its Laws bind; then the taker's teammates
    for team in (other, taking):
        frame = team.attacks_right
        ball = to_pitch(*spot, frame)
        side = _taking(kind, ball, team) if team is taking else _other(kind, ball, team, own_area)
        if team is taking and len(wall) >= 3:
            side = _off_the_wall(side, [to_pitch(*w, frame) for w in wall])
        rest = sorted(p for p in side.points if p not in side.first)
        for pid in (*side.first, *rest):
            if pid == taker:
                continue
            there = to_pitch(*_place(pid, side, [to_pitch(*q, frame) for q in placed]), frame)
            placed.append(there)
            out[pid] = aim(pid, there)
        if team is other:
            wall = [out[p].point for p in side.first]
    return out


def breaches(
    kind: Restart,
    spot: tuple[float, float],
    taker: str,
    taking: Team,
    other: Team,
    at: Mapping[str, tuple[float, float]],
) -> list[str]:
    """The players who break the Laws where they stand (`at`, on the pitch) at a restart of `kind`
    at `spot` taken by `taker` of `taking`, sorted: the decision layer plays the ball only once
    there are none. The Laws' own distances, without the MARGIN `layout` keeps beyond them: at a
    kick-off everyone in his own half and the opponents outside the centre circle; at a goal kick
    the opponents outside the taker's area; at a free kick the opponents 9.15 m off the ball and,
    in the taker's own area, outside it; at a throw-in 2 m off; at a corner 9.15 m off the corner
    arc; at a penalty everyone but the taker and the defending keeper outside the area and the arc
    and behind the mark."""
    theirs = (*other.slots, other.keeper)
    everyone = (*taking.slots, taking.keeper, *theirs)
    if kind is Restart.KICK_OFF:
        own = {
            pid: team.attacks_right
            for team in (taking, other)
            for pid in (*team.slots, team.keeper)
        }
        out = [p for p in everyone if to_pitch(*at[p], own[p])[0] > HALFWAY]
        out += [p for p in theirs if math.dist(at[p], spot) < CIRCLE]
    elif kind is Restart.GOAL_KICK:
        out = [p for p in theirs if in_penalty_area(at[p], not taking.attacks_right)]
    elif kind is Restart.CORNER:
        out = [p for p in theirs if math.dist(at[p], spot) < CIRCLE + CORNER_ARC]
    elif kind is Restart.THROW_IN:
        out = [p for p in theirs if math.dist(at[p], spot) < THROW_DISTANCE]
    elif kind is Restart.FREE_KICK:
        own_area = in_penalty_area(spot, not taking.attacks_right)
        out = [
            p
            for p in theirs
            if math.dist(at[p], spot) < CIRCLE
            or (own_area and in_penalty_area(at[p], not taking.attacks_right))
        ]
    else:  # a penalty, in the shooting side's frame: the mark at x = 94
        mark_x = to_pitch(*spot, taking.attacks_right)[0]
        out = [
            p
            for p in everyone
            if p not in (taker, other.keeper)
            and (
                in_penalty_area(at[p], taking.attacks_right)
                or math.dist(at[p], spot) < CIRCLE
                or to_pitch(*at[p], taking.attacks_right)[0] > mark_x
            )
        ]
    return sorted(set(out))


def _off_the_wall(side: _Side, wall: list[tuple[float, float]]) -> _Side:
    """`side`'s rule, and WALL_DISTANCE plus the margin off every player of `wall`."""
    rule = side.allowed
    keep = WALL_DISTANCE + MARGIN
    return replace(side, allowed=lambda q: rule(q) and all(math.dist(q, w) >= keep for w in wall))


def _check(kind, spot, taker, taking, other) -> None:
    if taker not in (*taking.slots, taking.keeper):
        raise ValueError(f"{taker} does not play for {taking.club.id}")
    if taking.attacks_right == other.attacks_right:
        raise ValueError("both sides attack the same way")
    if kind is Restart.KICK_OFF and math.dist(spot, (HALFWAY, MIDDLE)) > ON_SPOT:
        raise ValueError(f"a kick-off at {spot} is not on the centre")
    mark = to_pitch(PITCH_LENGTH - PENALTY_SPOT, MIDDLE, taking.attacks_right)
    if kind is Restart.PENALTY and math.dist(spot, mark) > ON_SPOT:
        raise ValueError(f"a penalty at {spot} is not on the mark {mark}")
    goal_x = PITCH_LENGTH if taking.attacks_right else 0.0  # the defending side's goal line
    off_a_touchline = min(abs(spot[1]), abs(PITCH_WIDTH - spot[1])) > ON_SPOT
    if kind is Restart.CORNER and (abs(spot[0] - goal_x) > ON_SPOT or off_a_touchline):
        raise ValueError(f"a corner at {spot} is not on a flag of the defending side's goal line")
    if kind is Restart.THROW_IN and off_a_touchline:
        raise ValueError(f"a throw-in at {spot} is not on a touchline")
    in_goal_area = (
        abs(spot[0] - (PITCH_LENGTH - goal_x)) <= GOAL_AREA_LENGTH + ON_SPOT
        and abs(spot[1] - MIDDLE) <= GOAL_AREA_HALF_WIDTH + ON_SPOT
    )
    if kind is Restart.GOAL_KICK and not in_goal_area:
        raise ValueError(f"a goal kick at {spot} is not in the taker's goal area")
    if kind is Restart.FREE_KICK and in_penalty_area(spot, taking.attacks_right):
        raise ValueError(f"a free kick at {spot} is inside the defending side's penalty area")


def in_penalty_area(where, right_hand: bool) -> bool:
    """Inside the penalty area at the right-hand (x = 105) or left-hand goal, on the pitch, its
    lines included: the same test as generator v1's `in_penalty_area`, so the two agree on which
    foul is a penalty to the last bit; generator v2 tells a penalty from a free kick by it."""
    goal_x = PITCH_LENGTH if right_hand else 0.0
    return (
        abs(where[0] - goal_x) <= PENALTY_AREA_LENGTH
        and abs(where[1] - MIDDLE) <= PENALTY_AREA_HALF_WIDTH
    )


def _shape(team, ball, attacking, line):
    phase = "attack" if attacking else "defend"
    width = team.club.tactics.width
    return {p: shape_point(team.slots[p], phase, line, ball, width) for p in sorted(team.slots)}


def _press_line(team) -> float:
    return PRESS_LINE[0] + (PRESS_LINE[1] - PRESS_LINE[0]) * team.club.tactics.press


def _open_play(team, ball, attacking):
    """The shape for open play at the ball, the keeper behind his back line in his own half."""
    line = back_line(ball[0], attacking, team.club.tactics.line_height)
    keeper = keeper_point(ball, line if ball[0] < HALFWAY else None)
    return _shape(team, ball, attacking, line) | {team.keeper: keeper}


def _taking(kind, ball, team) -> _Side:
    """The taker's side, in its frame."""
    if kind is Restart.KICK_OFF:
        points = _shape(team, ball, True, KICK_OFF_LINES[0]) | {team.keeper: KICK_OFF_KEEPER}
        return _Side({p: _own_half(q) for p, q in points.items()}, allowed=_in_own_half)
    if kind is Restart.GOAL_KICK:
        return _Side(_shape(team, ball, True, GOAL_KICK_LINE) | {team.keeper: keeper_point(ball)})
    if kind is Restart.CORNER:
        return _Side(_corner_attack(team, _side_of(ball)) | {team.keeper: SET_KEEPER})
    if kind is Restart.PENALTY:
        points = _penalty_rows(sorted(team.slots), front=True) | {team.keeper: SET_KEEPER}
        return _Side(points, ball, CIRCLE, lambda q: _behind(q, ball[0]) and _clear_ahead(q))
    return _Side(_open_play(team, ball, True), ball, TEAMMATE_GAP)  # a free kick, a throw-in


def _other(kind, ball, team, own_area: bool) -> _Side:
    """The side not taking it, in its frame; `own_area`: a free kick in the taker's own area."""
    if kind is Restart.KICK_OFF:
        points = _shape(team, ball, False, KICK_OFF_LINES[1]) | {team.keeper: KICK_OFF_KEEPER}
        points = {p: _own_half(q) for p, q in points.items()}
        return _Side(points, (HALFWAY, MIDDLE), CIRCLE, _in_own_half)
    if kind is Restart.GOAL_KICK or own_area:  # they leave the taker's area
        points = _shape(team, ball, False, _press_line(team)) | {team.keeper: keeper_point(ball)}
        points = {p: q if _clear_ahead(q) else (AREA_X - MARGIN, q[1]) for p, q in points.items()}
        distance = CIRCLE if own_area else 0.0
        return _Side(points, ball, distance, _clear_ahead)
    if kind is Restart.CORNER:
        points = _corner_defence(team, _side_of(ball)) | {team.keeper: (EDGE_BAND, MIDDLE)}
        return _Side(points, ball, CIRCLE + CORNER_ARC)
    if kind is Restart.PENALTY:
        rows = _penalty_rows(sorted(team.slots), front=False)
        points = {p: _turned(q) for p, q in rows.items()} | {team.keeper: (EDGE_BAND, MIDDLE)}
        return _Side(
            points,
            ball,
            CIRCLE,
            lambda q: q[0] >= ball[0] + MARGIN and _clear_behind(q),
            free=(team.keeper,),
        )
    points = _open_play(team, ball, False)
    if kind is Restart.THROW_IN:
        return _Side(points, ball, THROW_DISTANCE)
    goal_distance = math.dist(ball, (0.0, MIDDLE))
    if goal_distance > SHOOTING_RANGE:
        return _Side(points, ball, CIRCLE)
    wall = _wall(points, sorted(team.slots), ball, goal_distance)
    keeper = (EDGE_BAND, MIDDLE + (1.5 if ball[1] < MIDDLE else -1.5))  # behind his wall
    return _Side(points | wall | {team.keeper: keeper}, ball, CIRCLE, first=tuple(wall))


def _place(pid: str, side: _Side, placed: list[tuple[float, float]]) -> tuple[float, float]:
    """Player `pid`'s point in his side's frame: his own (pushed straight off the side's centre
    if he stands too near it, then kept inside the band) if he may stand there and it is at least
    PLAYER_GAP off every point `placed` (in the same frame); else the nearest point where he may,
    on rings RING apart round it, each searched from the side facing away from the centre."""
    free = pid in side.free
    radius = side.distance + MARGIN
    p = side.points[pid]
    if side.centre is not None and not free:
        p = _pushed(p, side.centre, radius)
    p = band(p)

    def ok(q):
        if not _in_band(q) or any(math.dist(q, s) < PLAYER_GAP for s in placed):
            return False
        if free:
            return True
        far = side.centre is None or math.dist(q, side.centre) >= radius - 1e-9
        return far and side.allowed(q)

    if side.centre is None:
        start = math.pi  # towards his own goal
    else:
        start = math.atan2(p[1] - side.centre[1], p[0] - side.centre[0])
    for k in range(int(2 * PITCH_LENGTH / RING)):
        steps = max(1, math.ceil(math.pi * k))  # either way round, about RING apart on the ring
        for i in range(steps + 1):
            turn = math.pi * i / steps
            for a in (start + turn, start - turn) if 0 < i < steps else (start + turn,):
                q = (p[0] + k * RING * math.cos(a), p[1] + k * RING * math.sin(a))
                if ok(q):
                    return q
    raise AssertionError(f"no free point for {pid}")  # unreachable: the pitch has room for 22


def _pushed(p, centre, radius):
    """`p` moved straight away from `centre` to `radius` off it, if it is nearer."""
    d = math.dist(p, centre)
    if d >= radius:
        return p
    if d == 0.0:
        return (centre[0] - radius, centre[1])
    return (
        centre[0] + (p[0] - centre[0]) * radius / d,
        centre[1] + (p[1] - centre[1]) * radius / d,
    )


def _in_band(p) -> bool:
    return band(p) == p


def _own_half(p):
    return (min(p[0], HALFWAY - MARGIN), p[1])


def _in_own_half(p) -> bool:
    return p[0] <= HALFWAY - MARGIN


def _behind(p, mark_x) -> bool:
    return p[0] <= mark_x - MARGIN


def _clear_ahead(p) -> bool:
    """Outside the penalty area ahead (the one the side attacks) by the margin at least."""
    return p[0] <= AREA_X - MARGIN or abs(p[1] - MIDDLE) >= PENALTY_AREA_HALF_WIDTH + MARGIN


def _clear_behind(p) -> bool:
    """Outside the side's own penalty area by the margin at least."""
    return (
        p[0] >= PENALTY_AREA_LENGTH + MARGIN
        or abs(p[1] - MIDDLE) >= PENALTY_AREA_HALF_WIDTH + MARGIN
    )


def _side_of(ball) -> float:
    return 1.0 if ball[1] < MIDDLE else -1.0  # mirror the spots for a corner from y = 68


def _by_role(team, order):
    """The outfield players, those of the roles in `order` first, then the rest by id."""
    rank = {role: i for i, role in enumerate(order)}
    return sorted(team.slots, key=lambda p: (rank.get(team.slots[p].role, len(order)), p))


def _flip(point, side):
    return (point[0], MIDDLE + side * (point[1] - MIDDLE))


def _corner_attack(team, side):
    order = _by_role(team, ("CB", "ST", "AM", "W", "CM", "DM", "FB"))
    spots = [*CORNER_BOX, CORNER_EDGE, CORNER_SHORT, *CORNER_BACK]
    spots += [CORNER_SPARE] * (len(order) - len(spots))
    return {p: _flip(q, side) for p, q in zip(order, spots, strict=False)}


def _corner_defence(team, side):
    order = _by_role(team, ("CB", "FB", "DM", "CM", "W", "AM", "ST"))
    spots = [*CORNER_ZONES, CORNER_OUTLET]
    spots += [CORNER_OUTLET] * (len(order) - len(spots))
    return {p: _flip(q, side) for p, q in zip(order, spots, strict=False)}


def _penalty_rows(outfield, front):
    """The outfield players' points round the area at a penalty, in the shooting side's frame:
    the shooting side along the front row, then the next; the other side a row further back."""
    points = {}
    for i, p in enumerate(outfield):
        row, column = divmod(i, len(PENALTY_YS))
        if front:
            points[p] = (PENALTY_ROWS[row], PENALTY_YS[column])
        else:
            points[p] = (PENALTY_ROWS[min(row + 1, 2)] - 1.5, PENALTY_YS[column] + 1.0)
    return points


def _turned(p):
    """A point of the shooting side's frame in the other side's frame."""
    return (PITCH_LENGTH - p[0], PITCH_WIDTH - p[1])


def _wall(points, outfield, ball, goal_distance):
    """A wall of two to four, the players nearest its place, between the ball and the goal's
    centre 9.15 m (plus the margin) off the ball."""
    count = 4 if goal_distance < WALL_OF_FOUR else 3 if goal_distance < WALL_OF_THREE else 2
    ux, uy = (0.0 - ball[0]) / goal_distance, (MIDDLE - ball[1]) / goal_distance
    cx, cy = ball[0] + ux * (CIRCLE + MARGIN), ball[1] + uy * (CIRCLE + MARGIN)
    nearest = sorted(outfield, key=lambda p: (math.dist(points[p], (cx, cy)), p))[:count]
    wall = {}
    for i, p in enumerate(nearest):
        offset = (i - (count - 1) / 2) * WALL_GAP
        wall[p] = (cx - uy * offset, cy + ux * offset)
    return wall
