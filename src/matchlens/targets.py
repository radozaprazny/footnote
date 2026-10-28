"""Where every player of generator v2 wants to be at a moment of play, and at what pace.

The movement layer (`matchlens.movement`) then moves him there under his limits. Rules, the first
that applies: the carrier (keeper or not) carries the ball where the decision layer sends him;
the receiver (keeper or not) runs to where the ball lands, at the pace that gets him there in
time; one or two pressers (by the club's press) close the carrier down, the second covering
behind; the keeper stands on the line from his goal to the ball, deeper the further the ball is
and behind his back line while the ball is in his half; defenders near an opponent mark him
goal-side; attackers make their runs (a full-back overlapping, a winger coming inside, a striker
on the last defender's shoulder); everyone else takes his slot in the club's shape for the
phase, each following the back line's moves by his own share, so lines never move in lock-step.
All of it is worked out in the team's frame (x metres from its own goal line, L below y = 34)
and turned onto the pitch by `formations.to_pitch`. Pure and deterministic: the same moment,
positions and seed give the same targets.
"""

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache, lru_cache

from matchlens.events import PITCH_LENGTH, PITCH_WIDTH
from matchlens.formations import Slot, to_pitch
from matchlens.league import Club, Player
from matchlens.movement import EDGE_BAND, Body, Limits, pace_to_arrive

MIDDLE = PITCH_WIDTH / 2
HALFWAY = PITCH_LENGTH / 2
# the back line out of possession: this far behind the ball, never deeper than LINE_DEEPEST and
# never higher than the club's cap (a deep block's 28 m, a high line's 45 m); in possession it
# pushes up behind the ball
LINE_DEEPEST = 6.0
GAP_OUT = (27.0, 19.0)  # the gap to the ball for line height 0 and 1
CAP_OUT = (28.0, 45.0)
GAP_IN = (30.0, 24.0)
CAP_IN = (40.0, 55.0)
# each player follows the back line's moves from where it stands with the ball on halfway by his
# own share, drawn once per player and seed
FOLLOW = (0.75, 1.0)
# how far the shape leans towards the ball's side: the share of the ball's offset from the middle
PULL = {"attack": 0.25, "defend": 0.40}
WIDTH_FACTOR = (0.85, 1.15)  # the shapes' widths are scaled by this for width 0 and 1
# the keeper: his distance from the goal line along the line to the ball, by the ball's x
KEEPER_DEPTH = (2.0, 22.0)  # nearest and furthest
KEEPER_DEPTH_FROM_BALL = (10.0, 0.30)  # depth = nearest + 0.30 per metre the ball is beyond 10 m
KEEPER_BEHIND_LINE = 1.5  # with the ball in his half, at least this far behind his back line
# pressing: who and how far; a club with press 0.5 or more sends two, the second to cover
PRESS_TRIGGER = (6.0, 20.0)  # metres from the carrier, for press 0 and 1
PRESS_LEAD_S = 0.3  # aims a little ahead of the carrier, and runs at his velocity
COVER_BEHIND, COVER_INSIDE = 4.0, 3.0  # the cover: goal-side of the carrier, and inside him
PRESSERS_APART = 2.0  # the two pressers' points never nearer than this (near the goal they meet)
# marking: an opponent within this of a defender's slot is marked, MARK_GAP metres goal-side
MARK_RADIUS = 12.0
MARK_GAP = 2.0
MARK_WEIGHT = 0.6  # the rest stays with the shape
MARK_CLOSE = 6.0  # within this of his man a marker also runs with him; further off he holds a zone
MARK_SWITCH = 3.0  # a marker keeps his man until another is this much nearer his slot
# runs: in each player's own window of RUN_EVERY_S he may make one, for its first RUN_FOR_S, with
# odds work rate x RUN_ODDS, and a pace RUN_PACE_EXTRA above his ordinary one
RUN_EVERY_S = 8.0
RUN_FOR_S = 4.0
RUN_ODDS = 0.25
RUN_PACE_EXTRA = 1.0
OFFSIDE_MARGIN = 0.5
# a smooth drift around the slot: amplitude and period range, by player, period and seed
DRIFT_M = 2.0
DRIFT_PERIOD_S = (25.0, 45.0)
# the pace to a point by how far it is: a walk within WALK_WITHIN, then growing with the distance
# up to a jog's cap that rises with the work rate; from FAR it ramps to a hard run at FAR_FULL
WALK_WITHIN, WALK = 1.0, 1.0
PACE_BASE, PACE_PER_M = 0.8, 0.3
JOG_CAP = (2.6, 3.8)  # at work rate 0 and 1
FAR, FAR_FULL, FAR_PACE = 25.0, 40.0, (5.0, 6.5)
PRESS_PACE = (4.0, 7.0)  # at press 0 and 1
# how hard an ordinary arrival brakes, as a share of the player's acceleration; pressing, a
# receiver and a carrier brake as hard as they can
COMFORT_BRAKING = 0.6


