"""Movement layer of generator v2: players move every 100 ms towards a target, under their limits.

Pure and deterministic. A player has a position and a velocity; each step he wants the velocity
that points at his target at the pace he is asked for, but never faster than his top speed nor
than the speed from which he can still stop on the target (braking at his acceleration on the
100 ms grid), and his velocity changes by at most his acceleration per step, as a vector, so a
turn takes several steps. Fatigue lowers both limits late in a half, more for a low stamina.
"""

import math
from dataclasses import dataclass
from typing import NamedTuple

from matchlens.events import PITCH_LENGTH, PITCH_WIDTH

DT = 0.1  # s, one step: the tracking's 10 Hz
# fatigue: from this minute of a half the limits fall linearly, by at most FATIGUE_DROP for a
# stamina of 0 at the half's 45th minute and after it (stoppage time); a stamina of 1 never tires
FATIGUE_FROM_S = 30 * 60
FATIGUE_FULL_S = 45 * 60
FATIGUE_DROP = 0.10
# targets stay this far inside the pitch, and a player brakes for the edge as if it were this much
# nearer: the band keeps a turn near the line, which shares the acceleration between the two axes,
# from carrying him over it
EDGE_BAND = 0.5
# no run on a pitch is this long; from further away any speed still stops in time
FAR_ENOUGH_M = 1000.0
# the gentlest share of his acceleration a player brakes with on arrival
MIN_BRAKING = 0.25
_X_BAND = PITCH_LENGTH - EDGE_BAND
_Y_BAND = PITCH_WIDTH - EDGE_BAND
_SQRT2 = math.sqrt(2.0)


class Body(NamedTuple):
    """A player's position (m) and velocity (m/s). A named tuple, not a frozen dataclass: `step`
    builds about 2 M of them a match, at half the cost."""

    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0

    @property
    def speed(self) -> float:
        return math.hypot(self.vx, self.vy)


@dataclass(frozen=True)
class Limits:
    top_speed: float  # m/s
    acceleration: float  # m/s², also the braking

    def tired(self, stamina: float, half_s: float) -> "Limits":
        """The limits at `half_s` seconds into a half for a player of this stamina (0 to 1)."""
        late = min(1.0, max(0.0, (half_s - FATIGUE_FROM_S) / (FATIGUE_FULL_S - FATIGUE_FROM_S)))
        factor = 1.0 - FATIGUE_DROP * (1.0 - stamina) * late
        return Limits(self.top_speed * factor, self.acceleration * factor)


def stopping_speed(distance: float, acceleration: float) -> float:
    """The highest speed for the next step from which a player still stops on a point
    `distance` metres ahead, braking by `acceleration` on the 100 ms grid: after moving `s * DT`
    he still covers `(s - dv) * DT + (s - 2 dv) * DT + ...` (dv = acceleration * DT) and no more."""
    if distance <= 0.0:
        return 0.0
    if distance > FAR_ENOUGH_M:
        return math.inf
    dv = acceleration * DT
    # S(s) = DT * sum over k = 0..m of (s - k dv), m = floor(s / dv): increasing and piecewise
    # linear in s; solve DT * S(s) = distance on the piece where floor(s / dv) = m
    m = max(0, int(math.sqrt(0.25 + 2.0 * distance / (dv * DT)) - 0.5) - 1)
    while True:
        s = (distance / DT + dv * m * (m + 1) / 2.0) / (m + 1)
        if s < (m + 1) * dv:
            return s
        m += 1


def braking_distance(speed: float, acceleration: float) -> float:
    """How far a player moving at `speed` on the next step still runs until he stands, braking by
    `acceleration` on the 100 ms grid: the inverse of `stopping_speed`."""
    if speed <= 0.0:
        return 0.0
    dv = acceleration * DT
    m = int(speed / dv)
    return DT * ((m + 1) * speed - dv * m * (m + 1) / 2.0)