@dataclass(frozen=True)
class Team:
    club: Club
    slots: Mapping[str, Slot]  # outfield player id -> his slot
    keeper: str
    attacks_right: bool


@dataclass(frozen=True)
class Moment:
    ball: tuple[float, float]
    possession: str | None  # the club in possession; None while the ball is loose or dead
    half_s: float = 0.0  # seconds into the half
    carrier: str | None = None
    carry_to: tuple[float, float] | None = None
    carry_pace: float = 0.0
    receiver: str | None = None
    landing: tuple[float, float] | None = None
    lands_in_s: float = 0.0
    period: int = 1


@dataclass(frozen=True)
class Aim:
    """Where a player heads on the pitch, the pace he closes on it at (m/s), the point's own
    velocity, and the share of his acceleration he brakes with on arrival. A caller that keeps
    an aim between refreshes moves its point on by velocity x elapsed time; held still, a moving
    aim is overrun by about the braking distance at its speed."""

    point: tuple[float, float]
    pace: float
    velocity: tuple[float, float] = (0.0, 0.0)
    braking: float = 1.0
    mark: str | None = None  # the opponent he marks, for the next call's `marks`


def targets(
    moment: Moment,
    teams: tuple[Team, Team],
    at: Mapping[str, tuple[float, float]],
    velocity: Mapping[str, tuple[float, float]],
    players: Mapping[str, Player],
    seed: int,
    marks: Mapping[str, str] | None = None,
) -> dict[str, Aim]:
    """Every player's aim at `moment`; `at` and `velocity` hold everyone's now, `marks` whom each
    marker marked at the previous call (its aims' `mark`), so he keeps his man (`marking`)."""
    if moment.carrier is not None and moment.carry_to is None:
        raise ValueError(f"carrier {moment.carrier} has no carry_to")
    if moment.receiver is not None and (moment.landing is None or not moment.lands_in_s > 0.0):
        raise ValueError(f"receiver {moment.receiver} has no landing in a positive time")
    out: dict[str, Aim] = {}
    for team, other in (teams, teams[::-1]):
        out |= _team_targets(moment, team, other, at, velocity, players, seed, marks or {})
    return out


def _team_targets(moment, team, other, at, velocity, players, seed, marks) -> dict[str, Aim]:
    frame = team.attacks_right

    def mine(point):  # pitch -> this team's frame (the turn is its own inverse)
        return to_pitch(point[0], point[1], frame)

    def their_velocity(pid):
        vx, vy = velocity.get(pid, (0.0, 0.0))
        return (vx, vy) if frame else (-vx, -vy)

    ball = mine(moment.ball)
    attacking = moment.possession == team.club.id
    phase = "attack" if attacking else "defend"
    tactics = team.club.tactics
    line = back_line(ball[0], attacking, tactics.line_height)
    rest = back_line(HALFWAY, attacking, tactics.line_height)  # the line with the ball on halfway
    offside = offside_line(ball, [mine(at[o]) for o in (*other.slots, other.keeper)])
    theirs = {o: mine(at[o]) for o in other.slots}  # the outfield opponents, in this frame
    out: dict[str, Aim] = {}

    def put(pid, point, pace, moving=(0.0, 0.0), braking=COMFORT_BRAKING, mark=None):
        x = min(PITCH_LENGTH - EDGE_BAND, max(EDGE_BAND, point[0]))
        y = min(PITCH_WIDTH - EDGE_BAND, max(EDGE_BAND, point[1]))
        turn = 1.0 if frame else -1.0  # a velocity turns with the frame, without the shift
        out[pid] = Aim(
            to_pitch(x, y, frame),
            max(0.0, min(pace, players[pid].top_speed)),
            (turn * moving[0] + 0.0, turn * moving[1] + 0.0),
            braking,
            mark,
        )

    # the carrier and the receiver first, a keeper too
    for pid in (*team.slots, team.keeper):
        if pid == moment.carrier:
            put(pid, mine(moment.carry_to), moment.carry_pace, braking=1.0)
        elif pid == moment.receiver:
            p = players[pid]
            body = Body(*at[pid], *velocity.get(pid, (0.0, 0.0)))
            limits = Limits(p.top_speed, p.acceleration)
            pace = pace_to_arrive(body, moment.landing, moment.lands_in_s, limits)
            put(pid, mine(moment.landing), pace, braking=1.0)
    # pressing the other side's carrier, a keeper too, by anyone but the receiver
    if not attacking and moment.carrier in (*other.slots, other.keeper):
        carrier_at = mine(at[moment.carrier])
        cv = their_velocity(moment.carrier)
        lead = (carrier_at[0] + cv[0] * PRESS_LEAD_S, carrier_at[1] + cv[1] * PRESS_LEAD_S)
        free = {p: mine(at[p]) for p in team.slots if p not in out}
        pace = _between(PRESS_PACE, tactics.press)
        first, cover = band(goal_side(lead, MARK_GAP / 2)), band(cover_point(lead))
        if math.dist(first, cover) < PRESSERS_APART:
            # in front of his own goal both points end on its line: the cover steps aside
            cover = (first[0], first[1] + math.copysign(PRESSERS_APART, MIDDLE - first[1] + 0.0))
        for i, pid in enumerate(pressing(carrier_at, free, tactics.press)):
            put(pid, first if i == 0 else cover, pace, cv, 1.0)
    for pid, slot in team.slots.items():
        if pid in out:
            continue
        here = mine(at[pid])
        own_line = rest + _between(FOLLOW, _unit(seed, pid, "follow")) * (line - rest)
        point = shape_point(slot, phase, own_line, ball, tactics.width)
        work = players[pid].work_rate
        if attacking:
            run = run_point(
                pid, slot, point, ball, offside, work, moment.half_s, seed, moment.period
            )
            if run is not None:
                put(pid, run, pace_to(here, run, work) + RUN_PACE_EXTRA)
                continue
            # the drift first, then onside: a drift must not carry him past the line
            point = drifted(point, pid, moment.half_s, seed, moment.period)
            point = (min(point[0], offside - OFFSIDE_MARGIN), point[1])
            put(pid, point, pace_to(here, point, work))
            continue
        # out of possession (or with the ball loose): mark the nearest opponent near the slot
        moving = (0.0, 0.0)
        marked = marking(point, theirs, marks.get(pid))
        if marked is not None:
            guard = goal_side(mine(at[marked]), MARK_GAP)
            point = (
                MARK_WEIGHT * guard[0] + (1 - MARK_WEIGHT) * point[0],
                MARK_WEIGHT * guard[1] + (1 - MARK_WEIGHT) * point[1],
            )
            if math.dist(here, mine(at[marked])) <= MARK_CLOSE:
                mv = their_velocity(marked)
                moving = (MARK_WEIGHT * mv[0], MARK_WEIGHT * mv[1])
        point = drifted(point, pid, moment.half_s, seed, moment.period)
        put(pid, point, pace_to(here, point, work), moving, mark=marked)
    if team.keeper not in out:
        spot = keeper_point(ball, line if ball[0] < HALFWAY else None)
        work = players[team.keeper].work_rate
        put(team.keeper, spot, pace_to(mine(at[team.keeper]), spot, work))
    return out