def braking_bound(speed: float, acceleration: float) -> float:
    """A distance from beyond which a player moving at `speed` surely stops in time: so
    `stopping_speed` of any distance beyond it is at least `speed`. `braking_distance` =
    DT ((m+1) s - dv m (m+1) / 2), m = floor(s / dv), is at most its top over a real m (at
    s / dv - 1/2), s² / 2a + s DT / 2 + a DT² / 8; plus a micrometre, far above the rounding."""
    return (
        speed * speed / (2.0 * acceleration)
        + speed * DT / 2.0
        + acceleration * DT * DT / 8.0
        + 1e-6
    )


def step(
    body: Body,
    target: tuple[float, float],
    pace: float,
    limits: Limits,
    target_velocity: tuple[float, float] = (0.0, 0.0),
    braking: float = 1.0,
) -> Body:
    """One 100 ms step towards `target`, closing on it at `pace` m/s (capped by the top speed); a
    target that moves at `target_velocity` is followed at its speed plus the closing pace, so a
    pursuer does not trail it by his braking distance. `braking` is the share of his acceleration
    he brakes with on arrival (an ordinary arrival brakes gently; the edges always get all of it).

    A body that started at rest inside the band and moved only by `step` keeps every limit; one
    built by hand that runs at an edge faster than he could stop from is braked at once, beyond
    his acceleration. Limits are meant to change only slowly (fatigue): a speed above a new top
    speed falls to it at once, so slow a player down by his pace, not by his limits."""
    tx, ty = target
    tvx, tvy = target_velocity
    finite = math.isfinite
    if (
        not (finite(tx) and finite(ty) and finite(tvx) and finite(tvy) and finite(pace))
        or pace < 0.0
    ):
        raise ValueError(f"target {target}, its velocity {target_velocity}, pace {pace}")
    if not MIN_BRAKING <= braking <= 1.0:
        raise ValueError(f"braking share {braking} is not in {MIN_BRAKING}-1")
    # the clamps are min(high, max(low, v)) written out, a tie resolved as min and max do: this
    # runs about 2 M times a match
    tx = tx if tx > EDGE_BAND else EDGE_BAND
    tx = tx if tx < _X_BAND else _X_BAND
    ty = ty if ty > EDGE_BAND else EDGE_BAND
    ty = ty if ty < _Y_BAND else _Y_BAND
    bx, by, bvx, bvy = body
    dx, dy = tx - bx, ty - by
    distance = math.hypot(dx, dy)
    top, a = limits.top_speed, limits.acceleration
    dv = a * DT
    wx, wy = tvx, tvy
    if distance > 0.0:
        # at most distance / DT, so the last step lands on the target
        closing = top if top < pace else pace
        # stopping_speed only where it can bind: it skips 4 calls in 5
        brake = a * braking
        if distance <= braking_bound(closing, brake):
            stopping = stopping_speed(distance, brake)
            if stopping < closing:
                closing = stopping
        wx += dx / distance * closing
        wy += dy / distance * closing
    wanted = math.hypot(wx, wy)
    if wanted > top:
        wx, wy = wx * top / wanted, wy * top / wanted
    cx, cy = wx - bvx, wy - bvy
    change = math.hypot(cx, cy)
    if change > dv:
        cx, cy = cx * dv / change, cy * dv / change
    edge_braking = a / _SQRT2
    vx, forced_x = _for_the_edge(bvx, cx, bx, PITCH_LENGTH, edge_braking)
    vy, forced_y = _for_the_edge(bvy, cy, by, PITCH_WIDTH, edge_braking)
    # braking for an edge comes first; the other axis gets what is left of the change
    if forced_x != forced_y:
        if forced_x:
            vy = bvy + _share_left(vx - bvx, vy - bvy, dv)
        else:
            vx = bvx + _share_left(vy - bvy, vx - bvx, dv)
    speed = math.hypot(vx, vy)
    if speed > top:  # tired limits can fall below a speed already reached
        vx, vy = vx * top / speed, vy * top / speed
    x = bx + vx * DT
    x = x if x > 0.0 else 0.0
    x = x if x < PITCH_LENGTH else PITCH_LENGTH
    y = by + vy * DT
    y = y if y > 0.0 else 0.0
    y = y if y < PITCH_WIDTH else PITCH_WIDTH
    return Body(x, y, (x - bx) / DT, (y - by) / DT)