def back_line(ball_x: float, attacking: bool, line_height: float) -> float:
    """The back line's x in the team's frame for the ball at `ball_x`."""
    gap = _between(GAP_IN if attacking else GAP_OUT, line_height)
    cap = _between(CAP_IN if attacking else CAP_OUT, line_height)
    return min(cap, max(LINE_DEEPEST, ball_x - gap))


def offside_line(ball: tuple[float, float], opponents: list[tuple[float, float]]) -> float:
    """The furthest x a player of the team may stand at without being offside: the second-last
    opponent's x, but never short of the ball or of the halfway line."""
    second_last = sorted((p[0] for p in opponents), reverse=True)[1]
    return max(second_last, ball[0], HALFWAY)


def shape_point(
    slot: Slot, phase: str, line: float, ball: tuple[float, float], width: float
) -> tuple[float, float]:
    """A slot's point: on the back line plus its dx, its y spread by the club's width and leaning
    towards the ball's side."""
    dx, y = getattr(slot, phase)
    spread = _between(WIDTH_FACTOR, width)
    return line + dx, MIDDLE + (y - MIDDLE) * spread + PULL[phase] * (ball[1] - MIDDLE)


def keeper_point(ball: tuple[float, float], line: float | None = None) -> tuple[float, float]:
    """On the line from the goal's centre to the ball, as deep as the ball's distance allows;
    given his back line (the ball in his half), at least KEEPER_BEHIND_LINE behind it."""
    nearest, furthest = KEEPER_DEPTH
    start, per_metre = KEEPER_DEPTH_FROM_BALL
    depth = min(furthest, max(nearest, nearest + per_metre * (ball[0] - start)))
    dx, dy = ball[0], ball[1] - MIDDLE
    reach = math.hypot(dx, dy)
    if reach <= depth:
        x, y = ball
    else:
        x, y = dx * depth / reach, MIDDLE + dy * depth / reach
    if line is not None and x > line - KEEPER_BEHIND_LINE:
        share = (line - KEEPER_BEHIND_LINE) / x
        x, y = x * share, MIDDLE + (y - MIDDLE) * share
    return x, y


def pressing(
    carrier: tuple[float, float], at: Mapping[str, tuple[float, float]], press: float
) -> list[str]:
    """Of the candidates in `at`, the one or two nearest the carrier within the trigger
    distance."""
    trigger = _between(PRESS_TRIGGER, press)
    count = 2 if press >= 0.5 else 1
    near = sorted((math.dist(p, carrier), pid) for pid, p in at.items())
    return [pid for d, pid in near[:count] if d <= trigger]


def cover_point(lead: tuple[float, float]) -> tuple[float, float]:
    """The second presser's point: COVER_BEHIND goal-side of the carrier and COVER_INSIDE
    nearer the middle, so the two never stand on one spot."""
    x, y = goal_side(lead, COVER_BEHIND)
    return x, y + math.copysign(min(COVER_INSIDE, abs(MIDDLE - y)), MIDDLE - y)


def goal_side(point: tuple[float, float], gap: float) -> tuple[float, float]:
    """`gap` metres from `point` towards the team's own goal centre."""
    dx, dy = -point[0], MIDDLE - point[1]
    d = math.hypot(dx, dy)
    if d <= gap:
        return (0.0, MIDDLE)
    return (point[0] + dx * gap / d, point[1] + dy * gap / d)


def nearest(
    point: tuple[float, float], others: Mapping[str, tuple[float, float]], radius: float
) -> str | None:
    """The id of the player in `others` nearest `point`, if within `radius`."""
    best = min(sorted(others), key=lambda o: math.dist(others[o], point), default=None)
    return best if best is not None and math.dist(others[best], point) <= radius else None


def marking(
    point: tuple[float, float], others: Mapping[str, tuple[float, float]], kept: str | None
) -> str | None:
    """Whom a defender whose slot is at `point` marks: the opponent he marked before (`kept`) while
    he is within MARK_RADIUS of it and no other is MARK_SWITCH metres nearer it, else the nearest
    within the radius (`nearest`), so two opponents crossing do not make him switch to and fro."""
    best = nearest(point, others, MARK_RADIUS)
    if kept not in others or (held := math.dist(others[kept], point)) > MARK_RADIUS:
        return best
    return kept if best is None or math.dist(others[best], point) > held - MARK_SWITCH else best


def run_point(
    pid: str,
    slot: Slot,
    point: tuple[float, float],
    ball: tuple[float, float],
    offside: float,
    work_rate: float,
    half_s: float,
    seed: int,
    period: int = 1,
) -> tuple[float, float] | None:
    """A run, if this player makes one now: a full-back overlapping on the ball's side, a winger
    coming inside, a striker on the last defender's shoulder; None otherwise. Each player's
    windows are shifted by his own offset, so runs neither start nor end together."""
    t = half_s + RUN_EVERY_S * _unit(seed, pid, "run-offset")
    if t % RUN_EVERY_S >= RUN_FOR_S or ball[0] < HALFWAY:
        return None
    if _unit(seed, pid, "run", period, int(t // RUN_EVERY_S)) >= work_rate * RUN_ODDS:
        return None
    same_side = (point[1] - MIDDLE) * (ball[1] - MIDDLE) > 0
    if slot.role == "FB" and same_side:
        return (
            min(ball[0] + 8.0, offside - OFFSIDE_MARGIN),
            point[1] + math.copysign(4.0, point[1] - MIDDLE),
        )
    if slot.role == "W":
        return (min(point[0] + 4.0, offside - OFFSIDE_MARGIN), MIDDLE + (point[1] - MIDDLE) * 0.5)
    if slot.role == "ST":
        return (offside - OFFSIDE_MARGIN, point[1])
    return None


def drifted(
    point: tuple[float, float], pid: str, half_s: float, seed: int, period: int = 1
) -> tuple[float, float]:
    """`point` plus a smooth drift of up to DRIFT_M metres, its periods and phases by player,
    period and seed: a sine per axis, so the target moves slowly and steadily."""
    (wx, px), (wy, py) = _drift(seed, pid, period)
    return (
        point[0] + DRIFT_M * math.sin(wx * half_s + px),
        point[1] + DRIFT_M * math.sin(wy * half_s + py),
    )


@cache
def _drift(seed: int, pid: str, period: int) -> tuple[tuple[float, float], tuple[float, float]]:
    """Per axis the drift's angular frequency and phase, drawn once per player, period and seed."""
    low, high = DRIFT_PERIOD_S
    return tuple(
        (
            2 * math.pi / (low + (high - low) * _unit(seed, pid, "period", period, axis)),
            2 * math.pi * _unit(seed, pid, "phase", period, axis),
        )
        for axis in (0, 1)
    )


def pace_to(here: tuple[float, float], there: tuple[float, float], work_rate: float) -> float:
    """The pace a player takes to a point this far away: a walk, a pace growing with the distance
    up to his jog's cap, and from FAR a ramp to a hard run at FAR_FULL."""
    d = math.dist(here, there)
    if d < WALK_WITHIN:
        return WALK
    cap = _between(JOG_CAP, work_rate)
    if d <= FAR:
        return min(cap, PACE_BASE + PACE_PER_M * d)
    share = min(1.0, (d - FAR) / (FAR_FULL - FAR))
    return cap + (_between(FAR_PACE, work_rate) - cap) * share


def band(point: tuple[float, float]) -> tuple[float, float]:
    """`point` kept inside the band along the pitch's edges (in either frame: it is symmetric)."""
    return (
        min(PITCH_LENGTH - EDGE_BAND, max(EDGE_BAND, point[0])),
        min(PITCH_WIDTH - EDGE_BAND, max(EDGE_BAND, point[1])),
    )


def _between(ends: tuple[float, float], share: float) -> float:
    return ends[0] + (ends[1] - ends[0]) * share


# asked for every player at every refresh, about 0.5 M calls a match; typed, as str(1) != str(1.0)
@lru_cache(maxsize=4096, typed=True)
def _unit(seed: int, *key) -> float:
    """A number in [0, 1) from the seed and a key, the same on every machine (no hash())."""
    text = "|".join(str(k) for k in (seed, *key)).encode()
    return int.from_bytes(hashlib.sha256(text).digest()[:8], "big") / 2**64