def _for_the_edge(
    v: float, change: float, at: float, size: float, braking: float
) -> tuple[float, bool]:
    """The velocity along one axis after `change`, cut to what still stops EDGE_BAND short of the
    edge it moves to, braking at `braking` (the acceleration / sqrt(2): what is left when both
    axes brake at once, in a corner), and whether the edge forced a bigger change than the target
    asked for, or one the other way (braking where he asked to speed up), not merely a shorter
    one. Only the edge ahead can bind, and the cheap braking distance tells whether it does."""
    wanted = v + change
    room = (size - EDGE_BAND - at) if wanted > 0.0 else (at - EDGE_BAND)
    # braking_distance(abs(wanted), braking) written out: this runs about 4 M times a match
    speed = abs(wanted)
    if speed <= 0.0:
        ahead = 0.0
    else:
        dv = braking * DT
        m = int(speed / dv)
        ahead = DT * ((m + 1) * speed - dv * m * (m + 1) / 2.0)
    if ahead <= room:
        return wanted, False
    bounded = math.copysign(stopping_speed(room, braking), wanted)
    made = bounded - v
    return bounded, abs(made) > abs(change) or made * change < 0.0


def _share_left(forced: float, free: float, dv: float) -> float:
    """The free axis's change, shortened so that both together stay within `dv`."""
    room = math.sqrt(max(0.0, dv * dv - forced * forced))
    return max(-room, min(room, free))


ARRIVED_M = 0.01  # nearer than this to his target, a player has arrived


def pace_to_arrive(
    body: Body,
    target: tuple[float, float],
    within_s: float,
    limits: Limits,
    braking: float = 1.0,
) -> float:
    """The lowest pace at which `step` brings him onto `target` within `within_s` seconds, run
    up and braking included; his top speed when even that is too late. Worked out by stepping
    (a bisection of 12 rounds), so it agrees with `step` exactly."""
    tx = min(PITCH_LENGTH - EDGE_BAND, max(EDGE_BAND, target[0]))
    ty = min(PITCH_WIDTH - EDGE_BAND, max(EDGE_BAND, target[1]))
    steps = int(within_s / DT + 1e-9)

    def arrives(pace: float) -> bool:
        b = body
        for _ in range(steps):
            b = step(b, (tx, ty), pace, limits, braking=braking)
            if math.hypot(tx - b.x, ty - b.y) < ARRIVED_M:
                return True
        return math.hypot(tx - b.x, ty - b.y) < ARRIVED_M

    if not arrives(limits.top_speed):
        return limits.top_speed
    low, high = 0.0, limits.top_speed
    for _ in range(12):
        mid = (low + high) / 2.0
        low, high = (low, mid) if arrives(mid) else (mid, high)
    return high


REACH_WITHIN_S = 30.0  # time_to_reach looks no further ahead: no run on the pitch takes longer


def time_to_reach(
    body: Body,
    target: tuple[float, float],
    limits: Limits,
    within_s: float = REACH_WITHIN_S,
) -> float:
    """The least time in which `step` brings him onto `target`: at his top speed, run-up and
    full braking included, on the 100 ms grid; `math.inf` if not within `within_s`. The
    counterpart of `pace_to_arrive`: within this time some pace gets him there, within 100 ms less
    none does."""
    tx = min(PITCH_LENGTH - EDGE_BAND, max(EDGE_BAND, target[0]))
    ty = min(PITCH_WIDTH - EDGE_BAND, max(EDGE_BAND, target[1]))
    if math.hypot(tx - body.x, ty - body.y) < ARRIVED_M:
        return 0.0
    b = body
    for k in range(1, int(within_s / DT + 1e-9) + 1):
        b = step(b, (tx, ty), limits.top_speed, limits)
        if math.hypot(tx - b.x, ty - b.y) < ARRIVED_M:
            return round(k * DT, 9)
    return math.inf
